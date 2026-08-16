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
VERSION = "2.5.0"
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


def search_krmzy(query):
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

    if status == 200 and "نقوم حالياً بتحديث مكتبتنا" not in body and "تحديث مكتبتنا" not in body:
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


def extract_okru(video_id):
    """Tenta extrair video do OK.ru embed. Retorna None se falhar."""
    url = f"https://ok.ru/videoembed/{video_id}"
    status, html = _request(url, headers={"Referer": BASE_URL + "/"})
    if status != 200:
        return None

    opts_match = re.search(r'data-options="([^"]+)"', html)
    if opts_match:
        opts_str = opts_match.group(1)
        opts_str = opts_str.replace('&quot;', '"').replace('&amp;', '&').replace('&#x3D;', '=')
        try:
            opts_json = json.loads(opts_str)
            flashvars = opts_json.get("flashvars", {})
            metadata_str = flashvars.get("metadata", "{}")
            if isinstance(metadata_str, str):
                metadata = json.loads(metadata_str)
            else:
                metadata = metadata_str
            videos = metadata.get("videos", [])
            if videos:
                def quality_key(v):
                    name = v.get("name", "0")
                    return int(name.replace("p", "").replace("P", ""))
                best = max(videos, key=quality_key)
                return best.get("url")
        except Exception:
            pass

    urls = re.findall(r'https?://[^\s"<>]+\.(?:m3u8|mp4)[^\s"<>]*', html)
    if urls:
        return urls[0]

    return None


def extract_mailru(public_url):
    """Tenta extrair video do Cloud Mail.ru. Retorna None se falhar."""
    status, html = _request(public_url, headers={"Referer": BASE_URL + "/"})
    if status != 200:
        return None

    wlg = re.search(r'"weblink_get".*?\[.*?\{.*?"url":"([^"]+)"', html, re.S)
    if wlg:
        return wlg.group(1).replace("\\/", "/")

    config = re.search(r'window\.__config__\s*=\s*({.*?});', html, re.S)
    if config:
        try:
            cfg = json.loads(config.group(1))
            weblinks = cfg.get("weblink_get", [])
            if weblinks:
                return weblinks[0].get("url")
        except Exception:
            pass

    parsed = urllib.parse.urlparse(public_url)
    path = parsed.path.strip("/")
    if path.startswith("public/"):
        key = path.replace("public/", "")
        api_url = f"https://cloud.mail.ru/api/v2/file?weblink={key}"
        s, body = _request(api_url)
        if s == 200:
            try:
                data = json.loads(body)
                return data.get("body", {}).get("weblink")
            except Exception:
                pass

    vids = re.findall(r'https?://[^\s"<>]+\.mp4[^\s"<>]*', html)
    if vids:
        return vids[0]

    return None


