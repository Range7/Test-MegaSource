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
"""

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = "MovieBox"
VERSION = "3.0.0"
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

MOVIEBOX_HOME = "https://themoviebox.xyz"

# Multiple API bases to try
API_BASES = [
    "https://h5-api.aoneroom.com/wefeed-h5api-bff",
    "https://h5.aoneroom.com/wefeed-h5-bff/web",
    "https://movieboxapp.in/wefeed-h5-bff/web",
    "https://moviebox.pk/wefeed-h5-bff/web",
]

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


def _request(url, method="GET", data=None, headers=None):
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": MOVIEBOX_HOME,
        "Referer": MOVIEBOX_HOME + "/",
        "X-Request-Lang": "en",
        "X-Client-Info": '{"timezone":"Asia/Dhaka"}',
        "X-Source": "playpage_share",
        "Sec-Ch-Ua": '"Chromium";v="121", "Not?A_Brand";v="24", "Google Chrome";v="121"',
        "Sec-Ch-Ua-Mobile": "?1",
        "Sec-Ch-Ua-Platform": '"Android"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
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


def _parse_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {}


def _unwrap(data):
    if isinstance(data, dict) and data.get("code") == 0 and data.get("message") == "ok":
        return data.get("data", {})
    return data


def _slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


def _imdb_to_tmdb(imdb_id):
    find_url = "https://api.themoviedb.org/3/find/" + urllib.parse.quote(imdb_id)
    query = urllib.parse.urlencode(
        {"api_key": TMDB_API_KEY, "external_source": "imdb_id"}
    )
    status, body = _request(find_url + "?" + query)
    if status != 200:
        return None
    data = _parse_json(body)
    if data.get("movie_results"):
        item = data["movie_results"][0]
        return {
            "type": "movie",
            "tmdb_id": item["id"],
            "title": item.get("title", ""),
            "year": (item.get("release_date") or "")[:4],
        }
    if data.get("tv_results"):
        item = data["tv_results"][0]
        return {
            "type": "tv",
            "tmdb_id": item["id"],
            "title": item.get("name", ""),
            "year": (item.get("first_air_date") or "")[:4],
        }
    return None


def _init_session():
    for base in API_BASES:
        if "h5api" in base:
            continue
        url = base.replace("/web", "") + "/app/get-latest-app-pkgs?app_name=moviebox"
        _request(url)
        break


def _search_h5api(keyword, subject_type):
    base = API_BASES[0]  # h5-api.aoneroom.com
    url = base + "/subject/search"
    payload = {
        "keyword": keyword,
        "page": 1,
        "perPage": 15,
        "subjectType": subject_type,
    }
    status, body = _request(url, method="POST", data=payload)
    if status != 200:
        return []
    data = _parse_json(body)
    # Try both wrapped and unwrapped
    items = []
    if isinstance(data, dict):
        if "items" in data:
            items = data["items"]
        elif "data" in data and isinstance(data["data"], dict) and "items" in data["data"]:
            items = data["data"]["items"]
    return items


def _search_webbff(keyword, subject_type):
    for base in API_BASES[1:]:
        url = base + "/subject/search"
        payload = {
            "keyword": keyword,
            "page": 1,
            "perPage": 15,
            "subjectType": subject_type,
        }
        status, body = _request(url, method="POST", data=payload)
        if status != 200:
            continue
        data = _parse_json(body)
        unwrapped = _unwrap(data)
        if isinstance(unwrapped, dict) and "items" in unwrapped:
            return unwrapped["items"]
        if isinstance(data, dict) and "items" in data:
            return data["items"]
    return []


def _try_detail(detail_path):
    base = API_BASES[0]
    url = f"{base}/detail?detailPath={urllib.parse.quote(detail_path, safe='')}"
    headers = {"Referer": f"{MOVIEBOX_HOME}/movies/{detail_path}"}
    status, body = _request(url, headers=headers)
    if status != 200:
        return None
    data = _parse_json(body)
    # Try multiple response formats
    subject = None
    if isinstance(data, dict):
        if "subject" in data:
            subject = data["subject"]
        elif "data" in data and isinstance(data["data"], dict):
            subject = data["data"].get("subject")
    if subject and subject.get("subjectId"):
        return {
            "subjectId": subject["subjectId"],
            "detailPath": subject.get("detailPath", detail_path),
            "title": subject.get("title", ""),
            "hasResource": subject.get("hasResource", False),
        }
    return None


def _find_by_title(title, year, subject_type):
    # Strategy 1: Search H5 API
    items = _search_h5api(title, subject_type)
    if items:
        for item in items:
            if not item.get("hasResource"):
                continue
            item_title = item.get("title", "").lower()
            if title.lower() in item_title or item_title in title.lower():
                return {
                    "subjectId": item["subjectId"],
                    "detailPath": item.get("detailPath", ""),
                    "title": item.get("title", ""),
                }
        for item in items:
            if item.get("hasResource"):
                return {
                    "subjectId": item["subjectId"],
                    "detailPath": item.get("detailPath", ""),
                    "title": item.get("title", ""),
                }

    # Strategy 2: Search Web BFF
    items = _search_webbff(title, subject_type)
    if items:
        for item in items:
            if not item.get("hasResource"):
                continue
            item_title = item.get("title", "").lower()
            if title.lower() in item_title or item_title in title.lower():
                return {
                    "subjectId": item["subjectId"],
                    "detailPath": item.get("detailPath", ""),
                    "title": item.get("title", ""),
                }
        for item in items:
            if item.get("hasResource"):
                return {
                    "subjectId": item["subjectId"],
                    "detailPath": item.get("detailPath", ""),
                    "title": item.get("title", ""),
                }

    # Strategy 3: Search with year appended
    if year:
        items = _search_h5api(f"{title} {year}", subject_type)
        if not items:
            items = _search_webbff(f"{title} {year}", subject_type)
        if items:
            for item in items:
                if item.get("hasResource"):
                    return {
                        "subjectId": item["subjectId"],
                        "detailPath": item.get("detailPath", ""),
                        "title": item.get("title", ""),
                    }

    # Strategy 4: Guess detail paths
    slug = _slugify(title)
    candidates = [slug]
    if year:
        candidates.append(f"{slug}-{year}")
    candidates.append(slug.replace("-", ""))
    for candidate in candidates:
        result = _try_detail(candidate)
        if result and result.get("hasResource"):
            return result

    return None


def _get_stream(subject_id, detail_path, se=0, ep=0):
    base = API_BASES[0]
    params = urllib.parse.urlencode({
        "subjectId": subject_id,
        "se": str(se),
        "ep": str(ep),
        "detailPath": detail_path,
        "streamSignType": "1",
    })
    url = f"{base}/subject/play?{params}"
    headers = {
        "Referer": f"{MOVIEBOX_HOME}/movies/{detail_path}",
        "X-Vip-Restrict": "0",
    }
    status, body = _request(url, headers=headers)
    if status != 200:
        return None, None
    data = _parse_json(body)
    # Try multiple response formats
    streams = []
    if isinstance(data, dict):
        if "streams" in data:
            streams = data["streams"]
        elif "data" in data and isinstance(data["data"], dict):
            streams = data["data"].get("streams", [])
    if not streams:
        return None, None

    def _res(s):
        try:
            return int((s.get("resolutions") or "0").split(",")[0])
        except Exception:
            return 0

    available = [s for s in streams if not s.get("vipLocked")]
    if not available:
        available = streams
    available.sort(key=_res, reverse=True)
    best = available[0]
    return best.get("url"), _res(best)


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

    found = _find_by_title(title, year, subject_type)
    if not found:
        return []

    subject_id = found["subjectId"]
    detail_path = found["detailPath"]

    se = 0 if media_type == "movie" else int(season or 1)
    ep = 0 if media_type == "movie" else int(episode or 1)

    stream_url, resolution = _get_stream(subject_id, detail_path, se, ep)
    if not stream_url:
        return []

    stream_title = f"MovieBox {resolution}p" if resolution and resolution > 0 else "MovieBox"

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
                        "Origin": MOVIEBOX_HOME,
                        "Referer": f"{MOVIEBOX_HOME}/movies/{detail_path}",
                    }
                },
            },
        }
    ]
