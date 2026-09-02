"""Gera o arquivo .txt da carta de apresentacao, pronto para copiar e colar."""

import os
import re
from datetime import datetime


def gerar_arquivo_carta_apresentacao(
    vaga_info: dict,
    analise_ia: dict,
    perfil_base: dict,
    output_dir: str = "cartas_apresentacao",
) -> str:
    os.makedirs(output_dir, exist_ok=True)

    titulo = vaga_info.get("titulo", "Vaga")
    empresa = vaga_info.get("empresa", "Empresa")
    # Nomes truncados: caminho longo demais estoura o MAX_PATH do Windows.
    titulo_limpo = (re.sub(r"[^\w\-_]", "_", str(titulo)).strip("_")[:35]) or "Vaga"
    empresa_limpa = (re.sub(r"[^\w\-_]", "_", str(empresa)).strip("_")[:30]) or "Empresa"
    caminho = os.path.join(output_dir, f"Carta_{titulo_limpo}_{empresa_limpa}.txt")

    nome = perfil_base.get("nome", "Candidato")
    contato = perfil_base.get("contato", {})
    info_contato = " | ".join([p for p in [
        perfil_base.get("localizacao", ""),
        contato.get("phone", ""),
        contato.get("email", ""),
        contato.get("linkedin", ""),
        contato.get("github", ""),
    ] if p])

    conteudo = f"""{'=' * 80}
CARTA DE APRESENTACAO
Candidato: {nome}
Cargo: {titulo}
Empresa: {empresa}
Data: {datetime.now().strftime('%d/%m/%Y')}
{'=' * 80}

Prezado(a) Recrutador(a) / Equipe de Selecao da {empresa},

{analise_ia.get('cover_letter', '')}

Atenciosamente,
{nome}
{info_contato}
"""

    with open(caminho, "w", encoding="utf-8") as arquivo:
        arquivo.write(conteudo)

    print(f"[CARTA] Salva em '{caminho}'.")
    return caminho