def parse_m3u8_max_quality(m3u8_url, referer):
    """Analisa master.m3u8 e retorna APENAS a maior qualidade."""
    try:
        req = urllib.request.Request(
            m3u8_url,
            headers={"User-Agent": USER_AGENT, "Referer": referer},
        )
        with _opener.open(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return None, None, 0

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

    return best_name, best_url, best_bandwidth


def _ensure_http(u):
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("http"):
        return u
    return "https://" + u


def _quality_from_name(name):
    name_lower = name.lower()
    if "1080" in name_lower or "fhd" in name_lower:
        return "1080p"
    elif "720" in name_lower or "hd" in name_lower:
        return "720p"
    elif "480" in name_lower:
        return "480p"
    elif "360" in name_lower:
        return "360p"
    return "HD"


def _quality_rank(title):
    """Retorna rank numerico da qualidade para ordenacao (maior = melhor)."""
    t = title.lower()
    if "1080" in t:
        return 1080
    elif "720" in t:
        return 720
    elif "480" in t:
        return 480
    elif "360" in t:
        return 360
    elif "240" in t:
        return 240
    elif "hd" in t:
        return 720
    return 0


def get_episode_streams(episode_url):
    status, body = _request(episode_url)
    if status != 200:
        return []

    fs_match = re.search(
        r'<a[^>]*href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*fullscreen-clickable[^"\']*["\']',
        body,
        re.S | re.I,
    )
    if not fs_match:
        fs_match = re.search(
            r'<a[^>]*class=["\'][^"\']*fullscreen-clickable[^"\']*["\'][^>]*href=["\']([^"\']+)["\']',
            body,
            re.S | re.I,
        )
    if not fs_match:
        return []

    fs_href = fs_match.group(1)

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

        stream_url = None
        server_title = server.get("name", "Unknown")
        is_m3u8 = False
        referer = BASE_URL + "/"
        quality_name = _quality_from_name(server_title)

        if name in ("arab hd", "arabhd", "arab-hd"):
            embed_url = f"https://v.turkvearab.com/embed-{sid}.html"
            s, html = _request(embed_url, headers={"Referer": episode_url})
            if s == 200:
                stream_url = unpack_js(html)
                if stream_url:
                    is_m3u8 = stream_url.endswith(".m3u8")
                    referer = "https://v.turkvearab.com/"

        elif name == "estream":
            embed_url = f"https://arabveturk.com/embed-{sid}.html"
            s, html = _request(embed_url, headers={"Referer": episode_url})
            if s == 200:
                stream_url = unpack_js(html)
                if stream_url:
                    is_m3u8 = stream_url.endswith(".m3u8")
                    referer = "https://arabveturk.com/"

        elif name == "express":
            if sid.startswith("http"):
                # Se ja for URL direta (m3u8, mp4, ou public link)
                if sid.endswith(".m3u8") or sid.endswith(".mp4") or ".m3u8" in sid:
                    # URL direta de video
                    stream_url = sid
                    is_m3u8 = sid.endswith(".m3u8") or ".m3u8" in sid
                elif "cloud.mail.ru" in sid or "mail.ru" in sid:
                    # Public folder link - tenta extrair
                    extracted = extract_mailru(sid)
                    if extracted:
                        stream_url = extracted
                        is_m3u8 = extracted.endswith(".m3u8")
                    else:
                        # Fallback: retorna URL publica diretamente
                        # O player do dispositivo pode lidar com ela
                        stream_url = sid
                else:
                    stream_url = sid
            else:
                stream_url = _ensure_http(sid)

        elif name == "ok":
            if sid.isdigit():
                # ID numerico - tenta extrair do embed
                extracted = extract_okru(sid)
                if extracted:
                    stream_url = extracted
                    referer = "https://ok.ru/"
                else:
                    # Fallback: retorna embed URL diretamente
                    stream_url = f"https://ok.ru/videoembed/{sid}"
                    referer = "https://ok.ru/"
            elif sid.startswith("http"):
                # URL direta
                stream_url = sid
                referer = "https://ok.ru/"
            else:
                stream_url = f"https://ok.ru/videoembed/{sid}"
                referer = "https://ok.ru/"

        elif name in ("pro hd", "prohd", "pro-hd"):
            # Player React - retorna embed direto
            stream_url = f"https://ebtv.upns.live/#{sid}"
            referer = "https://ebtv.upns.live/"
            quality_name = "HD"

        elif name in ("red hd", "redhd", "red-hd"):
            embed_url = f"https://iplayerhls.com/e/{sid}"
            s, html = _request(embed_url, headers={"Referer": episode_url})
            if s == 200:
                stream_url = unpack_js(html)
                if stream_url:
                    is_m3u8 = stream_url.endswith(".m3u8")
                    referer = "https://iplayerhls.com/"

        if not stream_url:
            continue

        # Extrai apenas a MAIOR qualidade para m3u8
        if is_m3u8:
            q_name, q_url, bw = parse_m3u8_max_quality(stream_url, referer)
            if q_url:
                stream_url = q_url
                quality_name = q_name
                server_title = f"{server_title} - {q_name}"
            else:
                server_title = f"{server_title} - {quality_name}"
        else:
            server_title = f"{server_title} - {quality_name}"

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": referer,
        }
        if referer != BASE_URL + "/":
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

    # ORDENA por qualidade: maior primeiro
    streams.sort(key=lambda s: _quality_rank(s["title"]), reverse=True)

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

    series_url = search_krmzy(tmdb_info)
    if not series_url:
        return []

    episode_url = find_episode(series_url, season, episode)
    if not episode_url:
        return []

    return get_episode_streams(episode_url)
