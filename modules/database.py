"""
Persistencia: dedupe e historico das vagas analisadas.

Grava em dois lugares:
  - Supabase  -> fonte real de dedupe. No GitHub Actions o runner e efemero,
                 entao SEM Supabase o agente reenvia as mesmas vagas todo dia.
  - JSON local -> conveniencia para rodar na sua maquina (esta no .gitignore).
"""

import json
import os
import re
from datetime import datetime
from typing import Any, Optional

from dotenv import load_dotenv

try:
    from supabase import Client, create_client
except ImportError:
    Client = None
    create_client = None

ARQUIVO_LOCAL = "vagas_processadas.json"
TABELA = "vagas_processadas"


def inicializar_supabase() -> Optional["Client"]:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_file = os.path.join(base_dir, ".env")
    if os.path.exists(env_file):
        load_dotenv(dotenv_path=env_file, override=True)
    else:
        load_dotenv(override=True)

    url = os.getenv("SUPABASE_URL", "").strip().strip('"').strip("'")
    chave = os.getenv("SUPABASE_KEY", "").strip().strip('"').strip("'")

    if url and not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # O painel do Supabase mostra a URL ja com "/rest/v1/" no fim, mas o cliente
    # monta esse caminho sozinho - colar como esta gera 404 em toda consulta.
    url = re.sub(r"/rest/v\d+/?$", "", url.rstrip("/"))

    if not url or not chave or create_client is None:
        print("[AVISO] Supabase nao configurado. Dedupe so vai funcionar localmente.")
        return None

    try:
        return create_client(url, chave)
    except Exception as erro:
        print(f"[ERRO SUPABASE] {erro}")
        return None


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "").lower().strip())


def _normalizar_url(url: str) -> str:
    return str(url or "").split("?")[0].rstrip("/").lower().strip()


def _carregar_local() -> list:
    if not os.path.exists(ARQUIVO_LOCAL):
        return []
    try:
        with open(ARQUIVO_LOCAL, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)
    except Exception:
        return []


def _salvar_local(registros: list) -> None:
    try:
        with open(ARQUIVO_LOCAL, "w", encoding="utf-8") as arquivo:
            json.dump(registros, arquivo, ensure_ascii=False, indent=2)
    except Exception as erro:
        print(f"[AVISO] Nao foi possivel salvar o cache local: {erro}")


def vaga_ja_processada(supabase: Optional[Any], vaga: dict) -> bool:
    link = _normalizar_url(vaga.get("link", ""))
    titulo = _normalizar(vaga.get("titulo", ""))
    empresa = _normalizar(vaga.get("empresa", ""))

    for registro in _carregar_local():
        if link and link == _normalizar_url(registro.get("link_vaga", "")):
            return True
        if titulo and empresa and titulo == _normalizar(registro.get("titulo_vaga", "")) \
                and empresa == _normalizar(registro.get("empresa", "")):
            return True

    if not supabase:
        return False

    try:
        if link:
            resposta = supabase.table(TABELA).select("id").eq("link_vaga", vaga.get("link")).execute()
            if resposta.data:
                return True
        if titulo and empresa:
            resposta = supabase.table(TABELA).select("id") \
                .ilike("titulo_vaga", vaga.get("titulo", "")) \
                .ilike("empresa", vaga.get("empresa", "")).execute()
            if resposta.data:
                return True
    except Exception as erro:
        print(f"[AVISO] Falha ao consultar dedupe no Supabase: {erro}")

    return False


def salvar_vaga_processada(
    supabase: Optional[Any],
    vaga: dict,
    analise: dict,
    status: str = "notificada",
    provider_ia: str = "",
) -> None:
    registro = {
        "titulo_vaga": vaga.get("titulo"),
        "empresa": vaga.get("empresa"),
        "link_vaga": vaga.get("link"),
        "fonte": vaga.get("fonte"),
        "modalidade": vaga.get("modalidade") or None,
        "localizacao": vaga.get("localizacao"),
        "match_score": analise.get("match_score"),
        "justificativa": analise.get("justificativa_match"),
        "resumo_adaptado": analise.get("resumo_adaptado"),
        "status": status,
        "provider_ia": provider_ia,
    }

    locais = _carregar_local()
    link = _normalizar_url(registro["link_vaga"])
    if not any(link and link == _normalizar_url(r.get("link_vaga", "")) for r in locais):
        locais.append({**registro, "criado_em": datetime.now().isoformat()})
        _salvar_local(locais)

    if not supabase:
        print(f"[BANCO] '{registro['titulo_vaga']}' registrada apenas no cache local.")
        return

    try:
        supabase.table(TABELA).insert(registro).execute()
        print(f"[BANCO] '{registro['titulo_vaga']}' gravada no Supabase.")
    except Exception as erro:
        print(f"[ERRO BANCO] Falha ao gravar '{registro['titulo_vaga']}': {erro}")


def ultima_notificacao(supabase: Optional[Any]) -> Optional[datetime]:
    """
    Quando a ultima vaga foi notificada. Serve ao sinal de vida: sem isso o
    agente nao consegue distinguir "mercado parado ha 3 dias" de "rodei agora".
    Devolve None se o banco nao responder - o chamador trata como "faz tempo".
    """
    if not supabase:
        return None
    try:
        resposta = (
            supabase.table(TABELA)
            .select("created_at")
            .eq("status", "notificada")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if resposta.data:
            return datetime.fromisoformat(resposta.data[0]["created_at"].replace("Z", "+00:00"))
    except Exception as erro:
        print(f"[AVISO] Falha ao consultar ultima notificacao: {erro}")
    return None
