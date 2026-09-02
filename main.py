"""
Agente de Vagas de Dados - orquestrador.

Fluxo: coleta -> filtros gratuitos -> dedupe no banco -> analise pela IA ->
gera material -> notifica no Telegram. Nunca aplica sozinho.

Uso:
    python main.py                 # rodada completa
    python main.py --dry-run       # so coleta e filtra, sem gastar cota de IA
    python main.py --limite 3      # analisa no maximo 3 vagas (teste)
    python main.py --sem-telegram  # nao notifica (util em teste local)
"""

import argparse
import json
import os
import re
import sys
import time

from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from modules.cover_letter import gerar_arquivo_carta_apresentacao
from modules.database import inicializar_supabase, salvar_vaga_processada, vaga_ja_processada
from modules.dossier import gerar_dossie_vaga
from modules.llm import LLMIndisponivelError
from modules.notifier import enviar_notificacao_vaga, enviar_resumo_rodada
from modules.pdf_generator import gerar_pdf_curriculo
from modules.scraper import coletar_vagas_todas_fontes
from modules.tailor import analisar_vaga

load_dotenv()

ARQUIVO_PERFIL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfil.json")
PASTA_CURRICULOS = "curriculos_gerados"

SCORE_MINIMO = int(os.getenv("SCORE_MINIMO", "60"))
SCORE_FORTE = int(os.getenv("SCORE_FORTE", "75"))
MAX_VAGAS_POR_RODADA = int(os.getenv("MAX_VAGAS_POR_RODADA", "30"))
PAUSA_ENTRE_VAGAS = int(os.getenv("PAUSA_ENTRE_VAGAS", "4"))


def carregar_perfil() -> dict:
    """
    Carrega o perfil de `perfil.json` (uso local) ou da variavel PERFIL_JSON
    (uso no GitHub Actions). O arquivo real nao vai para o repositorio: ele tem
    telefone e e-mail, e repo publico e varrido por bot de spam.
    """
    if os.path.exists(ARQUIVO_PERFIL):
        with open(ARQUIVO_PERFIL, "r", encoding="utf-8") as arquivo:
            return json.load(arquivo)

    perfil_env = os.getenv("PERFIL_JSON", "").strip()
    if perfil_env:
        try:
            return json.loads(perfil_env)
        except json.JSONDecodeError as erro:
            raise ValueError(f"PERFIL_JSON nao e um JSON valido: {erro}") from erro

    raise FileNotFoundError(
        "Perfil nao encontrado. Crie perfil.json a partir de perfil.example.json "
        "(local) ou cadastre o secret PERFIL_JSON (GitHub Actions)."
    )


def _nome_arquivo_seguro(texto: str, limite: int = 30) -> str:
    """Windows estoura o MAX_PATH com nome de empresa longo."""
    return (re.sub(r"[^\w\-_]", "_", str(texto)).strip("_")[:limite]) or "Empresa"


def processar_vaga(vaga: dict, perfil: dict, supabase, notificar: bool) -> str:
    """Analisa uma vaga e devolve o status final: 'notificada' ou 'descartada'."""
    analise, provider = analisar_vaga(vaga, perfil)
    score = analise.get("match_score", 0)
    print(f"[SCORE] {score}% — {vaga.get('titulo')} ({vaga.get('empresa')})")

    if score < SCORE_MINIMO:
        print(f"[DESCARTE] Abaixo do minimo de {SCORE_MINIMO}%.")
        salvar_vaga_processada(supabase, vaga, analise, status="descartada", provider_ia=provider)
        return "descartada"

    os.makedirs(PASTA_CURRICULOS, exist_ok=True)
    # O nome do candidato fica fora do nome do arquivo: ele aparece no log, e
    # log de Actions em repositorio publico e visivel para qualquer pessoa.
    nome_pdf = f"CV_{_nome_arquivo_seguro(vaga.get('empresa', 'Empresa'))}.pdf"
    caminho_pdf = os.path.join(PASTA_CURRICULOS, nome_pdf)

    gerar_pdf_curriculo(perfil, analise, output_filename=caminho_pdf)
    caminho_dossie = gerar_dossie_vaga(vaga, analise)
    caminho_carta = gerar_arquivo_carta_apresentacao(vaga, analise, perfil)

    if notificar:
        enviar_notificacao_vaga(
            vaga, analise, caminho_pdf, caminho_dossie, caminho_carta, score_forte=SCORE_FORTE
        )
    else:
        print(f"[LOCAL] Material gerado sem notificar: {caminho_pdf}")

    salvar_vaga_processada(supabase, vaga, analise, status="notificada", provider_ia=provider)

    # Anexos ja seguiram para o Telegram; nao deixa lixo no runner nem no repo.
    if notificar:
        for caminho in (caminho_pdf, caminho_dossie, caminho_carta):
            try:
                os.remove(caminho)
            except OSError:
                pass

    return "notificada"


