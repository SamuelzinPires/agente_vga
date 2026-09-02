"""
Coleta e filtragem de vagas de dados.

Ordem de valor das fontes para vaga JUNIOR de dados no Brasil:
  1. API publica da Gupy  - sem chave, sem custo, e onde esta a maioria das
                            vagas junior brasileiras. Traz descricao completa,
                            modalidade e cidade/estado estruturados.
  2. LinkedIn Guest       - vagas publicas, sem login. So titulo/empresa/local.
  3. Programathor         - categoria /jobs-big-data.
  4. GitHub Issues        - repositorios de vagas da comunidade.

Regra de custo: filtro por regex e de graca, chamada de IA e cota. Nada chega
ao LLM sem passar por todos os filtros daqui primeiro.
"""

import html
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
HEADERS_HTML = {"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"}

GUPY_API = "https://employability-portal.gupy.io/api/v1/jobs"

TERMOS_BUSCA = [
    "engenheiro de dados",
    "engenharia de dados",
    "analista de dados",
    "analista de bi",
    "analytics engineer",
]

REPOS_VAGAS_GITHUB = ["backend-br/vagas"]


# ─────────────────────────────────────────────────────────────────────────────
# Utilitarios
# ─────────────────────────────────────────────────────────────────────────────

def _limpar_texto(bruto: str) -> str:
    """Remove tags HTML e entidades (&nbsp;, &amp;) das descricoes."""
    if not bruto:
        return ""
    texto = BeautifulSoup(str(bruto), "html.parser").get_text(separator=" ")
    texto = html.unescape(texto).replace("\xa0", " ")
    return re.sub(r"\s+", " ", texto).strip()


def _normalizar_url(url: str) -> str:
    if not url:
        return ""
    return url.split("?")[0].rstrip("/").lower().strip()


# ─────────────────────────────────────────────────────────────────────────────
# Fontes
# ─────────────────────────────────────────────────────────────────────────────

def buscar_vagas_gupy(termo: str, limite: int = 40) -> list[dict]:
    """
    API publica do portal Gupy. Devolve descricao completa, modalidade
    (remote / hybrid / on-site) e cidade/estado ja estruturados - o que torna
    os filtros de localidade muito mais confiaveis que heuristica de texto.
    """
    vagas = []
    try:
        resposta = requests.get(
            GUPY_API,
            params={"jobName": termo, "limit": limite, "offset": 0},
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=20,
        )
        if resposta.status_code != 200:
            print(f"[GUPY] Status {resposta.status_code} para '{termo}'.")
            return vagas

        dados = resposta.json().get("data", [])
        for item in dados:
            cidade = item.get("city") or ""
            estado = item.get("state") or ""
            local = ", ".join([p for p in (cidade, estado) if p]) or "Nao informado"

            vagas.append({
                "titulo": item.get("name", ""),
                "empresa": item.get("careerPageName") or "Empresa nao informada",
                "link": item.get("jobUrl", ""),
                "descricao": _limpar_texto(item.get("description", "")),
                "localizacao": local,
                "modalidade": item.get("workplaceType") or "",
                "publicada_em": item.get("publishedDate", ""),
                "fonte": "Gupy",
            })

        print(f"[GUPY] {len(vagas)} vagas brutas para '{termo}'.")
    except Exception as erro:
        print(f"[GUPY ERRO] '{termo}': {erro}")

    return vagas


GEO_ID_BRASIL = "106057199"


