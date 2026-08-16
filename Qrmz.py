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
Usa apenas a biblioteca padrao do Python (urllib + cookiejar).
"""

import http.cookiejar
import json
import re
import ssl
import string
import urllib.error
import urllib.parse
import urllib.request

# =============================================================================
# METADADOS DO SCRAPER
# =============================================================================
TITLE = "Qrmzi.tv"
VERSION = "5.0.0"
DESCRIPTION = "Turkish Movies & Series (Arabic) - 1080p Only"

# =============================================================================
# CONSTANTES
# =============================================================================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TMDB_API_KEY = "92c1507cc18d85290e7a0b96abb37316"
BASE_URL = "https://www.qrmzi.tv"

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


# =============================================================================
# HTTP HELPER
# =============================================================================
def _request(url, method="GET", data=None, headers=None, timeout=15):
    """Requisicao HTTP com cookies, SSL e tratamento de erros."""
    h = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8,tr;q=0.7",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    if headers:
        h.update(headers)

    body = None
    if method == "POST":
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif data is not None:
            body = data

    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with _opener.open(req, context=_ssl_ctx, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, raw.decode("utf-8")
            except UnicodeDecodeError:
                return r.status, raw.decode("latin-1", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", errors="replace")
        except:
            return e.code, ""
    except Exception:
        return 0, ""


# =============================================================================
# TMDB - TITULO E TRADUCAO ARABE
# =============================================================================
def _tmdb_find(imdb_id):
    """Converte IMDB ID para informacoes TMDB."""
    url = "https://api.themoviedb.org/3/find/" + urllib.parse.quote(imdb_id)
    q = urllib.parse.urlencode({"api_key": TMDB_API_KEY, "external_source": "imdb_id"})
    status, body = _request(url + "?" + q, timeout=10)
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None

    if data.get("movie_results"):
        item = data["movie_results"][0]
        return {
            "type": "movie",
            "tmdb_id": item["id"],
            "title": item.get("title", ""),
            "original_title": item.get("original_title", ""),
        }
    if data.get("tv_results"):
        item = data["tv_results"][0]
        return {
            "type": "tv",
            "tmdb_id": item["id"],
            "title": item.get("name", ""),
            "original_name": item.get("original_name", ""),
        }
    return None


def _tmdb_arabic_title(tmdb_id, media_type):
    """Busca traducao arabe do TMDB."""
    tmdb_type = "movie" if media_type == "movie" else "tv"
    url = f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_id}/translations"
    q = urllib.parse.urlencode({"api_key": TMDB_API_KEY})
    status, body = _request(url + "?" + q, timeout=10)
    if status != 200:
        return None
    try:
        data = json.loads(body)
        for trans in data.get("translations", []):
            if trans.get("iso_639_1") == "ar":
                d = trans.get("data", {})
                return d.get("title") or d.get("name")
    except (ValueError, TypeError):
        pass
    return None


# =============================================================================
# LISTAGEM COMPLETA PARA FUZZY MATCHING
# =============================================================================
def _normalize(text):
    """Normaliza texto para comparacao."""
    return text.lower().replace("مسلسل", "").replace("فيلم", "").replace("-", " ").replace("  ", " ").strip()


def _word_overlap_score(query, title):
    """Calcula pontuacao de sobreposicao de palavras."""
    q_words = set(w for w in _normalize(query).split() if len(w) >= 2)
    t_words = set(w for w in _normalize(title).split() if len(w) >= 2)
    if not q_words or not t_words:
        return 0.0
    intersection = q_words & t_words
    return len(intersection) / len(q_words)


def _load_series_list():
    """Carrega lista de todas as series do qrmzi.tv."""
    status, body = _request(f"{BASE_URL}/all-turkish-series/")
    if status != 200:
        return []
    results = []
    matches = re.findall(r'<a[^>]*href="([^"]+)"[^>]*title="([^"]+)"[^>]*>', body)
    for href, title in matches:
        if "/series/" in href:
            results.append({"url": href, "title": title})
    return results


def _load_movies_list():
    """Carrega lista de todos os filmes do qrmzi.tv."""
    status, body = _request(f"{BASE_URL}/all-turkish-movies/")
    if status != 200:
        return []
    results = []
    matches = re.findall(r'<a[^>]*href="([^"]+)"[^>]*title="([^"]+)"[^>]*>', body)
    for href, title in matches:
        if "/movies/" in href:
            results.append({"url": href, "title": title})
    return results


# =============================================================================
# BUSCA INTELIGENTE
# =============================================================================
def _search_qrmzi(query, media_type):
    """
    Busca conteudo no qrmzi.tv.
    Tenta busca direta primeiro, depois fuzzy matching na lista completa.
    """
    if not query or len(query.strip()) < 2:
        return None

    # Estrategia 1: Busca direta no site
    search_url = BASE_URL + "/?s=" + urllib.parse.quote(query.strip())
    status, body = _request(search_url, headers={"Referer": BASE_URL + "/"})
    if status == 200 and body:
        articles = re.findall(r"<article[^>]*>.*?</article>", body, re.S | re.I)
        for art in articles:
            link = re.search(
                r'href=["\'](https?://www\.qrmzi\.tv/(?:movies|series|episode)/[^"\']+)["\']',
                art, re.S | re.I,
            )
            if link:
                return link.group(1)

    # Estrategia 2: Fuzzy matching na lista completa
    if media_type == "movie":
        all_items = _load_movies_list()
    else:
        all_items = _load_series_list()

    best_match = None
    best_score = 0.0

    for item in all_items:
        score = _word_overlap_score(query, item["title"])
        if score > best_score:
            best_score = score
            best_match = item["url"]

    if best_match and best_score >= 0.25:
        return best_match

    return None


# =============================================================================
# NAVEGACAO DE SERIES
# =============================================================================
def _get_series_episode_url(series_url, episode):
    """
    Extrai URL do episodio especifico da pagina da serie.
    Usa regex SIMPLES sem texto arabe (evita bug silencioso do Python regex).
    """
    status, body = _request(series_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return None

    pattern = r'href=["\'](https?://www\.qrmzi\.tv/episode/[^"\']+)["\']'
    matches = re.findall(pattern, body, re.I)

    for m in matches:
        if m.rstrip('/').endswith(f'-{episode}'):
            return m

    return None


# =============================================================================
# EXTRACAO DO IFRAME ALBAPLAYER
# =============================================================================
def _extract_player_iframe(page_url):
    """Extrai o iframe do AlbaPlayer."""
    status, body = _request(page_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return None

    m = re.search(
        r'<iframe[^>]+src=["\'](https?://w\.anaplayer\.online/[^"\']+)["\'][^>]*>',
        body, re.S | re.I,
    )
    if not m:
        return None

    src = m.group(1)
    if src.startswith("//"):
        src = "https:" + src
    return src


# =============================================================================
# DECODIFICADOR DE JAVASCRIPT PACKED
# =============================================================================
def _to_base(num, radix):
    chars = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if num == 0:
        return "0"
    n = num
    sb = []
    while n > 0:
        sb.append(chars[n % radix])
        n //= radix
    return "".join(reversed(sb))


def unpack_js(html):
    """
    Decodifica JavaScript packed:
    eval(function(p,a,c,k,e,d){...}('code',base,count,'dict'.split('|')))
    """
    eval_match = re.search(
        r'eval\s*\(\s*function\s*\(.*?}\s*\((.*)\)\s*\)',
        html,
        re.S,
    )
    if not eval_match:
        return None

    params_string = eval_match.group(1)
    params_match = re.search(
        r'["\'](.*?)["\']\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*["\'](.*?)["\']\.split\s*\(\s*["\']\|["\']\s*\)',
        params_string,
        re.S,
    )
    if not params_match:
        return None

    packed_code = params_match.group(1)
    base = int(params_match.group(2))
    count = int(params_match.group(3))
    dictionary_str = params_match.group(4)
    keywords = dictionary_str.split("|")

    replace_map = {}
    for i in range(count):
        keyword = keywords[i] if i < len(keywords) else ""
        if keyword:
            replace_map[_to_base(i, base)] = keyword

    deobfuscated = re.sub(
        r"\b\w+\b",
        lambda m: replace_map.get(m.group(0), m.group(0)),
        packed_code,
    )

    for pattern in [
        r'["\']?file["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?src["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?video["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?hls2["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?hls3["\']?\s*:\s*["\']([^"\']+)["\']',
        r'sources\s*:\s*\[.*?\{.*?file\s*:\s*["\']([^"\']+)["\']',
    ]:
        m = re.search(pattern, deobfuscated)
        if m:
            return m.group(1).replace("\\/", "/")

    return None


# =============================================================================
# EXTRACAO DE VIDEO DA PAGINA DE EMBED
# =============================================================================
def _extract_video_from_embed(embed_url):
    """
    Acessa embed do host de video e extrai URL direto.
    """
    status, body = _request(embed_url, headers={"Referer": "https://w.anaplayer.online/"})
    if status != 200 or not body:
        return None

    # Estrategia 1: Decodificar JS packed
    stream_url = unpack_js(body)
    if stream_url:
        return stream_url

    # Estrategia 2: Qualquer URL .mp4 ou .m3u8 direto no HTML
    direct = re.search(r'(https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*)', body, re.I)
    if direct:
        return direct.group(1)

    # Estrategia 3: Fallback pela imagem poster
    poster = re.search(
        r'<img[^>]+src=["\'](https?://[^"\']+/i/[^"\']+)["\']', body, re.S | re.I
    )
    if poster:
        guess = poster.group(1).replace("/i/", "/v/").replace(".jpg", ".mp4")
        return guess

    return None


# =============================================================================
# ANALISE M3U8 - FIX PRINCIPAL: deteccao por RESOLUCAO
# =============================================================================
def _parse_m3u8_max_quality(m3u8_url, referer):
    """
    Analisa master.m3u8 e retorna APENAS a maior qualidade.
    FIX PRINCIPAL: Usa RESOLUCAO (altura) como indicador primario de qualidade,
    nao apenas BANDWIDTH. Isso corrige o bug onde 1080p com ~3.4M bandwidth
    era classificado como 720p.
    """
    try:
        req = urllib.request.Request(
            m3u8_url,
            headers={"User-Agent": USER_AGENT, "Referer": referer},
        )
        with _opener.open(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None, None

    best_url = None
    best_height = 0
    best_name = "Auto"
    lines = content.split("\n")
    base_url = m3u8_url.rsplit("/", 1)[0] + "/"

    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            bw_match = re.search(r'BANDWIDTH=(\d+)', line)
            res_match = re.search(r'RESOLUTION=(\d+x(\d+))', line)

            bandwidth = int(bw_match.group(1)) if bw_match else 0
            resolution = res_match.group(1) if res_match else ""
            height = int(res_match.group(2)) if res_match else 0

            if i + 1 < len(lines):
                stream_url = lines[i + 1].strip()
                if stream_url and not stream_url.startswith("#"):
                    if not stream_url.startswith("http"):
                        stream_url = base_url + stream_url

                    # FIX: Usa altura da resolucao como criterio PRIMARIO
                    if height > best_height:
                        best_height = height
                        best_url = stream_url
                        if height >= 1080:
                            best_name = "1080p"
                        elif height >= 720:
                            best_name = "720p"
                        elif height >= 480:
                            best_name = "480p"
                        elif height >= 360:
                            best_name = "360p"
                        else:
                            best_name = "240p"
                    # Se altura igual, usa bandwidth como desempate
                    elif height == best_height and bandwidth > 0:
                        best_bandwidth = 0  # nao rastreamos bandwidth do best, simplificado
                        best_url = stream_url

    return best_name, best_url


# =============================================================================
# EXTRACAO DE TODOS OS SERVIDORES
# =============================================================================
def _extract_all_servers(player_base_url):
    """
    Acessa todos os servidores do AlbaPlayer e extrai videos.
    """
    all_sources = []

    server_names = {
        "1": "CDNPlus",
        "2": "MP4Plus",
        "3": "AnaFast",
        "4": "Vidoba",
        "5": "VidSpeed",
        "6": "larhu",
    }

    if not player_base_url.endswith('/'):
        player_base_url += '/'

    for serv_num, serv_name in server_names.items():
        url = player_base_url + "?serv=" + serv_num

        try:
            status, body = _request(url, headers={"Referer": BASE_URL + "/"})
            if status != 200 or not body:
                continue

            iframe = re.search(
                r'<iframe[^>]+src=["\']([^"\']+)["\'][^>]*>', body, re.S | re.I
            )
            if not iframe:
                continue

            embed = iframe.group(1)
            if embed.startswith("//"):
                embed = "https:" + embed

            # Pula redes sociais
            if any(x in embed for x in ["vk.com", "ok.ru", "youtube", "dailymotion"]):
                continue

            video_url = _extract_video_from_embed(embed)
            if not video_url:
                continue

            if video_url.startswith("//"):
                video_url = "https:" + video_url

            quality = "HD"
            if "1080" in video_url.lower():
                quality = "1080p"
            elif "720" in video_url.lower():
                quality = "720p"
            elif "480" in video_url.lower():
                quality = "480p"

            # Se for m3u8, analisa e pega maior qualidade
            if video_url.endswith(".m3u8"):
                q_name, q_url = _parse_m3u8_max_quality(video_url, embed)
                if q_url:
                    video_url = q_url
                    quality = q_name

            all_sources.append({
                "url": video_url,
                "quality": quality,
                "server": serv_name,
                "referer": embed,
            })

        except Exception:
            continue

    return all_sources


# =============================================================================
# RESOLUCAO DE FILMES
# =============================================================================
def _resolve_movie(imdb_id):
    """Resolve filme."""
    try:
        info = _tmdb_find(imdb_id)
        if not info:
            return []

        queries = []
        ar_title = _tmdb_arabic_title(info["tmdb_id"], "movie")
        if ar_title:
            queries.append(ar_title)
        if info.get("original_title"):
            queries.append(info["original_title"])
        if info.get("title"):
            queries.append(info["title"])

        for query in queries:
            result_url = _search_qrmzi(query, "movie")
            if result_url:
                player = _extract_player_iframe(result_url)
                if player:
                    sources = _extract_all_servers(player)
                    if sources:
                        return sources
        return []
    except Exception:
        return []


# =============================================================================
# RESOLUCAO DE SERIES
# =============================================================================
def _resolve_series(imdb_id, season, episode):
    """Resolve serie."""
    try:
        info = _tmdb_find(imdb_id)
        if not info:
            return []

        queries = []
        ar_title = _tmdb_arabic_title(info["tmdb_id"], "tv")
        if ar_title:
            queries.append(ar_title)
        if info.get("original_name"):
            queries.append(info["original_name"])
        if info.get("title"):
            queries.append(info["title"])

        for query in queries:
            result_url = _search_qrmzi(query, "series")
            if result_url:
                ep_url = _get_series_episode_url(result_url, episode)
                if ep_url:
                    player = _extract_player_iframe(ep_url)
                    if player:
                        sources = _extract_all_servers(player)
                        if sources:
                            return sources
        return []
    except Exception:
        return []


# =============================================================================
# ENTRADA PRINCIPAL MEGASOURCE
# =============================================================================
def get_streams(media_type, media_id, config=None):
    """
    Ponto de entrada do MegaSource.
    """
    imdb_id = media_id
    season = episode = None

    if ":" in media_id:
        parts = media_id.split(":", 2)
        if len(parts) == 3:
            imdb_id, season, episode = parts[0], parts[1], parts[2]

    sources = []
    if media_type == "movie":
        sources = _resolve_movie(imdb_id)
    elif media_type == "series" and season and episode:
        sources = _resolve_series(imdb_id, int(season), int(episode))

    streams = []
    has_1080p = False

    # Primeira passagem: verifica se ha 1080p
    for src in sources:
        if re.search(r"1080[pi]?", src.get("quality", ""), re.I):
            has_1080p = True
            break
        if re.search(r"1080[pi]?", src.get("url", ""), re.I):
            has_1080p = True
            break

    for src in sources:
        quality = src.get("quality", "")

        # Se existe 1080p em ALGUM servidor, filtra apenas 1080p
        # Se NAO existe 1080p, retorna TUDO para nao ficar vazio
        if has_1080p:
            if not re.search(r"1080[pi]?", quality, re.I):
                if not re.search(r"1080[pi]?", src.get("url", ""), re.I):
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
                            "Origin": "https://w.anaplayer.online",
                            "Referer": src.get("referer", "https://w.anaplayer.online/"),
                        }
                    },
                },
            }
        )

    return streams
