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
VERSION = "2.1.0"
DESCRIPTION = "مسلسلات تركية وعربية مترجمة (krmzi.org)"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TMDB_API_KEY = "ce91d0c4d737fceb1801c2bf58417b4b"
BASE_URL = "https://krmzi.org"

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

        # Tenta obter titulo arabe tambem
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
    """Normaliza texto para comparacao."""
    return text.lower().replace("مسلسل", "").replace("-", " ").strip()


def search_krmzy(query):
    if not query:
        return None

    queries_to_try = []
    if isinstance(query, dict):
        # Dicionario com varios titulos
        for key in ["arabic_name", "title", "original_name"]:
            val = query.get(key, "")
            if val and val not in queries_to_try:
                queries_to_try.append(val)
    else:
        queries_to_try.append(query)

    # Remove duplicados e vazios
    queries_to_try = [q for q in queries_to_try if q]

    for q in queries_to_try:
        result = _search_single(q)
        if result:
            return result

    # Fallback: busca na lista de series
    return _search_in_list(queries_to_try)


def _search_single(query):
    encoded = urllib.parse.quote(query)
    url = f"{BASE_URL}/?s={encoded}"
    status, body = _request(url)

    if status == 200 and "نقوم حالياً بتحديث مكتبتنا" not in body and "تحديث مكتبتنا" not in body:
        # Busca normal funcionou
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
    if status != 200:
        return None

    # Extrai todas as series da lista
    all_series = re.findall(
        r'<a[^>]*href="([^"]+)"[^>]*title="([^"]+)"[^>]*>',
        body,
    )

    for href, title in all_series:
        if "/series/" not in href:
            continue
        title_norm = _normalize(title)
        for q in queries:
            q_norm = _normalize(q)
            # Verifica se alguma palavra significativa do query esta no titulo
            q_words = [w for w in q_norm.split() if len(w) > 2]
            for word in q_words:
                if word in title_norm:
                    return _abs_url(href)

    return None


def get_series_page(url):
    status, body = _request(url)
    if status != 200:
        return None, None

    # Verifica redirecionamento para pagina da serie
    # Cuidado: nao redirecionar para paginas de ator
    series_match = re.search(
        r'<div[^>]*class=["\'][^"\']*singleSeries[^"\']*["\'][^>]*>.*?'
        r'<div[^>]*class=["\'][^"\']*info[^"\']*["\'][^>]*>.*?'
        r'<h1[^>]*>.*?<a[^>]*href=["\']([^"\']+)["\']',
        body,
        re.S | re.I,
    )
    if series_match:
        series_url = _abs_url(series_match.group(1))
        # So redireciona se for pagina de serie
        if "/series/" in series_url:
            status2, body2 = _request(series_url)
            if status2 == 200:
                return series_url, body2

    return url, body


def find_episode(series_url, season, episode):
    url, body = get_series_page(series_url)
    if not body:
        return None

    # Extrai episodios
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

        # Numero do episodio: ultimo span dentro de episodeNum
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

    # Mesmo comportamento do Kotlin: reversed()
    episodes = list(reversed(episodes))

    # Busca pelo numero
    for ep in episodes:
        if ep["num"] == episode:
            return ep["url"]

    # Fallback pelo indice
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

    # Tenta varios padroes de URL
    for pattern in [
        r'["\']?file["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?hls2["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?video["\']?\s*:\s*["\']([^"\']+)["\']',
        r'["\']?src["\']?\s*:\s*["\']([^"\']+)["\']',
    ]:
        m = re.search(pattern, deobfuscated)
        if m:
            return m.group(1).replace("\\/", "/")

    return None


def check_working_referer(stream_url):
    candidates = [
        "https://qesen.net/",
        "https://newaat.com/",
        "https://v.turkvearab.com/",
        "https://arabveturk.com/",
        "https://iplayerhls.com/",
    ]

    for ref in candidates:
        try:
            req = urllib.request.Request(
                stream_url,
                headers={"User-Agent": USER_AGENT, "Referer": ref},
            )
            with _opener.open(req, timeout=10) as resp:
                if resp.status == 200:
                    return ref
        except Exception:
            continue

    return "https://qesen.net/"


def _ensure_http(u):
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    return "https://" + u


def get_episode_streams(episode_url):
    status, body = _request(episode_url)
    if status != 200:
        return []

    # CORRECAO PRINCIPAL: regex flexivel para fullscreen-clickable
    # O href pode vir antes ou depois do class
    fs_match = re.search(
        r'<a[^>]*href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*fullscreen-clickable[^"\']*["\']',
        body,
        re.S | re.I,
    )
    if not fs_match:
        # Tenta ordem inversa (class antes de href)
        fs_match = re.search(
            r'<a[^>]*class=["\'][^"\']*fullscreen-clickable[^"\']*["\'][^>]*href=["\']([^"\']+)["\']',
            body,
            re.S | re.I,
        )
    if not fs_match:
        return []

    fs_href = fs_match.group(1)

    # Extrai o parametro 'post' base64 da URL
    post_match = re.search(r'post=([A-Za-z0-9+/=]+)', fs_href)
    if not post_match:
        return []

    try:
        decoded = base64.b64decode(post_match.group(1)).decode("utf-8")
        post_data = json.loads(decoded)
    except Exception:
        return []

    servers = post_data.get("servers", [])
    if not servers:
        return []

    streams = []

    for server in servers:
        name = server.get("name", "").lower().strip()
        sid = server.get("id", "").strip()
        if not sid:
            continue

        embed_url = None
        stream_url = None
        server_title = server.get("name", "Unknown")

        if name in ("arab hd", "arabhd", "arab-hd"):
            embed_url = f"https://v.turkvearab.com/embed-{sid}.html"
            s, html = _request(embed_url, headers={"Referer": episode_url})
            if s == 200:
                stream_url = unpack_js(html)

        elif name == "estream":
            embed_url = f"https://arabveturk.com/embed-{sid}.html"
            s, html = _request(embed_url, headers={"Referer": episode_url})
            if s == 200:
                stream_url = unpack_js(html)

        elif name == "express":
            stream_url = sid if sid.startswith("http") else _ensure_http(sid)

        elif name == "ok":
            stream_url = _ensure_http(f"//ok.ru/videoembed/{sid}")

        elif name in ("pro hd", "prohd", "pro-hd"):
            stream_url = f"https://ebtv.upns.live/#{sid}"

        elif name in ("red hd", "redhd", "red-hd"):
            embed_url = f"https://iplayerhls.com/e/{sid}"
            s, html = _request(embed_url, headers={"Referer": episode_url})
            if s == 200:
                stream_url = unpack_js(html)

        if not stream_url:
            continue

        # Para m3u8, determina referer correto
        referer = "https://krmzi.org/"
        if stream_url.endswith(".m3u8"):
            referer = check_working_referer(stream_url)

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer,
        }
        if referer != "https://krmzi.org/":
            headers["Origin"] = referer.rstrip("/")

        streams.append({
            "name": TITLE,
            "title": server_title,
            "url": stream_url,
            "behaviorHints": {
                "notMyMetadata": True,
                "proxyHeaders": {
                    "request": headers,
                },
            },
        })

    return streams


def get_streams(media_type, media_id, config=None):
    # Krmzy tem apenas series
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

    # Tenta buscar com varios titulos (arabe, ingles, original)
    series_url = search_krmzy(tmdb_info)
    if not series_url:
        return []

    episode_url = find_episode(series_url, season, episode)
    if not episode_url:
        return []

    return get_episode_streams(episode_url)
