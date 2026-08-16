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
import urllib.error
import urllib.parse
import urllib.request

# =============================================================================
# METADADOS DO SCRAPER
# =============================================================================
TITLE = "Qrmzi.tv"
VERSION = "6.0.0"
DESCRIPTION = "Turkish Movies & Series (Arabic)"

# =============================================================================
# CONSTANTES
# =============================================================================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TMDB_API_KEY = "92c1507cc18d85290e7a0b96abb37316"
BASE_URL = "https://www.qrmzi.tv"

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


# =============================================================================
# HTTP HELPER (igual ao krmzi.org)
# =============================================================================
def _request(url, method="GET", data=None, headers=None):
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)

    body = None
    if method == "POST":
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
        elif data is not None:
            body = data

    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with _opener.open(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception:
        return 0, ""


# =============================================================================
# TMDB - BUSCA TITULO (igual ao krmzi.org)
# =============================================================================
def imdb_to_tmdb(imdb_id):
    find_url = "https://api.themoviedb.org/3/find/" + urllib.parse.quote(imdb_id)
    query = urllib.parse.urlencode(
        {"api_key": TMDB_API_KEY, "external_source": "imdb_id"}
    )
    status, body = _request(find_url + "?" + query)
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None

    if data.get("tv_results"):
        item = data["tv_results"][0]
        tmdb_id = item["id"]
        title = item.get("name", "")
        original = item.get("original_name", "")
        
        # Busca titulo arabe
        arabic_title = ""
        try:
            detail_url = f"https://api.themoviedb.org/3/tv/{tmdb_id}?api_key={TMDB_API_KEY}&language=ar"
            s2, b2 = _request(detail_url)
            if s2 == 200:
                detail = json.loads(b2)
                arabic_title = detail.get("name", "")
        except Exception:
            pass
        
        return {
            "type": "tv",
            "tmdb_id": tmdb_id,
            "title": title,
            "original_name": original,
            "arabic_name": arabic_title,
        }
    
    if data.get("movie_results"):
        item = data["movie_results"][0]
        tmdb_id = item["id"]
        title = item.get("title", "")
        original = item.get("original_title", "")
        
        # Busca titulo arabe
        arabic_title = ""
        try:
            detail_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={TMDB_API_KEY}&language=ar"
            s2, b2 = _request(detail_url)
            if s2 == 200:
                detail = json.loads(b2)
                arabic_title = detail.get("title", "")
        except Exception:
            pass
        
        return {
            "type": "movie",
            "tmdb_id": tmdb_id,
            "title": title,
            "original_title": original,
            "arabic_name": arabic_title,
        }
    
    return None


# =============================================================================
# BUSCA NO QRMZI.TV (igual ao krmzi.org)
# =============================================================================
def _normalize(text):
    return text.lower().replace("مسلسل", "").replace("فيلم", "").replace("-", " ").replace("  ", " ").strip()


def _word_overlap_score(query, title):
    q_words = set(w for w in _normalize(query).split() if len(w) >= 2)
    t_words = set(w for w in _normalize(title).split() if len(w) >= 2)
    if not q_words or not t_words:
        return 0.0
    intersection = q_words & t_words
    return len(intersection) / len(q_words)


def _abs_url(href):
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return BASE_URL + href
    if not href.startswith("http"):
        return BASE_URL + "/" + href
    return href


def search_qrmzi(query_info):
    if not query_info:
        return None
    
    queries_to_try = []
    if isinstance(query_info, dict):
        # Prioridade: arabe > ingles > original
        for key in ["arabic_name", "title", "original_name", "original_title"]:
            val = query_info.get(key, "")
            if val and val not in queries_to_try:
                queries_to_try.append(val)
    else:
        queries_to_try.append(query_info)
    
    queries_to_try = [q for q in queries_to_try if q]
    
    # Estrategia 1: Busca direta
    for q in queries_to_try:
        result = _search_single(q)
        if result:
            return result
    
    # Estrategia 2: Fuzzy matching na lista completa
    return _search_in_list(queries_to_try)


def _search_single(query):
    encoded = urllib.parse.quote(query)
    url = f"{BASE_URL}/?s={encoded}"
    status, body = _request(url)
    
    if status == 200 and body:
        blocks = re.findall(
            r'<div[^>]*class=["\'][^"\']*block-post[^"\']*["\'][^>]*>(.*?)</div>',
            body,
            re.S | re.I,
        )
        for block in blocks:
            a_match = re.search(r'<a[^>]*href=["\']([^"\']+)["\']', block)
            if a_match:
                href = a_match.group(1)
                if "/series/" in href or "/movies/" in href or "/episode/" in href:
                    return _abs_url(href)
        
        articles = re.findall(
            r'<article[^>]*class=["\'][^"\']*postEp[^"\']*["\'][^>]*>(.*?)</article>',
            body,
            re.S | re.I,
        )
        for art in articles:
            a_match = re.search(r'<a[^>]*href=["\']([^"\']+)["\']', art)
            if a_match:
                href = a_match.group(1)
                if "/series/" in href or "/movies/" in href or "/episode/" in href:
                    return _abs_url(href)
    
    return None


def _search_in_list(queries):
    media_type = "movie" if any("movie_results" in str(q) for q in queries) else "series"
    
    if media_type == "movie":
        list_url = f"{BASE_URL}/all-turkish-movies/"
    else:
        list_url = f"{BASE_URL}/all-turkish-series/"
    
    status, body = _request(list_url)
    if status != 200:
        return None
    
    all_items = re.findall(
        r'<a[^>]*href="([^"]+)"[^>]*title="([^"]+)"[^>]*>',
        body,
    )
    
    best_match = None
    best_score = 0.0
    
    for href, title in all_items:
        if media_type == "movie" and "/movies/" not in href:
            continue
        if media_type == "series" and "/series/" not in href:
            continue
        
        for q in queries:
            score = _word_overlap_score(q, title)
            if score > best_score:
                best_score = score
                best_match = href
    
    if best_match and best_score >= 0.25:
        return _abs_url(best_match)
    
    return None


# =============================================================================
# NAVEGACAO DE SERIES
# =============================================================================
def get_series_page(url):
    status, body = _request(url)
    if status != 200:
        return None, None
    
    # Se ja for pagina de serie, retorna ela mesma
    if "/series/" in url:
        return url, body
    
    # Se for episodio, tenta derivar URL da serie
    series_match = re.search(
        r'<div[^>]*class=["\'][^"\']*singleSeries[^"\']*["\'][^>]*>.*?'
        r'<div[^>]*class=["\'][^"\']*info[^"\']*["\'][^>]*>.*?'
        r'<h1[^>]*>.*?<a[^>]*href=["\']([^"\']+)["\']',
        body,
        re.S | re.I,
    )
    if series_match:
        series_url = _abs_url(series_match.group(1))
        if "/series/" in series_url:
            status2, body2 = _request(series_url)
            if status2 == 200:
                return series_url, body2
    
    return url, body


def find_episode(series_url, episode):
    url, body = get_series_page(series_url)
    if not body:
        return None

    episodes = []
    for match in re.finditer(
        r'<article[^>]*class=["\'][^"\']*postEp[^"\']*["\'][^>]*>(.*?)</article>',
        body,
        re.S | re.I,
    ):
        block = match.group(1)
        a_match = re.search(r'<a[^>]*href=["\']([^"\']+)["\']', block)
        if not a_match:
            continue

        ep_url = _abs_url(a_match.group(1))

        num_match = re.search(
            r'<div[^>]*class=["\'][^"\']*episodeNum[^"\']*["\'][^>]*>.*?'
            r'<span[^>]*>[^<]*</span>.*?'
            r'<span[^>]*>(\d+)</span>',
            block,
            re.S | re.I,
        )
        ep_num = 0
        if num_match:
            try:
                ep_num = int(num_match.group(1).strip())
            except ValueError:
                pass

        episodes.append({"url": ep_url, "num": ep_num})

    episodes = list(reversed(episodes))

    for ep in episodes:
        if ep["num"] == episode:
            return ep["url"]

    if 1 <= episode <= len(episodes):
        return episodes[episode - 1]["url"]

    return None


# =============================================================================
# DECODIFICADOR JS PACKED (igual ao krmzi.org)
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
    ]:
        m = re.search(pattern, deobfuscated)
        if m:
            return m.group(1).replace("\\/", "/")

    return None


