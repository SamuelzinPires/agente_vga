"""
Gerador de curriculo em PDF otimizado para ATS.

Coluna unica, sem tabela, sem caixa de texto, sem grafico: e feio de proposito.
Robo de recrutamento (Gupy, Greenhouse, Lever) le layout de duas colunas de
forma imprevisivel e costuma embaralhar as secoes. Para envio humano, use um
modelo mais bonito; para ATS, este.
"""

import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

# Curriculo de junior tem que caber em UMA pagina: recrutador le a primeira e
# raramente vira. Por isso o corte e no gerador, nao no perfil.
MAX_PROJETOS = 3
MAX_TOPICOS_POR_PROJETO = 2
MAX_EXPERIENCIAS = 4
MAX_DETALHES_POR_EXPERIENCIA = 2


def _ordenar_projetos(projetos: list, prioridade: list) -> list:
    """
    Reordena os projetos conforme a prioridade que a IA definiu para a vaga.
    Projeto fora da lista da IA vai para o fim, na ordem original do perfil.
    """
    if not prioridade:
        return projetos

    posicao = {titulo: indice for indice, titulo in enumerate(prioridade)}
    return sorted(
        projetos,
        key=lambda p: posicao.get(str(p.get("titulo", "")) if isinstance(p, dict) else str(p), len(posicao)),
    )


