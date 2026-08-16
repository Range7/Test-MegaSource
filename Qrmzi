"""
Krmzy
================================

Protocol
--------
Seguindo o protocolo do MegaSource, este arquivo define:

 TITLE, VERSION, DESCRIPTION
 get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id : "tt0111161" (filme) | "tt0944947:1:1" (serie:temporada:episodio)

Retorna streams com behaviorHints.proxyHeaders
Usa apenas a biblioteca padrao do Python (urllib + cookiejar).

Para usar: suba este arquivo como scraper.py num repositorio do GitHub e
adicione a URL raw no addon MegaSource (pagina de configuracao).
"""

import base64
import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = "Krmzy"
VERSION = "3.0.0"
DESCRIPTION = "مسلسلات تركية وعربية مترجمة (qrmzi.tv) - 1080p فقط"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TMDB_API_KEY = "ce91d0c4d737fceb1801c2bf58417b4b"
BASE_URL = "https://www.qrmzi.tv"

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


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
    return None


def _abs_url(href):
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return BASE_URL + href
    if not href.startswith("http"):
        return BASE_URL + "/" + href
    return href


def _normalize(text):
    return text.lower().replace("مسلسل", "").replace("-", " ").replace("قرمزي", "").strip()


def _word_overlap_score(query, title):
    q_words = set(w for w in _normalize(query).split() if len(w) >= 2)
    t_words = set(w for w in _normalize(title).split() if len(w) >= 2)
    if not q_words or not t_words:
        return 0.0
    intersection = q_words & t_words
    return len(intersection) / len(q_words)


def search_qrmzy(query):
    if not query:
        return None
    
    queries_to_try = []
    if isinstance(query, dict):
        for key in ["arabic_name", "title", "original_name"]:
            val = query.get(key, "")
            if val and val not in queries_to_try:
                queries_to_try.append(val)
    else:
        queries_to_try.append(query)
    
    queries_to_try = [q for q in queries_to_try if q]
    
    for q in queries_to_try:
        result = _search_single(q)
        if result:
            return result
    
    return _search_in_list(queries_to_try)


def _search_single(query):
    encoded = urllib.parse.quote(query)
    url = f"{BASE_URL}/?s={encoded}"
    status, body = _request(url)
    
    if status == 200:
        blocks = re.findall(
            r'<div[^>]*class=["\'][^"\']*block-post[^"\']*["\'][^>]*>(.*?)</div>',
            body,
            re.S | re.I,
        )
        for block in blocks:
            a_match = re.search(r'<a[^>]*href=["\']([^"\']+)["\']', block)
            if a_match:
                href = a_match.group(1)
                if "/series/" in href or "/episode/" in href:
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
                if "/series/" in href or "/episode/" in href:
                    return _abs_url(href)
    
    return None


def _search_in_list(queries):
    status, body = _request(f"{BASE_URL}/series-list/")
n    if status != 200:
        return None
    
    all_series = re.findall(
        r'<a[^>]*href="([^"]+)"[^>]*title="([^"]+)"[^>]*>',
        body,
    )
    
    best_match = None
    best_score = 0.0
    
    for href, title in all_series:
        if "/series/" not in href:
            continue
        
        for q in queries:
            score = _word_overlap_score(q, title)
            if score > best_score:
                best_score = score
                best_match = href
    
    if best_match and best_score >= 0.25:
        return _abs_url(best_match)
    
    return None


def get_series_page(url):
    status, body = _request(url)
    if status != 200:
        return None, None

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


def find_episode(series_url, season, episode):
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
        r'["\']?file["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?src["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?video["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?m3u8["\']?\s*:\s*["\']([^"\']+)["\']',
    ]:
        m = re.search(pattern, deobfuscated)
        if m:
            return m.group(1).replace("\\/", "/")

    return None


