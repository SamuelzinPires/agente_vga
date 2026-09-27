"""
Notificacao no Telegram.

Sem auto-apply: o agente NUNCA envia candidatura sozinho. Ele monta o material
(PDF + carta + dossie) e manda para voce decidir. A maioria das vagas de dados
no Brasil e via Gupy, que exige aplicacao manual de qualquer forma - e uma
candidatura ruim disparada em seu nome nao tem desfazer.
"""

import html
import os

import requests

LIMITE_TELEGRAM = 4096  # limite duro da API; mensagem maior falha em silencio


def _cortar(texto: str, tamanho: int) -> str:
    texto = str(texto or "").strip()
    if len(texto) <= tamanho:
        return texto
    return texto[:tamanho].rsplit(" ", 1)[0] + "..."


def _faixa(match_score: int, score_forte: int) -> str:
    if match_score >= score_forte:
        return "🔥 MATCH FORTE"
    return "✅ VALE APLICAR"


def _selo_categoria(categoria: str) -> str:
    """Para nao confundir, de relance, movimento de carreira com movimento de renda."""
    return "🛠️ SUPORTE" if categoria == "suporte" else "🧮 DADOS"


def _linha_salario(vaga: dict) -> str:
    """
    Salario so e conhecido quando a descricao informa - e 80% das vagas de suporte
    nao informam. Nesse caso o aviso e explicito, para você perguntar no processo
    em vez de supor.
    """
    if vaga.get("categoria") != "suporte":
        return ""

    minimo, maximo = vaga.get("salario_min"), vaga.get("salario_max")
    if maximo is None:
        return "<b>Salário:</b> ⚠️ não informado — perguntar no processo"
    if minimo is not None and minimo != maximo:
        return f"<b>Salário:</b> R$ {minimo:,.0f} – R$ {maximo:,.0f}".replace(",", ".")
    return f"<b>Salário:</b> R$ {maximo:,.0f}".replace(",", ".")


def enviar_notificacao_vaga(
    vaga: dict,
    analise: dict,
    caminho_pdf: str = None,
    caminho_dossie: str = None,
    caminho_carta: str = None,
    score_forte: int = 75,
) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[AVISO] TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes. Notificacao ignorada.")
        return False

    score = analise.get("match_score", 0)
    dossie = analise.get("dossie_entrevista", {})
    local = vaga.get("localizacao", "nao informado")
    modalidade = vaga.get("modalidade") or "nao informada"

    aviso = ""
    if analise.get("alerta_veracidade"):
        termos = ", ".join(analise["alerta_veracidade"])
        aviso = f"\n⚠️ <b>Guarda de veracidade:</b> a IA tentou citar {html.escape(termos)}. Revise a carta.\n"

    # A carta completa NAO entra na mensagem: vai como anexo .txt. Junto com o
    # resto ela estoura os 4096 caracteres e a notificacao inteira se perde.
    linha_salario = _linha_salario(vaga)
    if linha_salario:
        linha_salario = "\n" + linha_salario

    mensagem = f"""<b>{_selo_categoria(vaga.get('categoria', 'dados'))} · {_faixa(score, score_forte)} — {score}%</b>

<b>Cargo:</b> {html.escape(str(vaga.get('titulo', '')))}
<b>Empresa:</b> {html.escape(str(vaga.get('empresa', '')))}
<b>Local:</b> {html.escape(str(local))} ({html.escape(str(modalidade))})
<b>Fonte:</b> {html.escape(str(vaga.get('fonte', '')))}{linha_salario}
{aviso}
<b>Por que combina:</b>
<i>{html.escape(_cortar(analise.get('justificativa_match', ''), 600))}</i>

<b>Resumo adaptado:</b>
<i>{html.escape(_cortar(analise.get('resumo_adaptado', ''), 700))}</i>

<b>Pitch de 1 minuto:</b>
<i>{html.escape(_cortar(dossie.get('pitch_elevador', ''), 500))}</i>

📎 Curriculo, carta e dossie em anexo."""

    if len(mensagem) > LIMITE_TELEGRAM:
        mensagem = mensagem[:LIMITE_TELEGRAM - 20] + "\n[...]"

    link = vaga.get("link") or ""
    payload = {
        "chat_id": chat_id,
        "text": mensagem,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if link.startswith("http"):
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "Abrir vaga e candidatar-se", "url": link}]]
        }

    try:
        resposta = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=15
        )
        if resposta.status_code != 200:
            descricao = resposta.json().get("description", resposta.text)
            if "chat not found" in descricao.lower():
                print("[ERRO TELEGRAM] Chat nao encontrado: abra a conversa com o bot e envie /start.")
            else:
                print(f"[ERRO TELEGRAM] {descricao}")
            return False
        print("[TELEGRAM] Notificacao enviada.")
    except Exception as erro:
        print(f"[ERRO TELEGRAM] Falha de conexao: {erro}")
        return False

    for caminho in (caminho_pdf, caminho_carta, caminho_dossie):
        if caminho and os.path.exists(caminho):
            try:
                with open(caminho, "rb") as arquivo:
                    requests.post(
                        f"https://api.telegram.org/bot{token}/sendDocument",
                        data={"chat_id": chat_id},
                        files={"document": (os.path.basename(caminho), arquivo)},
                        timeout=30,
                    )
                print(f"[TELEGRAM] Anexo '{os.path.basename(caminho)}' enviado.")
            except Exception as erro:
                print(f"[ERRO TELEGRAM] Falha ao enviar '{caminho}': {erro}")

    return True


def enviar_resumo_rodada(texto: str) -> None:
    """Mensagem curta de fim de execucao (quantas vagas, quantas aprovadas)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": _cortar(texto, LIMITE_TELEGRAM - 10), "parse_mode": "HTML"},
            timeout=15,
        )
    except Exception as erro:
        print(f"[ERRO TELEGRAM] Falha ao enviar resumo: {erro}")
