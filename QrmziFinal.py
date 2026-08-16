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
VERSION = "3.0.0"
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
    """
    Busca traducao arabe do TMDB. CRITICO porque qrmzi.tv usa titulos em arabe.
    """
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
# BUSCA NO QRMZI.TV
# =============================================================================
def _search_qrmzi(query):
    """
    Busca no motor WordPress do qrmzi.tv.
    Retorna lista de dicts com url e tipo.
    """
    if not query or len(query.strip()) < 2:
        return []

    search_url = BASE_URL + "/?s=" + urllib.parse.quote(query.strip())
    status, body = _request(search_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return []

    results = []
    seen = set()

    # WordPress retorna resultados em <article>
    articles = re.findall(r"<article[^>]*>.*?</article>", body, re.S | re.I)
    for art in articles:
        link = re.search(
            r'href=["\'](https?://www\.qrmzi\.tv/(?:movies|series|episode)/[^"\']+)["\']',
            art, re.S | re.I,
        )
        if not link:
            continue

        url = link.group(1)
        if url in seen:
            continue
        seen.add(url)

        title = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", art, re.S | re.I)
        title_clean = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else ""

        if "/movies/" in url:
            item_type = "movie"
        elif "/series/" in url:
            item_type = "series"
        else:
            item_type = "episode"

        results.append({"title": title_clean, "url": url, "type": item_type})

    return results


# =============================================================================
# NAVEGACAO DE SERIES: PAGINA DA SERIE -> EPISODIO ESPECIFICO
# =============================================================================
def _get_series_episode_url(series_title, season, episode):
    """
    Dado um titulo de serie, encontra a pagina da serie no qrmzi.tv
    e extrai o URL do episodio especifico.
    """
    results = _search_qrmzi(series_title)
    series_url = None

    for r in results:
        if r["type"] == "series" and "/series/" in r["url"]:
            series_url = r["url"]
            break
        elif "/episode/" in r["url"]:
            # Deriva URL da serie a partir do episodio
            # Ex: /episode/مسلسل-حب-محتمل-الحلقة-1/ -> /series/مسلسل-حب-محتمل/
            slug_match = re.search(r'/episode/([^/]+)-الحلقة-\d+', r["url"])
            if slug_match:
                series_url = BASE_URL + "/series/" + slug_match.group(1) + "/"
                break

    if not series_url:
        return None

    # Busca episodios na pagina da serie
    status, body = _request(series_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return None

    # Procura link do episodio: /episode/...-الحلقة-{numero}/
    ep_pattern = r'href=["\'](https?://www\.qrmzi\.tv/episode/[^"\']+-الحلقة-' + str(episode) + r'(?:[-/]|$)[^"\']*)["\']'
    ep_match = re.search(ep_pattern, body, re.S | re.I)
    if ep_match:
        return ep_match.group(1)

    # Fallback: lista todos os episodios e busca pelo numero
    all_eps = re.findall(
        r'href=["\'](https?://www\.qrmzi\.tv/episode/[^"\']+-الحلقة-\d+[^"\']*)["\']',
        body, re.S | re.I,
    )
    for ep_url in sorted(set(all_eps)):
        if f"-الحلقة-{episode}" in ep_url or f"-الحلقة-{episode}/" in ep_url:
            return ep_url

    return None


# =============================================================================
# EXTRACAO DO IFRAME ALBAPLAYER
# =============================================================================
def _extract_player_iframe(page_url):
    """Extrai o iframe do AlbaPlayer da pagina do filme/episodio."""
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
# DECODIFICADOR DE JAVASCRIPT PACKED (do krmzi.org, adaptado)
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
    Decodifica JavaScript no formato:
    eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(...)}('code',base,'dict'));
    Usado pelos hosts de video (cdnplus, mp4plus, etc).
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
        r'["\']?hls2["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?hls3["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?file["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?video["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?src["\']?\s*:\s*["\']([^"\']+)["\']',
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
    Acessa a pagina de embed do host de video e extrai o URL direto.
    Retorna (video_url, is_m3u8) ou (None, False).
    """
    status, body = _request(embed_url, headers={"Referer": "https://w.anaplayer.online/"})
    if status != 200 or not body:
        return None, False

    # ================================================================
    # Estrategia 1: Decodificar JS packed do JWPlayer
    # ================================================================
    stream_url = unpack_js(body)
    if stream_url:
        is_m3u8 = stream_url.endswith(".m3u8")
        return stream_url, is_m3u8

    # ================================================================
    # Estrategia 2: Fallback pela imagem poster -> guess video URL
    # Hosts como cdnplus usam: /i/01/00005/xxxxx.jpg (poster)
    # O video pode estar em: /v/01/00005/xxxxx.mp4
    # ================================================================
    poster = re.search(
        r'<img[^>]+src=["\'](https?://[^"\']+/i/[^"\']+)["\']', body, re.S | re.I
    )
    if poster:
        guess = poster.group(1).replace("/i/", "/v/").replace(".jpg", ".mp4")
        return guess, False

    # ================================================================
    # Estrategia 3: Qualquer URL .mp4 ou .m3u8 direto no HTML
    # ================================================================
    direct = re.search(r'(https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*)', body, re.I)
    if direct:
        url = direct.group(1)
        return url, url.endswith(".m3u8")

    return None, False


# =============================================================================
# ANALISE M3U8 PARA MAIOR QUALIDADE
# =============================================================================
def _parse_m3u8_max_quality(m3u8_url, referer):
    """Analisa master.m3u8 e retorna APENAS a maior qualidade."""
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
    best_bandwidth = 0
    best_name = "Auto"
    lines = content.split("\n")
    base_url = m3u8_url.rsplit("/", 1)[0] + "/"

    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            bw_match = re.search(r'BANDWIDTH=(\d+)', line)
            res_match = re.search(r'RESOLUTION=(\d+x\d+)', line)

            bandwidth = int(bw_match.group(1)) if bw_match else 0
            resolution = res_match.group(1) if res_match else ""

            if i + 1 < len(lines):
                stream_url = lines[i + 1].strip()
                if stream_url and not stream_url.startswith("#"):
                    if not stream_url.startswith("http"):
                        stream_url = base_url + stream_url

                    if bandwidth > best_bandwidth:
                        best_bandwidth = bandwidth
                        best_url = stream_url
                        if bandwidth >= 4000000:
                            best_name = "1080p"
                        elif bandwidth >= 2000000:
                            best_name = "720p"
                        elif bandwidth >= 1000000:
                            best_name = "480p"
                        elif bandwidth >= 500000:
                            best_name = "360p"
                        else:
                            best_name = "240p"
                    elif resolution and not best_bandwidth:
                        h = int(resolution.split("x")[1])
                        if h > best_bandwidth:
                            best_bandwidth = h
                            best_url = stream_url
                            best_name = resolution.split("x")[1] + "p"

    return best_name, best_url


# =============================================================================
# EXTRACAO DE TODOS OS SERVIDORES DO ALBAPLAYER
# =============================================================================
def _extract_all_servers(player_base_url):
    """
    Acessa o player AlbaPlayer e extrai iframes de todos os servidores.
    Retorna lista de dicts com url do video, nome do servidor e qualidade.
    """
    all_sources = []

    # Servidores do AlbaPlayer (testados: 1-8)
    server_names = {
        "1": "CDNPlus",
        "2": "MP4Plus",
        "3": "AnaFast",
        "4": "Vidoba",
        "5": "VidSpeed",
        "6": "larhu",
    }
    # VK e OK sao embeds de redes sociais; pulamos por nao conseguir extrair MP4 direto

    for serv_num, serv_name in server_names.items():
        if "?" in player_base_url:
            url = player_base_url + "&serv=" + serv_num
        else:
            url = player_base_url + "?serv=" + serv_num

        try:
            status, body = _request(url, headers={"Referer": BASE_URL + "/"})
            if status != 200 or not body:
                continue

            # Extrai iframe do embed do servidor
            iframe = re.search(
                r'<iframe[^>]+src=["\']([^"\']+)["\'][^>]*>', body, re.S | re.I
            )
            if not iframe:
                continue

            embed = iframe.group(1)
            if embed.startswith("//"):
                embed = "https:" + embed

            # Pula embeds de redes sociais
            if any(x in embed for x in ["vk.com", "ok.ru", "youtube", "dailymotion"]):
                continue

            video_url, is_m3u8 = _extract_video_from_embed(embed)
            if not video_url:
                continue

            quality = "1080p"

            # Se for m3u8, analisa e pega apenas a maior qualidade
            if is_m3u8:
                q_name, q_url = _parse_m3u8_max_quality(video_url, embed)
                if q_url:
                    video_url = q_url
                    quality = q_name

            # ================================================================
            # فلترة 1080p: نتخطى السيرفرات التي لا تحتوي على 1080p
            # ================================================================
            # Se a qualidade for inferior a 1080p, pula
            if quality in ("720p", "480p", "360p", "240p"):
                continue

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
    """Resolve filme: IMDB -> TMDB -> qrmzi.tv -> Player -> Video 1080p."""
    try:
        info = _tmdb_find(imdb_id)
        if not info:
            return []

        # Coleta titulos para busca (arabe eh prioritario)
        queries = []
        ar_title = _tmdb_arabic_title(info["tmdb_id"], "movie")
        if ar_title:
            queries.append(ar_title)
        if info.get("original_title"):
            queries.append(info["original_title"])
        if info.get("title"):
            queries.append(info["title"])

        for query in queries:
            results = _search_qrmzi(query)
            for r in results:
                if r["type"] == "movie":
                    player = _extract_player_iframe(r["url"])
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
    """Resolve serie: IMDB -> TMDB -> qrmzi series page -> episodio -> Player -> Video 1080p."""
    try:
        info = _tmdb_find(imdb_id)
        if not info:
            return []

        # Busca titulo arabe prioritariamente
        queries = []
        ar_title = _tmdb_arabic_title(info["tmdb_id"], "tv")
        if ar_title:
            queries.append(ar_title)
        if info.get("original_name"):
            queries.append(info["original_name"])
        if info.get("title"):
            queries.append(info["title"])

        for query in queries:
            ep_url = _get_series_episode_url(query, season, episode)
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

    media_type: "movie" | "series"
    media_id: "tt0111161" ou "tt0944947:1:1"
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
    for src in sources:
        # ================================================================
        # فلترة نهائية صارمة: فقط 1080p
        # ================================================================
        quality = src.get("quality", "")
        if not re.search(r"1080[pi]?", quality, re.I):
            # Se nao tem 1080p no label, verifica na URL
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