def buscar_vagas_linkedin_guest(termo: str) -> list[dict]:
    """
    Vagas publicas do LinkedIn em modo convidado (sem login nem cookie).

    O `geoId` e obrigatorio: passando so `location=Brasil` o LinkedIn ignora o
    pais e devolve vagas dos Estados Unidos sem avisar.
    """
    vagas = []
    url = (
        "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={requests.utils.quote(termo)}&location=Brazil&geoId={GEO_ID_BRASIL}&start=0"
    )

    try:
        resposta = requests.get(url, headers=HEADERS_HTML, timeout=15)
        if resposta.status_code != 200:
            print(f"[LINKEDIN] Status {resposta.status_code} para '{termo}'.")
            return vagas

        sopa = BeautifulSoup(resposta.text, "html.parser")
        for card in sopa.find_all("li"):
            titulo_el = card.find("h3", class_="base-search-card__title")
            link_el = card.find("a", class_="base-card__full-link")
            if not (titulo_el and link_el):
                continue

            empresa_el = card.find("h4", class_="base-search-card__subtitle")
            local_el = card.find("span", class_="job-search-card__location")
            titulo = titulo_el.text.strip()
            empresa = empresa_el.text.strip() if empresa_el else "Empresa nao informada"
            local = local_el.text.strip() if local_el else "Nao informado"

            vagas.append({
                "titulo": titulo,
                "empresa": empresa,
                "link": link_el.get("href", "").split("?")[0],
                "descricao": (
                    f"Vaga publica do LinkedIn: {titulo} na {empresa} ({local}). "
                    "Descricao completa apenas no anuncio original."
                ),
                "localizacao": local,
                "modalidade": "",
                "fonte": "LinkedIn Guest",
            })

        print(f"[LINKEDIN] {len(vagas)} vagas brutas para '{termo}'.")
    except Exception as erro:
        print(f"[LINKEDIN ERRO] '{termo}': {erro}")

    return vagas


def buscar_vagas_programathor() -> list[dict]:
    """Categoria de dados do Programathor (a slug correta e 'jobs-big-data')."""
    vagas = []
    try:
        resposta = requests.get(
            "https://programathor.com.br/jobs-big-data", headers=HEADERS_HTML, timeout=15
        )
        if resposta.status_code != 200:
            return vagas

        sopa = BeautifulSoup(resposta.content, "html.parser")
        for bloco in sopa.find_all("div", class_=lambda c: c and "cell-list" in c):
            ancora = bloco.find("a", href=True)
            if not ancora:
                continue
            h3 = bloco.find("h3")
            spans = bloco.find_all("span")
            titulo = h3.get_text().strip() if h3 else "Vaga de Dados"
            empresa = spans[0].get_text().strip() if spans else "Programathor"

            # O portal lista vagas expiradas com o selo "Vencida" dentro do card.
            if re.match(r"^\s*(vencida|encerrada)\b", titulo, re.IGNORECASE):
                continue

            vagas.append({
                "titulo": titulo,
                "empresa": empresa,
                "link": "https://programathor.com.br" + ancora["href"],
                "descricao": f"{titulo} na empresa {empresa}. Vaga publica no Programathor.",
                "localizacao": " ".join(s.get_text().strip() for s in spans[:4]),
                "modalidade": "",
                "fonte": "Programathor",
            })

        print(f"[PROGRAMATHOR] {len(vagas)} vagas brutas.")
    except Exception as erro:
        print(f"[PROGRAMATHOR ERRO] {erro}")

    return vagas


def buscar_vagas_github_issues(repos: list[str] = None) -> list[dict]:
    """Issues abertas em repositorios de vagas da comunidade."""
    vagas = []
    for repo in (repos or REPOS_VAGAS_GITHUB):
        try:
            resposta = requests.get(
                f"https://api.github.com/repos/{repo}/issues",
                params={"state": "open", "per_page": 30},
                headers={"User-Agent": "agente-vagas-dados", "Accept": "application/vnd.github+json"},
                timeout=15,
            )
            if resposta.status_code != 200:
                continue

            for issue in resposta.json():
                if "pull_request" in issue:
                    continue
                vagas.append({
                    "titulo": issue.get("title", ""),
                    "empresa": f"Comunidade GitHub ({repo})",
                    "link": issue.get("html_url", ""),
                    "descricao": _limpar_texto(issue.get("body") or issue.get("title", "")),
                    "localizacao": "Ver anuncio",
                    "modalidade": "",
                    "fonte": f"GitHub ({repo})",
                })

            print(f"[GITHUB] issues lidas de {repo}.")
        except Exception as erro:
            print(f"[GITHUB ERRO] {repo}: {erro}")

    return vagas


