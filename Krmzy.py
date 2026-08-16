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
VERSION = "2.0.0"
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
        return {"type": "tv", "tmdb_id": item["id"], "title": item.get("name")}
    return None


def _abs_url(href):
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return BASE_URL + href
    if not href.startswith("http"):
        return BASE_URL + "/" + href
    return href


def search_krmzy(query):
    encoded = urllib.parse.quote(query)

    # Tenta busca direta primeiro
    url = f"{BASE_URL}/?s={encoded}"
    status, body = _request(url)

    # Se pagina de busca estiver em manutencao, usa series-list
    if status != 200 or "نقوم حالياً بتحديث مكتبتنا" in body or "تحديث مكتبتنا" in body:
        status, body = _request(f"{BASE_URL}/series-list/")
        if status != 200:
            return None

        # Procura na lista de series pelo titulo (parcial)
        query_clean = query.lower().replace("مسلسل", "").strip()
        pattern = r'<a[^>]*href="([^"]+)"[^>]*title="([^"]*' + re.escape(query_clean[:12]) + r'[^"]*)"'
        matches = re.findall(pattern, body, re.I)
        if matches:
            return _abs_url(matches[0][0])

        # Fallback: procura qualquer link de serie na pagina
        all_series = re.findall(
            r'<a[^>]*href="([^"]+)"[^>]*title="([^"]+)"[^>]*>',
            body,
        )
        for href, title in all_series:
            if query_clean[:8] in title.lower():
                return _abs_url(href)
        return None

    # Busca normal
    blocks = re.findall(
        r'<div[^>]*class=["\'][^"\']*block-post[^"\']*["\'][^>]*>(.*?)</div>',
        body,
        re.S | re.I,
    )
    for block in blocks:
        a_match = re.search(r'<a[^>]*href=["\']([^"\']+)["\']', block)
        if a_match:
            return _abs_url(a_match.group(1))

    articles = re.findall(
        r'<article[^>]*class=["\'][^"\']*postEp[^"\']*["\'][^>]*>(.*?)</article>',
        body,
        re.S | re.I,
    )
    for art in articles:
        a_match = re.search(r'<a[^>]*href=["\']([^"\']+)["\']', art)
        if a_match:
            return _abs_url(a_match.group(1))

    return None


def get_series_page(url):
    status, body = _request(url)
    if status != 200:
        return None, None

    # Verifica redirecionamento para pagina da serie
    series_match = re.search(
        r'<div[^>]*class=["\'][^"\']*singleSeries[^"\']*["\'][^>]*>.*?'
        r'<div[^>]*class=["\'][^"\']*info[^"\']*["\'][^>]*>.*?'
        r'<h1[^>]*>.*?<a[^>]*href=["\']([^"\']+)["\']',
        body,
        re.S | re.I,
    )
    if series_match:
        series_url = _abs_url(series_match.group(1))
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

    # Extrai o link fullscreen-clickable com dados base64
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
            # Player React - retorna link direto (player externo pode suportar)
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

    query = tmdb_info.get("title") or imdb_id
    series_url = search_krmzy(query)
    if not series_url:
        return []

    episode_url = find_episode(series_url, season, episode)
    if not episode_url:
        return []

    return get_episode_streams(episode_url)
