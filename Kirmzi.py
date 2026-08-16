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

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = "Krmzy"
VERSION = "1.0.0"
DESCRIPTION = "مسلسلات تركية وعربية مترجمة (krmzi.org)"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
TMDB_API_KEY = "92c1507cc18d85290e7a0b96abb37316"
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
    if data.get("movie_results"):
        item = data["movie_results"][0]
        return {"type": "movie", "tmdb_id": item["id"], "title": item.get("title")}
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
    urls_to_try = [
        f"{BASE_URL}/?s={encoded}",
        f"{BASE_URL}/search/{encoded}/",
    ]

    for url in urls_to_try:
        status, body = _request(url)
        if status != 200:
            continue

        # Procura div.block-post (resultados da busca)
        blocks = re.findall(
            r'<div[^>]*class=["\'][^"\']*block-post[^"\']*["\'][^>]*>(.*?)</div>',
            body,
            re.S | re.I,
        )
        for block in blocks:
            a_match = re.search(r'<a[^>]*href=["\']([^"\']+)["\']', block)
            if a_match:
                return _abs_url(a_match.group(1))

        # Fallback: procura qualquer article.postEp com link
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

    # Se houver redirecionamento para pagina da serie (igual ao Kotlin)
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

    # Extrai episodios: article.postEp
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

        # Numero do episodio: div.episodeNum span:last-child
        num_match = re.search(
            r'<div[^>]*class=["\'][^"\']*episodeNum[^"\']*["\'][^>]*>.*?'
            r'<span[^>]*>([^<]+)</span>',
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

    # Tenta encontrar pelo numero do episodio
    for ep in episodes:
        if ep["num"] == episode:
            return ep["url"]

    # Fallback: pelo indice (1-based)
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


def unpack_js(page_text):
    eval_match = re.search(
        r'eval\s*\(\s*function\s*\(.*?}\s*\((.*)\)\s*\)',
        page_text,
        re.S,
    )
    if not eval_match:
        return None

    params_string = eval_match.group(1)

    params_match = re.search(
        r"['\"](.*?)['\"]\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*['\"](.*?)['\"]\.split\s*\(\s*['\"]\|['\"]\s*\)",
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

    file_match = re.search(r'["\']?file["\']?\s*:\s*["\']([^"\']+)["\']', deobfuscated)
    if not file_match:
        return None

    return file_match.group(1).replace("\\/", "/")


def extract_custom_stream(embed_url):
    referers = [BASE_URL + "/", "https://newaat.com/", "https://qesen.net/"]

    page_text = None
    for ref in referers:
        status, text = _request(embed_url, headers={"Referer": ref})
        if status == 200 and "eval(function" in text:
            page_text = text
            break

    if not page_text:
        return None

    return unpack_js(page_text)


def check_working_referer(stream_url, embed_url):
    try:
        parsed = urllib.parse.urlparse(embed_url)
        iframe_host = f"{parsed.scheme}://{parsed.host}/"
    except Exception:
        iframe_host = "https://qesen.net/"

    candidates = [iframe_host, "https://qesen.net/", "https://newaat.com/"]

    for ref in candidates:
        try:
            req = urllib.request.Request(
                stream_url,
                headers={"User-Agent": USER_AGENT, "Referer": ref},
                method="HEAD",
            )
            with _opener.open(req, timeout=10) as resp:
                if resp.status == 200:
                    return ref
        except Exception:
            continue

    return iframe_host


def _ensure_http(u):
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    return "https://" + u


def _dailymotion_from_li(li_html):
    a_match = re.search(r'<code[^>]*>.*?<a[^>]*href=["\']([^"\']+)["\']', li_html, re.S)
    if a_match:
        return a_match.group(1)
    code_match = re.search(r'<code[^>]*>([^<]+)</code>', li_html, re.S)
    if code_match:
        txt = code_match.group(1).strip()
        if txt:
            return txt
    return None


def get_episode_streams(episode_url):
    status, body = _request(episode_url)
    if status != 200:
        return []

    # Extrai link do extractor (iframe/embed)
    extractor_match = re.search(
        r'<a[^>]*class=["\'][^"\']*fullscreen-clickable[^"\']*["\'][^>]*href=["\']([^"\']+)["\']',
        body,
        re.S | re.I,
    )
    if not extractor_match:
        return []
    extractor_url = _abs_url(extractor_match.group(1))

    # Se for link direto m3u8/mp4
    if extractor_url.lower().endswith((".m3u8", ".mp4")):
        return [_make_stream(extractor_url, "Direct", BASE_URL + "/")]

    # Carrega pagina do extractor
    status2, body2 = _request(extractor_url, headers={"Referer": episode_url})
    if status2 != 200:
        return []

    # Extrai lista de servidores
    server_items = re.findall(
        r'<li[^>]*data-server=["\']([^"\']*)["\'][^>]*data-name=["\']([^"\']*)["\'][^>]*>(.*?)</li>',
        body2,
        re.S | re.I,
    )

    # Fallback: outras formas de li.serversList
    if not server_items:
        server_items = re.findall(
            r'<li[^>]*data-server-id=["\']([^"\']*)["\'][^>]*data-type=["\']([^"\']*)["\'][^>]*>(.*?)</li>',
            body2,
            re.S | re.I,
        )

    streams = []

    for server_id_raw, server_type_raw, li_html in server_items:
        server_type = server_type_raw.lower().strip()
        server_id = server_id_raw.strip()

        embed_url = None

        if server_type == "youtube":
            embed_url = f"https://www.youtube.com/watch?v={server_id}"
        elif server_type == "youtube_in":
            embed_url = f"https://www.youtube.com/embed/{server_id}"
        elif server_type == "express":
            embed_url = server_id if server_id else None
        elif server_type == "dailymotion":
            embed_url = _dailymotion_from_li(li_html)
        elif server_type == "facebook":
            embed_url = f"https://app.videas.fr/embed/media/{server_id}"
        elif server_type == "estream":
            embed_url = f"https://arabveturk.com/embed-{server_id}.html"
        elif server_type in ("arab hd", "arabhd", "arab-hd"):
            embed_url = f"https://v.turkvearab.com/embed-{server_id}.html"
        elif server_type == "box":
            embed_url = f"https://youdboox.com/embed-{server_id}.html"
        elif server_type == "now":
            embed_url = f"https://extreamnow.org/embed-{server_id}.html"
        elif server_type == "ok":
            embed_url = _ensure_http(f"//ok.ru/videoembed/{server_id}")
        elif server_type in ("red hd", "redhd", "red-hd"):
            embed_url = f"https://iplayerhls.com/e/{server_id}"
        elif server_type in ("pro hd", "prohd", "pro-hd"):
            embed_url = f"https://ebtv.upns.live/#{server_id}"
        elif server_type == "pro":
            embed_url = f"https://mdna.upns.online/#{server_id}"
        else:
            # Fallbacks
            fallback_href = re.search(r'<a[^>]*href=["\']([^"\']+)["\']', li_html)
            fallback_data = re.search(r'data-src=["\']([^"\']+)["\']', li_html)
            if fallback_href:
                embed_url = _abs_url(fallback_href.group(1))
            elif fallback_data:
                embed_url = _abs_url(fallback_data.group(1))

        if not embed_url:
            continue

        # Servidores customizados que precisam de unpacking
        if server_type in ("arab hd", "arabhd", "arab-hd", "estream"):
            extracted = extract_custom_stream(embed_url)
            if extracted:
                working_ref = check_working_referer(extracted, embed_url)
                streams.append(
                    _make_stream(
                        extracted,
                        server_type_raw,
                        working_ref,
                        origin=working_ref.rstrip("/"),
                    )
                )
        elif server_type == "youtube":
            streams.append(_make_stream(embed_url, "YouTube", BASE_URL + "/"))
        else:
            # Outros: retorna link direto para o player/embed
            streams.append(_make_stream(embed_url, server_type_raw, BASE_URL + "/"))

    return streams


def _make_stream(url, title, referer, origin=None):
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": referer,
    }
    if origin:
        headers["Origin"] = origin

    return {
        "name": TITLE,
        "title": title,
        "url": url,
        "behaviorHints": {
            "notMyMetadata": True,
            "proxyHeaders": {
                "request": headers,
            },
        },
    }


def get_streams(media_type, media_id, config=None):
    # Krmzy tem apenas series, mas mantemos compatibilidade
    if media_type == "movie":
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

    # Converte IMDB para TMDB para obter titulo
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