# ─────────────────────────────────────────────────────────────────────────────
# Filtros (todos gratuitos - rodam antes de qualquer chamada de IA)
# ─────────────────────────────────────────────────────────────────────────────

CARGOS_ALVO_REGEX = [
    r"\bengenheir[oa]s?\s+de\s+dados\b", r"\bengenharia\s+de\s+dados\b", r"\bdata\s+engineer\b",
    r"\banalista\s+de\s+dados\b", r"\bdata\s+analyst\b", r"\bdata\s+analytics\b",
    r"\banalista\s+de\s+bi\b", r"\bbusiness\s+intelligence\b", r"\bbi\s+analyst\b",
    r"\banalytics\s+engineer\b", r"\bengenheir[oa]\s+de\s+analytics\b",
    r"\banalista\s+de\s+etl\b", r"\bdata\s*ops\b", r"\bengenheir[oa]\s+de\s+bi\b",
]

# Perfis vizinhos que NAO sao o alvo hoje (exigem estatistica/modelagem preditiva)
CARGOS_EXCLUIDOS_REGEX = [
    r"\bcientista\s+de\s+dados\b", r"\bdata\s+scientist\b", r"\bmachine\s+learning\b",
    r"\bestat[ií]stic[oa]\b", r"\bcientista\b",
    r"\bhelpdesk\b", r"\bservice\s*desk\b", r"\bsuporte\s*n[12]\b", r"\batendimento\b",
    r"\bprofessor[a]?\b", r"\bdocente\b", r"\binstrutor[a]?\b", r"\btutor[a]?\b",
    r"\bcomercial\b", r"\bvendas\b", r"\bvendedor[a]?\b", r"\bsdr\b", r"\bbdr\b",
    r"\bscrum\s*master\b", r"\bagile\s*coach\b", r"\bproduct\s*owner\b", r"\bproduct\s*manager\b",
    r"\bdesigner\b", r"\bux\b", r"\bui\b",
]

SENIORIDADE_ALTA_REGEX = [
    r"\bs[eê]nior\b", r"\bsr\.?\b", r"\bsnr\b", r"\bespecialista\b", r"\bspecialist\b",
    r"\blead\b", r"\bl[ií]der\b", r"\bcoordenador[a]?\b", r"\bgerente\b", r"\bmanager\b",
    r"\bhead\b", r"\bdiretor[a]?\b", r"\barquitet[oa]\b", r"\barchitect\b", r"\bprincipal\b",
    # Nivel em algarismo romano: "Analytics Engineer III" e senior na pratica.
    # II fica de fora de proposito - costuma ser pleno e ainda vale a tentativa.
    r"\biii\b", r"\biv\b",
]

# Duas versoes de proposito: em campo estruturado (cidade/estado) a sigla "GO"
# sozinha e confiavel; no meio da descricao ela colide com o verbo ingles "go"
# e marcaria vaga de Sao Paulo como se fosse de Goias.
MARCAS_GOIAS_REGEX = r"\b(goi[âa]nia|goi[áa]s|go|aparecida\s+de\s+goi[âa]nia|an[áa]polis)\b"
MARCAS_GOIAS_TEXTO_REGEX = r"\b(goi[âa]nia|goi[áa]s|aparecida\s+de\s+goi[âa]nia|an[áa]polis)\b"

OUTRAS_REGIOES_REGEX = (
    r"\b(s[aã]o\s*paulo|\bsp\b|barueri|alphaville|campinas|osasco|santo\s*andr[eé]|"
    r"belo\s*horizonte|\bmg\b|curitiba|\bpr\b|porto\s*alegre|\brs\b|florian[oó]polis|\bsc\b|"
    r"bras[íi]lia|\bdf\b|rio\s*de\s*janeiro|\brj\b|salvador|\bba\b|recife|\bpe\b|fortaleza|\bce\b|"
    r"manaus|\bam\b|campo\s*grande|\bms\b|cuiab[áa]|\bmt\b)\b"
)

