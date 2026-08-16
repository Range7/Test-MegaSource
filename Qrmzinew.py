"""
MegaSource
================================

Protocol
--------
Seguindo o protocolo do MegaSource, este arquivo define:

 TITLE, VERSION, DESCRIPTION
 get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id : "tt0111161" (filme) | "tt0944947:1:1" (serie:temporada:episodio)

Retorna streams com behaviorHints.proxyHeaders.
Usa apenas a biblioteca padrao do Python (urllib + cookiejar) para
maxima compatibilidade com o ambiente MegaSource.

Para usar: suba este arquivo como scraper.py num repositorio do GitHub e
adicione a URL raw no addon MegaSource (pagina de configuracao).
"""

import http.cookiejar
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request

# =============================================================================
# METADADOS DO SCRAPER
# =============================================================================
TITLE = "Qrmzi.tv"
VERSION = "1.0.0"
DESCRIPTION = "Turkish Movies & Series (Arabic) - 1080p Only Filter"

# =============================================================================
# CONFIGURACOES E CONSTANTES
# =============================================================================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TMDB_API_KEY = "92c1507cc18d85290e7a0b96abb37316"
BASE_URL = "https://www.qrmzi.tv"
PLAYER_DOMAIN = "https://w.anaplayer.online"

# Contexto SSL para sites com certificados problematicos
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