def gerar_pdf_curriculo(
    perfil_base: dict,
    analise_ia: dict,
    output_filename: str = "curriculo_otimizado.pdf",
    design_config: dict = None,
    categoria: str = "dados",
) -> str:
    design_config = design_config or {}
    cor_primaria_hex = design_config.get("cor_primaria", "#000000")

    pasta_destino = os.path.dirname(output_filename)
    if pasta_destino:
        os.makedirs(pasta_destino, exist_ok=True)

    doc = SimpleDocTemplate(
        output_filename,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=28,
        bottomMargin=28,
    )
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=14, leading=16, alignment=TA_CENTER,
        textColor=colors.HexColor("#000000"), spaceAfter=3,
    )
    contact_style = ParagraphStyle(
        "ContactStyle", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9, leading=11, alignment=TA_CENTER,
        textColor=colors.HexColor("#333333"), spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "SectionStyle", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=10.5, leading=12, textColor=colors.HexColor(cor_primaria_hex),
        spaceBefore=7, spaceAfter=2, keepWithNext=True,
    )
    body_style = ParagraphStyle(
        "BodyStyle", parent=styles["Normal"], fontName="Helvetica",
        fontSize=9, leading=11, alignment=TA_JUSTIFY,
        textColor=colors.HexColor("#1A1A1A"), spaceAfter=2,
    )
    bullet_style = ParagraphStyle(
        "BulletStyle", parent=body_style, leftIndent=12,
        firstLineIndent=-8, spaceAfter=2,
    )

    # 1. Cabecalho
    nome = perfil_base.get("nome", "CANDIDATO").upper()
    if perfil_base.get("contato_str"):
        info_contato = perfil_base["contato_str"]
    else:
        c = perfil_base.get("contato", {})
        partes = [
            perfil_base.get("localizacao"),
            c.get("phone"),
            c.get("email"),
            c.get("linkedin"),
            c.get("github"),  # portfolio de dados mora aqui: nao pode faltar
        ]
        info_contato = " | ".join([p for p in partes if p])

    story.append(Paragraph(f"<b>{nome}</b>", title_style))
    story.append(Paragraph(info_contato, contact_style))

    # 2. Perfil profissional (versao adaptada pela IA, ja checada pela guarda)
    story.append(Paragraph("PERFIL PROFISSIONAL", section_style))
    resumo = analise_ia.get("resumo_adaptado") or perfil_base.get("resumo_profissional", "")
    story.append(Paragraph(resumo, body_style))
    story.append(Spacer(1, 3))

    # 3 e 4. Projetos e experiencia, em ordem que depende da categoria da vaga.
    #
    # Vaga de dados: projeto primeiro - em transicao de carreira e o projeto que
    # comprova a stack pedida. Vaga de suporte: experiencia primeiro - ali o que
    # importa e ja ter atendido usuario, e o projeto passa a ser diferencial.
    bloco_projetos = []
    projetos = _ordenar_projetos(
        perfil_base.get("projetos_tecnicos", []),
        analise_ia.get("projetos_prioritarios", []),
    )[:MAX_PROJETOS]

    if projetos:
        bloco_projetos.append(Paragraph("PROJETOS TECNICOS", section_style))
        for projeto in projetos:
            if isinstance(projeto, dict):
                bloco_projetos.append(Paragraph(f"<b>{projeto.get('titulo', 'Projeto')}</b>", body_style))
                for topico in projeto.get("topicos", [])[:MAX_TOPICOS_POR_PROJETO]:
                    bloco_projetos.append(Paragraph(f"• {topico}", bullet_style))
            else:
                bloco_projetos.append(Paragraph(f"• {projeto}", bullet_style))
            bloco_projetos.append(Spacer(1, 3))

    bloco_experiencia = []
    experiencias = perfil_base.get("experiencias", [])[:MAX_EXPERIENCIAS]
    if experiencias:
        bloco_experiencia.append(Paragraph("EXPERIENCIA PROFISSIONAL", section_style))
        for exp in experiencias:
            if isinstance(exp, dict):
                cabecalho = f"<b>{exp.get('empresa', '')}</b> - {exp.get('cargo', '')} ({exp.get('periodo', '')})"
                bloco_experiencia.append(Paragraph(cabecalho, body_style))
                for detalhe in exp.get("detalhes", [])[:MAX_DETALHES_POR_EXPERIENCIA]:
                    bloco_experiencia.append(Paragraph(f"• {detalhe}", bullet_style))
            elif isinstance(exp, str):
                bloco_experiencia.append(Paragraph(exp, body_style))
            bloco_experiencia.append(Spacer(1, 3))

    if categoria == "suporte":
        story.extend(bloco_experiencia)
        story.extend(bloco_projetos)
    else:
        story.extend(bloco_projetos)
        story.extend(bloco_experiencia)

    # 5. Habilidades tecnicas
    habilidades = perfil_base.get("habilidades_tecnicas", {})
    destaques = analise_ia.get("habilidades_destacadas", [])
    if habilidades or destaques:
        story.append(Paragraph("HABILIDADES TECNICAS", section_style))
        if destaques:
            story.append(Paragraph(
                f"<b>Aderencia a esta vaga:</b> {', '.join(str(d) for d in destaques)}",
                body_style,
            ))
        if isinstance(habilidades, dict):
            for categoria, skills in habilidades.items():
                texto = ", ".join(skills) if isinstance(skills, list) else str(skills)
                story.append(Paragraph(f"• <b>{categoria}:</b> {texto}", body_style))
        elif isinstance(habilidades, list):
            story.append(Paragraph(", ".join(habilidades), body_style))
        story.append(Spacer(1, 3))

    # 6. Formacao
    formacao = perfil_base.get("formacao", [])
    if formacao:
        story.append(Paragraph("FORMACAO ACADEMICA", section_style))
        for item in formacao:
            if isinstance(item, dict):
                texto = f"• <b>{item.get('curso', '')}</b> - {item.get('instituicao', '')} ({item.get('conclusao', '')})"
            else:
                texto = f"• {item}"
            story.append(Paragraph(texto, body_style))
        story.append(Spacer(1, 3))

    # 7. Certificacoes e cursos
    certificacoes = perfil_base.get("certificacoes", [])
    if certificacoes:
        story.append(Paragraph("CERTIFICACOES E CURSOS", section_style))
        # Em paragrafo unico, nao em bullets: economiza 3 linhas na pagina.
        texto_certs = " • ".join(certificacoes) if isinstance(certificacoes, list) else str(certificacoes)
        story.append(Paragraph(texto_certs, body_style))
        story.append(Spacer(1, 3))

    # 8. Idiomas e competencias
    idiomas = perfil_base.get("idiomas_str", "")
    soft_skills = perfil_base.get("soft_skills", [])
    if idiomas or soft_skills:
        story.append(Paragraph("IDIOMAS E COMPETENCIAS", section_style))
        if idiomas:
            story.append(Paragraph(f"<b>Idiomas:</b> {idiomas}", body_style))
        if soft_skills:
            texto = ", ".join(soft_skills) if isinstance(soft_skills, list) else str(soft_skills)
            story.append(Paragraph(f"<b>Competencias:</b> {texto}", body_style))

    doc.build(story)
    return output_filename