# Em portugues E em ingles: o LinkedIn devolve o local ja traduzido
# ("Nova York, Estados Unidos"), entao a lista so em ingles nao pega nada.
PAISES_ESTRANGEIROS_REGEX = [
    r"\bunited\s+states\b", r"\bestados\s+unidos\b", r"\beua\b", r"\busa\b",
    r"\bcanada\b", r"\bcanad[áa]\b", r"\bgermany\b", r"\balemanha\b",
    r"\bunited\s+kingdom\b", r"\breino\s+unido\b", r"\bportugal\b", r"\blisboa\b",
    r"\bespanha\b", r"\bspain\b", r"\bnetherlands\b", r"\bpa[íi]ses\s+baixos\b",
    r"\bmexico\b", r"\bm[ée]xico\b", r"\bargentina\b", r"\bcol[ôo]mbia\b",
    r"\bchile\b", r"\b[íi]ndia\b", r"\bpol[ôo]nia\b", r"\birlanda\b",
]

PAYWALL_REGEX = [
    r"assine\b.*?\bpara\s+(se\s+)?candidatar\b", r"vaga\s+exclusiva\s+para\s+assinantes\b",
    r"membros?\s+premium\b", r"plano\s+vip\b", r"seja\s+vip\b", r"torne-se\s+vip\b",
    r"\bvaga\s+vip\b", r"\b[áa]rea\s+vip\b", r"assinatura\s+paga\b",
    r"trabalhaes\.com\.br", r"bebee\.com",
]

# Vagas afirmativas restritas a publicos aos quais voce nao pertence.
# NAO usar as flags `isPWD`/`disabilities` da Gupy aqui: elas sinalizam vaga
# ABERTA a PCD, nao exclusiva - filtrar por elas descartaria vagas validas.
GRUPO_EXCLUSIVO_REGEX = [
    r"\belas\s+in\s+tech\b", r"\bwomen\s+in\s+tech\b",
    r"\bexclusiv[ao]\b.*?\b(mulheres|pcd|pessoas\s+negras)\b",
    r"\bafirmativa\b.*?\b(mulheres|pcd|pessoas\s+negras|pretas|ind[íi]genas|lgbt)\b",
    r"\b(vaga|programa)\s+afirmativ[ao]\b",
]


def _texto_completo(vaga: dict) -> str:
    partes = [vaga.get(c, "") for c in ("titulo", "empresa", "descricao", "localizacao", "link")]
    return " ".join(str(p) for p in partes).lower()


def e_cargo_de_dados(vaga: dict) -> bool:
    titulo = str(vaga.get("titulo", "")).lower()
    if any(re.search(p, titulo) for p in SENIORIDADE_ALTA_REGEX):
        return False
    if any(re.search(p, titulo) for p in CARGOS_EXCLUIDOS_REGEX):
        return False
    return any(re.search(p, titulo) for p in CARGOS_ALVO_REGEX)


def e_remota_ou_goiania(vaga: dict) -> bool:
    """
    Aprova: 100% remoto no Brasil, ou presencial/hibrido em Goiania/GO.
    Usa a modalidade estruturada quando a fonte fornece (Gupy); senao cai
    para heuristica de texto.
    """
    modalidade = str(vaga.get("modalidade", "")).lower()
    local = f"{vaga.get('localizacao', '')} {vaga.get('titulo', '')}".lower()

    if modalidade == "remote":
        return True
    if modalidade in ("hybrid", "on-site", "onsite"):
        return bool(re.search(MARCAS_GOIAS_REGEX, local))

    texto = _texto_completo(vaga)
    tem_goias = bool(re.search(MARCAS_GOIAS_TEXTO_REGEX, texto))
    tem_outra_regiao = bool(re.search(OUTRAS_REGIOES_REGEX, texto))
    e_remoto = bool(re.search(
        r"\b(100%\s*remoto|totalmente\s*remoto|remoto|remota|remote|home\s*office|teletrabalho|anywhere)\b",
        texto,
    ))
    e_presencial = bool(re.search(r"\b(presencial|on-?site|h[ií]brid[oa]|hybrid)\b", texto))

    if tem_goias:
        return True
    if e_presencial and not tem_goias:
        return False
    if e_remoto and not tem_outra_regiao:
        return True
    return not tem_outra_regiao


