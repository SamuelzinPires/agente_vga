"""
Camada unica de acesso a LLM.

Principal:  Gemini (Google AI Studio) - free tier, saida JSON nativa.
Fallback:   Groq (llama-3.3-70b-versatile) - assume automaticamente quando o
            Gemini estoura cota, e derrubado por rate limit ou devolve lixo.

O resto do projeto so conhece `chamar_llm_json()`. Trocar de provider e mexer
em variavel de ambiente, nao em codigo espalhado.
"""

import json
import logging
import os
import re
import time

logger = logging.getLogger(__name__)

MODELO_GEMINI = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
MODELO_GROQ = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

TENTATIVAS_POR_PROVIDER = 2
ESPERA_BASE_SEGUNDOS = 8

# Disjuntor: quando um provider falha esta quantidade de vezes seguidas na mesma
# execucao, ele sai de cena ate a proxima rodada. Sem isso, um provider fora do
# ar cobra a espera de retry em TODAS as vagas da fila - com 30 vagas, sao
# minutos jogados fora esperando algo que ja se sabe que nao vai responder.
FALHAS_PARA_DESLIGAR = 2
_falhas_seguidas: dict[str, int] = {}


class LLMIndisponivelError(RuntimeError):
    """Nenhum provider conseguiu responder com JSON valido."""


def _e_erro_recuperavel(erro: Exception) -> bool:
    """
    Erro que vale tentar de novo no MESMO provider antes de trocar.

    Cobre dois casos distintos:
      - cota / rate limit (429): esperar as vezes resolve;
      - indisponibilidade temporaria (503 UNAVAILABLE, "high demand"): comum no
        free tier do Gemini nos modelos mais novos, e some sozinho.
    Erro de modelo inexistente (404) NAO entra aqui: insistir nao adianta.
    """
    texto = f"{type(erro).__name__} {erro}".lower()
    marcadores = [
        "429", "resource_exhausted", "quota", "rate limit", "ratelimit",
        "too many requests", "exceeded",
        "503", "unavailable", "high demand", "overloaded", "500", "internal error",
        "timeout", "timed out",
    ]
    return any(m in texto for m in marcadores)


def _extrair_json(texto: str) -> dict:
    """
    Converte a resposta em dict. Tenta o parse direto e, se o modelo devolver
    o JSON embrulhado em markdown ou com texto em volta, recorta o primeiro
    objeto valido.
    """
    if not texto:
        raise ValueError("Resposta vazia do modelo.")

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        pass

    limpo = re.sub(r"^```(?:json)?|```$", "", texto.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        pass

    inicio = limpo.find("{")
    fim = limpo.rfind("}")
    if inicio != -1 and fim > inicio:
        return json.loads(limpo[inicio:fim + 1])

    raise ValueError(f"Nao foi possivel extrair JSON da resposta: {texto[:200]}...")


def _chamar_gemini(prompt: str) -> dict:
    from google import genai
    from google.genai import types

    cliente = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    resposta = cliente.models.generate_content(
        model=MODELO_GEMINI,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    return _extrair_json(resposta.text)


def _chamar_groq(prompt: str) -> dict:
    from groq import Groq

    cliente = Groq(api_key=os.getenv("GROQ_API_KEY"))
    resposta = cliente.chat.completions.create(
        model=MODELO_GROQ,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    return _extrair_json(resposta.choices[0].message.content)


def _tentar_provider(nome: str, funcao, prompt: str) -> dict:
    """Executa um provider com retry. Devolve None se ele nao servir agora."""
    for tentativa in range(1, TENTATIVAS_POR_PROVIDER + 1):
        try:
            return funcao(prompt)
        except Exception as erro:
            if _e_erro_recuperavel(erro):
                if tentativa < TENTATIVAS_POR_PROVIDER:
                    espera = ESPERA_BASE_SEGUNDOS * tentativa
                    print(f"[LLM] {nome}: indisponivel agora. Aguardando {espera}s ({tentativa}/{TENTATIVAS_POR_PROVIDER})...")
                    time.sleep(espera)
                    continue
                print(f"[LLM] {nome}: seguiu indisponivel. Passando para o proximo provider.")
                return None
            print(f"[LLM] {nome}: falhou ({type(erro).__name__}: {erro}). Passando para o proximo provider.")
            return None
    return None


def chamar_llm_json(prompt: str) -> tuple[dict, str]:
    """
    Manda o prompt para o primeiro provider disponivel e devolve (resultado, provider).

    Sem chave nenhuma configurada, levanta LLMIndisponivelError - nunca devolve
    dado inventado, porque esse dado viraria conteudo de curriculo.
    """
    providers = []
    if os.getenv("GEMINI_API_KEY"):
        providers.append((f"Gemini/{MODELO_GEMINI}", _chamar_gemini))
    if os.getenv("GROQ_API_KEY"):
        providers.append((f"Groq/{MODELO_GROQ}", _chamar_groq))

    if not providers:
        raise LLMIndisponivelError(
            "Nenhuma chave de IA configurada. Defina GEMINI_API_KEY e/ou GROQ_API_KEY no .env."
        )

    if all(_falhas_seguidas.get(nome, 0) >= FALHAS_PARA_DESLIGAR for nome, _ in providers):
        raise LLMIndisponivelError(
            "Todos os providers foram desligados nesta rodada apos falhas seguidas."
        )

    for nome, funcao in providers:
        if _falhas_seguidas.get(nome, 0) >= FALHAS_PARA_DESLIGAR:
            continue

        resultado = _tentar_provider(nome, funcao, prompt)
        if resultado is not None:
            _falhas_seguidas[nome] = 0
            print(f"[LLM] Resposta obtida via {nome}.")
            return resultado, nome

        _falhas_seguidas[nome] = _falhas_seguidas.get(nome, 0) + 1
        if _falhas_seguidas[nome] == FALHAS_PARA_DESLIGAR:
            print(f"[LLM] {nome} desligado nesta rodada apos {FALHAS_PARA_DESLIGAR} falhas seguidas.")

    raise LLMIndisponivelError(
        "Todos os providers de IA falharam nesta rodada (cota esgotada ou erro de API)."
    )