def get_1080p_from_m3u8(m3u8_url, referer):
    """
    Analisa master.m3u8 e retorna APENAS a qualidade 1080p.
    Se nao houver 1080p, retorna None.
    """
    try:
        req = urllib.request.Request(
            m3u8_url,
            headers={"User-Agent": USER_AGENT, "Referer": referer},
        )
        with _opener.open(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    
    best_url = None
    best_bandwidth = 0
    lines = content.split("\n")
    base_url = m3u8_url.rsplit("/", 1)[0] + "/"
    
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            bw_match = re.search(r'BANDWIDTH=(\d+)', line)
            res_match = re.search(r'RESOLUTION=(\d+x\d+)', line)
            
            bandwidth = int(bw_match.group(1)) if bw_match else 0
            resolution = res_match.group(1) if res_match else ""
            
            # Verifica se eh 1080p
            is_1080p = False
            if resolution:
                h = int(resolution.split("x")[1])
                if h >= 1080:
                    is_1080p = True
            elif bandwidth >= 2500000:
                is_1080p = True
            
            if is_1080p and i + 1 < len(lines):
                stream_url = lines[i + 1].strip()
                if stream_url and not stream_url.startswith("#"):
                    if not stream_url.startswith("http"):
                        stream_url = base_url + stream_url
                    
                    # Pega a de maior bandwidth entre as 1080p
                    if bandwidth > best_bandwidth:
                        best_bandwidth = bandwidth
                        best_url = stream_url
    
    return best_url


def extract_server_video(embed_url, referer):
    """
    Extrai URL de video de um embed de servidor.
    Retorna (url, is_m3u8) ou (None, False).
    """
    status, html = _request(embed_url, headers={"Referer": referer})
    if status != 200:
        return None, False
    
    # Metodo 1: JS packed (cdnplus, anafast, etc)
    if "eval(function" in html:
        unpacked = unpack_js(html)
        if unpacked:
            is_m3u8 = unpacked.endswith(".m3u8") or ".m3u8" in unpacked
            return unpacked, is_m3u8
    
    # Metodo 2: URL direta no HTML
    vids = re.findall(r'https?://[^\s"<>]+\.(?:m3u8|mp4)[^\s"<>]*', html)
    if vids:
        url = vids[0]
        is_m3u8 = url.endswith(".m3u8") or ".m3u8" in url
        return url, is_m3u8
    
    # Metodo 3: Procura por iframe interno
    iframe = re.search(r'<iframe[^>]*src="([^"]+)"', html)
    if iframe:
        inner = iframe.group(1)
        if inner.startswith("http"):
            return extract_server_video(inner, embed_url)
    
    return None, False


def get_episode_streams(episode_url):
    status, body = _request(episode_url)
    if status != 200:
        return []
    
    # Extrai iframe do anaplayer
    iframe_match = re.search(
        r'<iframe[^>]*src=["\']([^"\']+)["\'][^>]*>',
        body,
        re.S | re.I,
    )
    if not iframe_match:
        return []
    
    anaplayer_url = iframe_match.group(1)
    
    # Busca todos os servidores no anaplayer
    # O anaplayer tem links como ?serv=1, ?serv=2, etc.
    # Vamos buscar a pagina base e extrair todos os iframes de servidores
    base_url = anaplayer_url.split("?")[0]
    
    streams = []
    
    # Tenta servidores 1-6
    for serv_num in range(1, 7):
        serv_url = f"{base_url}?serv={serv_num}"
        s, html = _request(serv_url, headers={"Referer": episode_url})
        if s != 200:
            continue
        
        # Extrai iframe do servidor
        serv_iframe = re.search(r'<iframe[^>]*src=["\']([^"\']+)["\']', html, re.S | re.I)
        if not serv_iframe:
            continue
        
        embed_url = serv_iframe.group(1)
        
        # Determina nome do servidor pelo dominio
        domain = embed_url.split("/")[2] if "://" in embed_url else ""
        if "cdnplus" in domain:
            server_name = "CDNPlus"
        elif "mp4plus" in domain:
            server_name = "MP4Plus"
        elif "anafast" in domain:
            server_name = "AnaFast"
        elif "vidoba" in domain:
            server_name = "Vidoba"
        elif "vidspeed" in domain:
            server_name = "VidSpeed"
        elif "ok.ru" in domain:
            server_name = "OK.ru"
        else:
            server_name = domain.split(".")[0].capitalize()
        
        # Extrai video do embed
        video_url, is_m3u8 = extract_server_video(embed_url, serv_url)
        if not video_url:
            continue
        
        referer = f"https://{domain}/" if domain else BASE_URL + "/"
        
        # Se for m3u8, extrai APENAS 1080p
        if is_m3u8:
            url_1080p = get_1080p_from_m3u8(video_url, referer)
            if url_1080p:
                # 1080p encontrado!
                headers = {
                    "User-Agent": USER_AGENT,
                    "Referer": referer,
                    "Origin": referer.rstrip("/"),
                }
                streams.append({
                    "name": TITLE,
                    "title": f"{server_name} - 1080p",
                    "url": url_1080p,
                    "behaviorHints": {
                        "notMyMetadata": True,
                        "proxyHeaders": {
                            "request": headers,
                        },
                    },
n                })
            # Se nao tiver 1080p, ignora (nao adiciona)
        else:
            # MP4 direto - assume que eh alta qualidade
            headers = {
                "User-Agent": USER_AGENT,
                "Referer": referer,
                "Origin": referer.rstrip("/"),
            }
            streams.append({
                "name": TITLE,
                "title": f"{server_name} - 1080p",
                "url": video_url,
                "behaviorHints": {
                    "notMyMetadata": True,
                    "proxyHeaders": {
                        "request": headers,
                    },
                },
            })
    
    # Ordena: 1080p primeiro (todos sao 1080p aqui, mas mantem a ordem)
    return streams


def get_streams(media_type, media_id, config=None):
    if media_type != "series":
        return []

    if ":" not in media_id:
        return []

    parts = media_id.split(":", 2)
    if len(parts) != 3:
        return []

    imdb_id, season_str, episode_str = parts
    try:
        season = int(season_str)
        episode = int(episode_str)
    except ValueError:
        return []

    tmdb_info = imdb_to_tmdb(imdb_id)
    if not tmdb_info:
        return []

    series_url = search_qrmzy(tmdb_info)
    if not series_url:
        return []

    episode_url = find_episode(series_url, season, episode)
    if not episode_url:
        return []

    return get_episode_streams(episode_url)