# =============================================================================
# EXTRACAO DE STREAMS (igual ao krmzi.org)
# =============================================================================
def get_episode_streams(episode_url):
    status, body = _request(episode_url)
    if status != 200:
        return []

    # Extrai iframe do AlbaPlayer
    iframe_match = re.search(
        r'<iframe[^>]+src=["\'](https?://w\.anaplayer\.online/[^"\']+)["\']',
        body,
        re.S | re.I,
    )
    if not iframe_match:
        return []
    
    player_url = iframe_match.group(1)
    if player_url.startswith("//"):
        player_url = "https:" + player_url
    
    # Garante URL base correta
    if not player_url.endswith('/'):
        player_url += '/'

    servers = [
        ("1", "CDNPlus"),
        ("2", "MP4Plus"),
        ("3", "AnaFast"),
        ("4", "Vidoba"),
        ("5", "VidSpeed"),
        ("6", "larhu"),
    ]

    streams = []

    for serv_num, serv_name in servers:
        url = player_url + "?serv=" + serv_num
        s, html = _request(url, headers={"Referer": episode_url})
        if s != 200:
            continue
        
        # Extrai iframe do embed do servidor
        embed_iframe = re.search(
            r'<iframe[^>]+src=["\']([^"\']+)["\'][^>]*>',
            html,
            re.S | re.I,
        )
        if not embed_iframe:
            continue
        
        embed = embed_iframe.group(1)
        if embed.startswith("//"):
            embed = "https:" + embed
        
        # Pula redes sociais
        if any(x in embed for x in ["vk.com", "ok.ru", "youtube", "dailymotion"]):
            continue
        
        # Extrai video do embed
        s2, embed_html = _request(embed, headers={"Referer": url})
        if s2 != 200:
            continue
        
        stream_url = unpack_js(embed_html)
        if not stream_url:
            # Fallback: procura URL direta
            direct = re.search(r'(https?://[^\s"\'<>]+\.(?:mp4|m3u8)[^\s"\'<>]*)', embed_html, re.I)
            if direct:
                stream_url = direct.group(1)
        
        if not stream_url:
            continue
        
        if stream_url.startswith("//"):
            stream_url = "https:" + stream_url

        # Detecta qualidade pelo URL
        quality = "HD"
        if "1080" in stream_url.lower():
            quality = "1080p"
        elif "720" in stream_url.lower():
            quality = "720p"
        elif "480" in stream_url.lower():
            quality = "480p"
        elif "360" in stream_url.lower():
            quality = "360p"

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": embed,
        }

        streams.append({
            "name": TITLE,
            "title": f"{serv_name} - {quality}",
            "url": stream_url,
            "behaviorHints": {
                "notMyMetadata": True,
                "proxyHeaders": {
                    "request": headers,
                },
            },
        })

    return streams


# =============================================================================
# ENTRADA PRINCIPAL MEGASOURCE
# =============================================================================
def get_streams(media_type, media_id, config=None):
    if media_type == "movie":
        if ":" in media_id:
            return []
        
        tmdb_info = imdb_to_tmdb(media_id)
        if not tmdb_info:
            return []
        
        movie_url = search_qrmzi(tmdb_info)
        if not movie_url:
            return []
        
        # Para filmes, a pagina do filme contem o iframe diretamente
        return get_episode_streams(movie_url)
    
    elif media_type == "series":
        if ":" not in media_id:
            return []
        
        parts = media_id.split(":", 2)
        if len(parts) != 3:
            return []
        
        imdb_id, season_str, episode_str = parts
        try:
            episode = int(episode_str)
        except ValueError:
            return []
        
        tmdb_info = imdb_to_tmdb(imdb_id)
        if not tmdb_info:
            return []
        
        series_url = search_qrmzi(tmdb_info)
        if not series_url:
            return []
        
        episode_url = find_episode(series_url, episode)
        if not episode_url:
            return []
        
        return get_episode_streams(episode_url)
    
    return []
