"""Dossie de preparacao para entrevista, em Markdown."""

import os
import re
from datetime import datetime


def gerar_dossie_vaga(vaga_info: dict, analise_ia: dict, output_dir: str = "dossies_vagas") -> str:
    os.makedirs(output_dir, exist_ok=True)

    titulo = vaga_info.get("titulo", "Vaga")
    empresa = vaga_info.get("empresa", "Empresa")
    titulo_limpo = (re.sub(r"[^\w\-_]", "_", str(titulo)).strip("_")[:35]) or "Vaga"
    empresa_limpa = (re.sub(r"[^\w\-_]", "_", str(empresa)).strip("_")[:30]) or "Empresa"
    caminho = os.path.join(output_dir, f"Dossie_{titulo_limpo}_{empresa_limpa}.md")

    dossie = analise_ia.get("dossie_entrevista", {})
    pontos_fortes = dossie.get("pontos_fortes", [])
    perguntas = dossie.get("perguntas_provaveis", [])
    perguntas_recrutador = dossie.get("perguntas_para_recrutador", [])
    pitch = dossie.get("pitch_elevador", "")

    conteudo = f"""# Dossie de Preparacao para Entrevista

**Cargo:** {titulo}
**Empresa:** {empresa}
**Match:** {analise_ia.get('match_score', 0)}%
**Modalidade:** {vaga_info.get('modalidade') or 'nao informada'} | **Local:** {vaga_info.get('localizacao', 'nao informado')}
**Fonte:** {vaga_info.get('fonte', '')}
**Link:** {vaga_info.get('link', '')}
**Analisado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}

---

## Justificativa do match
{analise_ia.get('justificativa_match', 'N/A')}

---

## Pitch de 1 minuto
> "{pitch}"

---

## Pontos fortes a destacar
"""
    for ponto in pontos_fortes:
        conteudo += f"- {ponto}\n"

    conteudo += "\n---\n\n## Perguntas provaveis e respostas sugeridas\n\n"
    for indice, item in enumerate(perguntas, 1):
        if isinstance(item, dict):
            pergunta = item.get("pergunta", "")
            resposta = item.get("resposta_sugerida", "")
        else:
            pergunta = str(item)
            resposta = "Responda ancorando em um projeto real do seu portfolio."
        conteudo += f"### {indice}. {pergunta}\n**Resposta sugerida:** {resposta}\n\n"

    conteudo += "---\n\n## Perguntas para fazer ao recrutador\n\n"
    for pergunta in perguntas_recrutador:
        conteudo += f"- {pergunta}\n"

    conteudo += f"\n---\n\n## Resumo otimizado para ATS\n{analise_ia.get('resumo_adaptado', '')}\n"
    conteudo += f"\n---\n\n## Carta de apresentacao gerada\n{analise_ia.get('cover_letter', '')}\n"

    alertas = analise_ia.get("alerta_veracidade")
    if alertas:
        conteudo += (
            "\n---\n\n## ATENCAO - guarda de veracidade\n"
            f"A IA tentou citar tecnologias que voce nao tem no perfil: {', '.join(alertas)}.\n"
            "O resumo do PDF foi substituido pelo texto factual do seu perfil. "
            "Revise a carta antes de enviar.\n"
        )

    with open(caminho, "w", encoding="utf-8") as arquivo:
        arquivo.write(conteudo)

    print(f"[DOSSIE] Salvo em '{caminho}'.")
    return caminho
