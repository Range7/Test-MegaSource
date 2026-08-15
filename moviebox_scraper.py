"""
MovieBox Scraper for MegaSource
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
import urllib.error
import urllib.parse
import urllib.request

TITLE = "MovieBox"
VERSION = "1.0.0"
DESCRIPTION = "Movies & Series from themoviebox.xyz"

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36"
)
TMDB_API_KEY = (
    "\x39\x32\x63\x31\x35\x30\x37\x63\x63\x31\x38\x64\x38\x35"
    "\x32\x39\x30\x65\x37\x61\x30\x62\x39\x36\x61\x62\x62\x33"
    "\x37\x33\x31\x36"
)

BASE_URL = "https://h5.aoneroom.com"
API_BASE = BASE_URL + "/wefeed-h5-bff/web"

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


def _request(url, method="GET", data=None, headers=None):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://themoviebox.xyz",
        "Referer": "https://themoviebox.xyz/",
        "X-Request-Lang": "en",
        "X-Client-Info": '{"timezone":"Asia/Dhaka"}',
        "X-Source": "playpage_share",
    }
    if headers:
        request_headers.update(headers)

    body = None
    if method == "POST" and data is not None:
        body = json.dumps(data).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with _opener.open(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception:
        return 0, ""


def _unwrap(response_text):
    try:
        data = json.loads(response_text)
        if (
            isinstance(data, dict)
            and data.get("code") == 0
            and data.get("message") == "ok"
        ):
            return data.get("data", {})
        return data
    except (ValueError, TypeError):
        return {}


def _init_session():
    url = BASE_URL + "/wefeed-h5-bff/app/get-latest-app-pkgs?app_name=moviebox"
    _request(url)


def _imdb_to_tmdb(imdb_id):
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

    if data.get("movie_results"):
        item = data["movie_results"][0]
        return {
            "type": "movie",
            "tmdb_id": item["id"],
            "title": item.get("title"),
            "year": (item.get("release_date") or "")[:4],
        }
    if data.get("tv_results"):
        item = data["tv_results"][0]
        return {
            "type": "tv",
            "tmdb_id": item["id"],
            "title": item.get("name"),
            "year": (item.get("first_air_date") or "")[:4],
        }
    return None


def _search_moviebox(query, subject_type=0):
    url = API_BASE + "/subject/search"
    payload = {
        "keyword": query,
        "page": 1,
        "perPage": 10,
        "subjectType": subject_type,
    }
    status, body = _request(url, method="POST", data=payload)
    if status != 200:
        return []
    data = _unwrap(body)
    return data.get("items", [])


def _extract_slug(detail_path):
    parts = detail_path.strip("/").split("/")
    return parts[-1] if parts else detail_path


def _get_stream(subject_id, detail_path, se=0, ep=0):
    params = urllib.parse.urlencode({
        "subjectId": subject_id,
        "se": str(se),
        "ep": str(ep),
    })
    url = API_BASE + "/subject/play?" + params
    slug = _extract_slug(detail_path)
    headers = {"Referer": "https://themoviebox.xyz/movies/" + slug}
    status, body = _request(url, headers=headers)
    if status != 200:
        return None, None
    data = _unwrap(body)
    streams = data.get("streams", [])
    if not streams:
        return None, None

    def _get_res(s):
        try:
            return int((s.get("resolutions") or "0").split(",")[0])
        except Exception:
            return 0

    streams.sort(key=_get_res, reverse=True)
    best = streams[0]
    return best.get("url"), _get_res(best)


def get_streams(media_type, media_id, config=None):
    _init_session()

    imdb_id = media_id
    season = episode = None
    if ":" in media_id:
        parts = media_id.split(":", 2)
        imdb_id, season, episode = parts[0], parts[1], parts[2]

    tmdb_info = _imdb_to_tmdb(imdb_id)
    if not tmdb_info or not tmdb_info.get("title"):
        return []

    title = tmdb_info["title"]
    year = tmdb_info.get("year")

    subject_type = 1 if media_type == "movie" else 2
    results = _search_moviebox(title, subject_type)

    if not results:
        return []

    best_match = None
    for item in results:
        if not item.get("hasResource"):
            continue
        item_title = item.get("title", "")
        if title.lower() in item_title.lower() or item_title.lower() in title.lower():
            best_match = item
            break

    if not best_match:
        for item in results:
            if item.get("hasResource"):
                best_match = item
                break

    if not best_match:
        return []

    subject_id = best_match.get("subjectId")
    detail_path = best_match.get("detailPath")

    if not subject_id or not detail_path:
        return []

    se = 0 if media_type == "movie" else int(season or 1)
    ep = 0 if media_type == "movie" else int(episode or 1)

    stream_url, resolution = _get_stream(subject_id, detail_path, se, ep)
    if not stream_url:
        return []

    stream_title = "MovieBox"
    if resolution and resolution > 0:
        stream_title = f"MovieBox {resolution}p"

    slug = _extract_slug(detail_path)
    return [
        {
            "name": TITLE,
            "title": stream_title,
            "url": stream_url,
            "behaviorHints": {
                "notMyMetadata": True,
                "proxyHeaders": {
                    "request": {
                        "User-Agent": USER_AGENT,
                        "Origin": "https://themoviebox.xyz",
                        "Referer": "https://themoviebox.xyz/movies/" + slug,
                    }
                },
            },
        }
    ]