def main() -> None:
    parser = argparse.ArgumentParser(description="Agente de vagas de dados")
    parser.add_argument("--dry-run", action="store_true", help="coleta e filtra sem chamar a IA")
    parser.add_argument("--limite", type=int, default=MAX_VAGAS_POR_RODADA, help="teto de vagas analisadas")
    parser.add_argument("--sem-telegram", action="store_true", help="nao envia notificacao")
    args = parser.parse_args()

    print("=" * 70)
    print("AGENTE DE VAGAS DE DADOS — iniciando rodada")
    print("=" * 70)

    perfil = carregar_perfil()
    # Sem nome, telefone ou e-mail no log: em repositorio publico, o log da
    # execucao do GitHub Actions e publico junto.
    print(f"[PERFIL] carregado — alvo: {', '.join(perfil.get('cargos_alvo', []))}")

    vagas = coletar_vagas_todas_fontes()
    if not vagas:
        print("[FIM] Nenhuma vaga passou pelos filtros nesta rodada.")
        return

    if args.dry_run:
        print(f"\n[DRY-RUN] {len(vagas)} vagas aprovadas pelos filtros (IA nao foi chamada):\n")
        for indice, vaga in enumerate(vagas, 1):
            print(f"{indice:3d}. {vaga.get('titulo')}")
            print(f"     {vaga.get('empresa')} | {vaga.get('localizacao')} "
                  f"| {vaga.get('modalidade') or 'n/d'} | {vaga.get('fonte')}")
        return

    supabase = inicializar_supabase()

    novas = [v for v in vagas if not vaga_ja_processada(supabase, v)]
    print(f"[DEDUPE] {len(vagas) - len(novas)} ja processadas antes. {len(novas)} novas.")

    if not novas:
        print("[FIM] Nada novo nesta rodada.")
        return

    fila = novas[:args.limite]
    if len(novas) > len(fila):
        print(f"[COTA] Analisando apenas {len(fila)} de {len(novas)} para proteger a cota de IA.")

    contadores = {"notificada": 0, "descartada": 0, "erro": 0}

    for indice, vaga in enumerate(fila, 1):
        print(f"\n--- [{indice}/{len(fila)}] {vaga.get('titulo')} ---")
        try:
            status = processar_vaga(vaga, perfil, supabase, notificar=not args.sem_telegram)
            contadores[status] += 1
        except LLMIndisponivelError as erro:
            # Sem IA disponivel nao adianta seguir: encerra a rodada limpo.
            print(f"[PARADA] {erro}")
            break
        except Exception as erro:
            # Uma vaga quebrada nao pode derrubar as outras da fila.
            contadores["erro"] += 1
            print(f"[ERRO] Falha ao processar '{vaga.get('titulo')}': {type(erro).__name__}: {erro}")

        time.sleep(PAUSA_ENTRE_VAGAS)

    resumo = (
        f"<b>Rodada concluida</b>\n"
        f"Analisadas: {sum(contadores.values())}\n"
        f"Notificadas (>= {SCORE_MINIMO}%): {contadores['notificada']}\n"
        f"Descartadas: {contadores['descartada']}\n"
        f"Erros: {contadores['erro']}"
    )
    print("\n" + "=" * 70)
    print(re.sub(r"<[^>]+>", "", resumo))
    print("=" * 70)

    if not args.sem_telegram and contadores["notificada"] == 0:
        enviar_resumo_rodada(resumo)


if __name__ == "__main__":
    main()