# =============================================================================
# FUNCOES AUXILIARES HTTP
# =============================================================================
def _request(url, method="GET", data=None, headers=None, timeout=15):
    """
    Helper para requisicoes HTTP.
    Inclui tratamento de cookies, headers padrao e SSL.
    Retorna (status_code, body_text).
    """
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8,tr;q=0.7",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    if headers:
        request_headers.update(headers)

    body = None
    if method == "POST":
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            request_headers.setdefault(
                "Content-Type", "application/x-www-form-urlencoded"
            )
        elif data is not None:
            body = data

    req = urllib.request.Request(
        url, data=body, headers=request_headers, method=method
    )
    try:
        with _opener.open(req, context=_ssl_ctx, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception:
        # Erro de rede/timeout: retorna vazio para nao quebrar o addon
        return 0, ""


# =============================================================================
# TMDB - CONVERSAO IMDB -> TITULO
# =============================================================================
def _tmdb_find(imdb_id):
    """
    Consulta TMDB pelo IMDB ID para obter titulo original (geralmente turco)
    e titulo em ingles.
    """
    find_url = "https://api.themoviedb.org/3/find/" + urllib.parse.quote(imdb_id)
    query = urllib.parse.urlencode(
        {"api_key": TMDB_API_KEY, "external_source": "imdb_id"}
    )
    status, body = _request(find_url + "?" + query, timeout=10)
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None

    result = None
    if data.get("movie_results"):
        item = data["movie_results"][0]
        result = {
            "type": "movie",
            "tmdb_id": item["id"],
            "title": item.get("title", ""),
            "original_title": item.get("original_title", ""),
        }
    elif data.get("tv_results"):
        item = data["tv_results"][0]
        result = {
            "type": "tv",
            "tmdb_id": item["id"],
            "title": item.get("name", ""),
            "original_name": item.get("original_name", ""),
        }
    return result


# =============================================================================
# BUSCA NO SITE QRMZI.TV
# =============================================================================
def _search_qrmzi(query):
    """
    Pesquisa conteudo no qrmzi.tv usando o motor de busca WordPress.
    Retorna lista de dicts: [{"title": "...", "url": "...", "type": "movie|episode"}]
    """
    if not query or len(query.strip()) < 2:
        return []

    search_url = BASE_URL + "/?s=" + urllib.parse.quote(query.strip())
    status, body = _request(search_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return []

    results = []
    seen_urls = set()

    # WordPress geralmente retorna resultados em <article> tags
    # Extrai cada bloco de artigo separadamente para maior precisao
    articles = re.findall(r"<article[^>]*>.*?</article>", body, re.S | re.I)

    for article in articles:
        # Extrai o link principal do post
        link_match = re.search(
            r'<a[^>]+href=["\'](https?://www\.qrmzi\.tv/(?:movies|episode)/[^"\']+)["\']',
            article,
            re.S | re.I,
        )
        if not link_match:
            continue

        url = link_match.group(1)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Extrai o titulo (geralmente dentro de <h2> ou <h3>)
        title_match = re.search(
            r"<h[1-6][^>]*>(.*?)</h[1-6]>", article, re.S | re.I
        )
        title = ""
        if title_match:
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()

        item_type = "movie" if "/movies/" in url else "episode"
        results.append({"title": title, "url": url, "type": item_type})

    return results


# =============================================================================
# EXTRACAO DO IFRAME DO PLAYER
# =============================================================================
def _extract_player_iframe(page_url):
    """
    Acessa a pagina do filme/episodio no qrmzi.tv e extrai
    o iframe src apontando para w.anaplayer.online
    """
    status, body = _request(page_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return None

    # Procura iframe do AlbaPlayer
    iframe_match = re.search(
        r'<iframe[^>]+src=["\'](https?://w\.anaplayer\.online/[^"\']+)["\'][^>]*>',
        body,
        re.S | re.I,
    )
    if iframe_match:
        iframe_src = iframe_match.group(1)
        # Garante URL absoluta e limpa
        if iframe_src.startswith("//"):
            iframe_src = "https:" + iframe_src
        return iframe_src

    return None


# =============================================================================
# EXTRACAO E FILTRAGEM 1080p DO PLAYER
# =============================================================================
def _extract_1080p_sources(player_base_url):
    """
    Acessa as paginas do player AlbaPlayer para cada servidor disponivel,
    extrai os links de video e aplica فلترة صارمة لدقة 1080p فقط.

    الشرط الأساسي: يتم تجاهل أي سيرفر لا يحتوي على تأكيد واضح لدقة 1080p.
    """
    all_sources = []

    # Servidores conhecidos do AlbaPlayer neste site
    servers = [
        ("1", "CDNPlus"),
        ("2", "MP4Plus"),
    ]

    for serv_num, serv_name in servers:
        # Monta URL do servidor especifico
        if "?" in player_base_url:
            serv_url = player_base_url + "&serv=" + serv_num
        else:
            serv_url = player_base_url + "?serv=" + serv_num

        try:
            status, body = _request(
                serv_url, headers={"Referer": BASE_URL + "/"}
            )
            if status != 200 or not body:
                continue

            # ================================================================
            # فلترة دقة 1080p - الخطوة الأولى: فحص عنوان الصفحة
            # ================================================================
            # نستخرج عنوان الصفحة <title> للتحقق من وجود إشارة إلى 1080
            title_match = re.search(r"<title>(.*?)</title>", body, re.S | re.I)
            page_title = title_match.group(1) if title_match else ""

            # التحقق من وجود 1080p أو 1080 في العنوان أو في محتوى الصفحة
            has_1080_in_title = bool(
                re.search(r"1080[pi]?", page_title, re.I)
            )
            has_1080_in_body = bool(
                re.search(r"1080[pi]?", body, re.I)
            )

            # إذا لم يكن هناك أي تأكيد على 1080p، نتخطى هذا السيرفر تماماً
            if not has_1080_in_title and not has_1080_in_body:
                continue

            video_url = None
            quality_label = "1080p"  # افتراضي بناءً على التحقق السابق

            # ================================================================
            # استراتيجيات استخراج رابط الفيديو من صفحة AlbaPlayer
            # ================================================================

            # Estrategia 1: tags <source> ou <video> com src direto
            src_match = re.search(
                r'<(?:source|video)[^>]+src=["\']([^"\']+(?:\.mp4|\.m3u8)[^"\']*)["\']',
                body,
                re.S | re.I,
            )
            if src_match:
                video_url = src_match.group(1)

            # Estrategia 2: JSON de sources dentro de scripts
            if not video_url:
                # Procura por variaveis como: sources = [{file: "...", label: "1080p"}]
                json_match = re.search(
                    r'(?:var\s+)?(?:sources|playlist)\s*[:=]\s*(\[.*?\])',
                    body,
                    re.S,
                )
                if json_match:
                    try:
                        sources_list = json.loads(json_match.group(1))
                        for src in sources_list:
                            if isinstance(src, dict) and src.get("file"):
                                lbl = src.get("label", "")
                                # فلترة إضافية: إذا كان هناك label نتحقق منه
                                if re.search(r"1080[pi]?", lbl, re.I):
                                    video_url = src["file"]
                                    quality_label = lbl
                                    break
                                elif not lbl and not video_url:
                                    # بدون label، نأخذ الأولى فقط إذا كانت الصفحة تؤكد 1080p
                                    video_url = src["file"]
                    except (ValueError, TypeError):
                        pass

            # Estrategia 3: variavel JavaScript com URL .mp4/.m3u8
            if not video_url:
                var_match = re.search(
                    r'var\s+\w+\s*=\s*["\']([^"\']+(?:\.mp4|\.m3u8))["\']',
                    body,
                    re.I,
                )
                if var_match:
                    video_url = var_match.group(1)

            # Estrategia 4: qualquer URL direta .mp4 ou .m3u8 no HTML
            if not video_url:
                direct_match = re.search(
                    r'(https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*)',
                    body,
                    re.I,
                )
                if direct_match:
                    video_url = direct_match.group(1)

            # ================================================================
            # تطبيع الرابط النهائي والتحقق منه
            # ================================================================
            if video_url:
                # Converte URLs relativas e protocol-relative
                if video_url.startswith("//"):
                    video_url = "https:" + video_url
                elif video_url.startswith("/"):
                    video_url = PLAYER_DOMAIN + video_url

                # فلترة نهائية: نتأكد أن الرابط يبدأ بـ http
                if video_url.startswith("http"):
                    all_sources.append({
                        "url": video_url,
                        "quality": quality_label,
                        "server": serv_name,
                        "referer": serv_url,
                    })

        except Exception:
            # Em qualquer erro de parsing/extracao, pula para o proximo servidor
            continue

    return all_sources


# =============================================================================
# RESOLUCAO DE FILMES
# =============================================================================
def _resolve_movie(imdb_id):
    """
    Resolve um filme pelo IMDB ID.
    Fluxo: IMDB -> TMDB (titulo) -> Busca qrmzi.tv -> Pagina -> Iframe -> Video 1080p
    """
    try:
        tmdb_info = _tmdb_find(imdb_id)
        if not tmdb_info:
            return []

        # Tenta buscar pelo titulo original (geralmente turco) e pelo titulo em ingles
        queries = []
        if tmdb_info.get("original_title") and tmdb_info["original_title"] != tmdb_info.get("title"):
            queries.append(tmdb_info["original_title"])
        if tmdb_info.get("title"):
            queries.append(tmdb_info["title"])

        for query in queries:
            results = _search_qrmzi(query)
            for r in results:
                if r["type"] == "movie":
                    iframe = _extract_player_iframe(r["url"])
                    if iframe:
                        sources = _extract_1080p_sources(iframe)
                        if sources:
                            return sources
        return []
    except Exception:
        return []


# =============================================================================
# RESOLUCAO DE SERIES
# =============================================================================
def _resolve_series(imdb_id, season, episode):
    """
    Resolve um episodio de serie pelo IMDB ID + temporada + episodio.
    Fluxo: IMDB -> TMDB (titulo) -> Busca qrmzi.tv -> Filtra episodio -> Iframe -> Video 1080p
    """
    try:
        tmdb_info = _tmdb_find(imdb_id)
        if not tmdb_info:
            return []

        queries = []
        if tmdb_info.get("original_name") and tmdb_info["original_name"] != tmdb_info.get("title"):
            queries.append(tmdb_info["original_name"])
        if tmdb_info.get("title"):
            queries.append(tmdb_info["title"])

        for query in queries:
            results = _search_qrmzi(query)

            # Estrategia 1: procura diretamente um resultado de episodio com o numero correto
            for r in results:
                if r["type"] == "episode":
                    # Verifica se a URL contem o numero do episodio
                    # Padrao: /episode/...-الحلقة-{numero}/
                    ep_pattern = r"الحلقة[-\s]*" + re.escape(str(episode)) + r"(?:[-/\s]|$)"
                    if re.search(ep_pattern, r["url"], re.I):
                        iframe = _extract_player_iframe(r["url"])
                        if iframe:
                            sources = _extract_1080p_sources(iframe)
                            if sources:
                                return sources

            # Estrategia 2: busca mais especifica com "الحلقة {episode}"
            specific_query = f"{query} الحلقة {episode}"
            specific_results = _search_qrmzi(specific_query)
            for r in specific_results:
                if r["type"] == "episode":
                    iframe = _extract_player_iframe(r["url"])
                    if iframe:
                        sources = _extract_1080p_sources(iframe)
                        if sources:
                            return sources

        return []
    except Exception:
        return []


# =============================================================================
# FUNCAO PRINCIPAL DO PROTOCOLO MEGASOURCE
# =============================================================================
def get_streams(media_type, media_id, config=None):
    """
    Ponto de entrada principal do protocolo MegaSource.

    media_type: "movie" | "series"
    media_id:   "tt0111161" (filme) | "tt0944947:1:1" (serie:temporada:episodio)

    Retorna lista de streams no formato padrao MegaSource.
    """
    imdb_id = media_id
    season = None
    episode = None

    # Parse media_id para series: imdb_id:season:episode
    if ":" in media_id:
        parts = media_id.split(":", 2)
        if len(parts) == 3:
            imdb_id, season, episode = parts[0], parts[1], parts[2]

    sources = []

    # -------------------------------------------------------------------------
    # Resolve o conteudo baseado no tipo
    # -------------------------------------------------------------------------
    if media_type == "movie":
        sources = _resolve_movie(imdb_id)
    elif media_type == "series" and season and episode:
        sources = _resolve_series(imdb_id, int(season), int(episode))
    else:
        sources = []

    # -------------------------------------------------------------------------
    # Monta a resposta no formato MegaSource
    # -------------------------------------------------------------------------
    streams = []
    for src in sources:
        # ================================================================
        # فلترة نهائية صارمة: نتحقق مرة أخرى أن الجودة 1080p
        # ================================================================
        quality = src.get("quality", "")
        # Se o quality nao contem 1080, verifica na URL
        if not re.search(r"1080[pi]?", quality, re.I):
            if not re.search(r"1080[pi]?", src.get("url", ""), re.I):
                # Pula este stream se nao houver indicacao de 1080p
                continue

        streams.append(
            {
                "name": TITLE,
                "title": f"{src['server']} - {src['quality']}",
                "url": src["url"],
                "behaviorHints": {
                    "notMyMetadata": True,
                    "proxyHeaders": {
                        "request": {
                            "User-Agent": USER_AGENT,
                            "Origin": PLAYER_DOMAIN,
                            "Referer": src.get("referer", PLAYER_DOMAIN + "/"),
                        }
                    },
                },
            }
        )

    return streams