def e_vaga_no_brasil(vaga: dict) -> bool:
    texto = _texto_completo(vaga)
    if re.search(r"\b(brasil|brazil|latam)\b", texto):
        return True
    return not any(re.search(p, texto) for p in PAISES_ESTRANGEIROS_REGEX)


def e_candidatura_gratuita(vaga: dict) -> bool:
    texto = _texto_completo(vaga)
    return not any(re.search(p, texto) for p in PAYWALL_REGEX)


def e_vaga_publico_geral(vaga: dict) -> bool:
    texto = f"{vaga.get('titulo', '')} {vaga.get('descricao', '')}".lower()
    if re.search(r"\bexclusiv[ao]\b.*?\bpcd\b", texto) or re.search(r"\bvaga\s+pcd\b", texto):
        return False
    return not any(re.search(p, texto) for p in GRUPO_EXCLUSIVO_REGEX)


FILTROS = [
    ("cargo fora do alvo de dados", e_cargo_de_dados),
    ("fora de remoto/Goiania", e_remota_ou_goiania),
    ("fora do Brasil", e_vaga_no_brasil),
    ("candidatura paga", e_candidatura_gratuita),
    ("vaga afirmativa restrita", e_vaga_publico_geral),
]


def _deduplicar(vagas: list[dict]) -> list[dict]:
    """Uma mesma vaga costuma aparecer na Gupy e no LinkedIn ao mesmo tempo."""
    vistos = set()
    unicas = []
    for vaga in vagas:
        chave_link = _normalizar_url(vaga.get("link", ""))
        chave_texto = (
            re.sub(r"\s+", " ", str(vaga.get("titulo", "")).lower().strip()),
            re.sub(r"\s+", " ", str(vaga.get("empresa", "")).lower().strip()),
        )
        if chave_link and chave_link in vistos:
            continue
        if chave_texto in vistos:
            continue
        if chave_link:
            vistos.add(chave_link)
        vistos.add(chave_texto)
        unicas.append(vaga)
    return unicas


def coletar_vagas_todas_fontes(termos: list[str] = None) -> list[dict]:
    """Varre todas as fontes, deduplica e aplica os filtros gratuitos."""
    termos = termos or TERMOS_BUSCA
    brutas = []

    print("\n[COLETA] Gupy (fonte principal)...")
    for termo in termos:
        brutas.extend(buscar_vagas_gupy(termo))
        time.sleep(1)

    print("\n[COLETA] LinkedIn Guest...")
    for termo in termos[:3]:
        brutas.extend(buscar_vagas_linkedin_guest(termo))
        time.sleep(1)

    print("\n[COLETA] Programathor...")
    brutas.extend(buscar_vagas_programathor())

    print("\n[COLETA] GitHub...")
    brutas.extend(buscar_vagas_github_issues())

    unicas = _deduplicar(brutas)
    print(f"\n[COLETA] {len(brutas)} vagas brutas -> {len(unicas)} unicas apos dedupe.")

    aprovadas = []
    reprovadas = {motivo: 0 for motivo, _ in FILTROS}
    for vaga in unicas:
        for motivo, filtro in FILTROS:
            if not filtro(vaga):
                reprovadas[motivo] += 1
                break
        else:
            aprovadas.append(vaga)

    print("[FILTROS] Descartadas por motivo:")
    for motivo, total in reprovadas.items():
        print(f"          - {motivo}: {total}")
    print(f"[FILTROS] {len(aprovadas)} vagas aprovadas para analise da IA.\n")

    return aprovadas
