"""
MovieBoxHD Scraper for MegaSource
==================================
Protocol:
  TITLE, VERSION, DESCRIPTION
  get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id   : "tt0111161" (movie) | "tt0944947:1:1" (series:season:episode)

Features:
  - Movies & TV Series support
  - Auto cookie/session initialization
  - All qualities extraction (360p, 480p, 720p, 1080p)
  - Subscription bypass via free stream endpoints
  - Highest quality prioritized
  - Uses only Python standard library (urllib + cookiejar)

Backend: aoneroom.com (h5.aoneroom.com)
"""

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = "MovieBoxHD"
VERSION = "2.1.0"
DESCRIPTION = "MovieBox HD - Movies & Series - All Qualities (360p to 1080p)"

# API Configuration
API_HOST = "h5.aoneroom.com"
API_PROTOCOL = "https"
BASE_URL = f"{API_PROTOCOL}://{API_HOST}"

# Endpoints
APP_INFO_PATH = "/wefeed-h5-bff/web/app_info"
SEARCH_PATH = "/wefeed-h5-bff/web/subject/search"
STREAM_PATH = "/wefeed-h5-bff/web/subject/play"
DOWNLOAD_PATH = "/wefeed-h5-bff/web/subject/download"
DETAIL_PATH = "/movies"

# TMDB
TMDB_API_KEY = "9801b6b0548ad57581d111ea690c85c8"
TMDB_BASE = "https://api.themoviedb.org/3"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": BASE_URL,
    "Referer": BASE_URL + "/",
    "Connection": "keep-alive",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))
_cookies_initialized = False


# ============================================================
# HTTP Helpers
# ============================================================

def _request(url, method="GET", headers=None, data=None, timeout=20):
    request_headers = dict(DEFAULT_HEADERS)
    if headers:
        request_headers.update(headers)

    body = None
    if method == "POST" and data is not None:
        if isinstance(data, dict):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        else:
            body = data

    try:
        req = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        with _opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except Exception:
            return exc.code, ""
    except Exception:
        return 0, ""


def _json_request(url, method="GET", headers=None, data=None, timeout=20):
    status, text = _request(url, method, headers, data, timeout)
    if status < 200 or status > 299:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict) and parsed.get("code") == 0 and parsed.get("message") == "ok" and "data" in parsed:
            return parsed["data"]
        return parsed
    except Exception:
        return None


# ============================================================
# Session / Cookie Initialization
# ============================================================

def _ensure_session():
    global _cookies_initialized
    if _cookies_initialized:
        return True
    url = f"{BASE_URL}{APP_INFO_PATH}?app_name=moviebox"
    status, _ = _request(url, headers={"Referer": BASE_URL + "/"})
    _cookies_initialized = True
    return status == 200


# ============================================================
# TMDB Helpers (IMDB -> Title)
# ============================================================

def imdb_to_tmdb_info(imdb_id, media_type):
    url = (
        f"{TMDB_BASE}/find/{urllib.parse.quote(imdb_id)}"
        f"?api_key={TMDB_API_KEY}&external_source=imdb_id"
    )
    data = _json_request(url)
    if not isinstance(data, dict):
        return None

    if media_type == "movie":
        results = data.get("movie_results") or []
        if results:
            return {
                "type": "movie",
                "tmdb_id": results[0].get("id"),
                "title": results[0].get("title") or results[0].get("original_title", ""),
                "year": (results[0].get("release_date") or "")[:4]
            }
        results = data.get("tv_results") or []
        if results:
            return {
                "type": "tv",
                "tmdb_id": results[0].get("id"),
                "title": results[0].get("name") or results[0].get("original_name", ""),
                "year": (results[0].get("first_air_date") or "")[:4]
            }
    else:
        results = data.get("tv_results") or []
        if results:
            return {
                "type": "tv",
                "tmdb_id": results[0].get("id"),
                "title": results[0].get("name") or results[0].get("original_name", ""),
                "year": (results[0].get("first_air_date") or "")[:4]
            }
        results = data.get("movie_results") or []
        if results:
            return {
                "type": "movie",
                "tmdb_id": results[0].get("id"),
                "title": results[0].get("title") or results[0].get("original_title", ""),
                "year": (results[0].get("release_date") or "")[:4]
            }
    return None


# ============================================================
# MovieBox Search -> Detail Path
# ============================================================

def search_moviebox(title, year="", media_type="movie"):
    _ensure_session()

    subject_type_map = {"movie": "movie", "series": "tv"}
    subject_type = subject_type_map.get(media_type, "")

    search_params = {
        "keyword": title,
        "page": 1,
        "pageSize": 30,
    }
    if subject_type:
        search_params["subject_type"] = subject_type

    url = f"{BASE_URL}{SEARCH_PATH}?{urllib.parse.urlencode(search_params)}"
    data = _json_request(url, headers={"Referer": BASE_URL + "/"})

    if not isinstance(data, dict):
        return []

    results = data.get("list") or data.get("results") or []
    if not isinstance(results, list):
        return []

    normalized = []
    for item in results:
        if not isinstance(item, dict):
            continue
        item_title = item.get("title") or item.get("name") or ""
        item_year = str(item.get("year") or item.get("releaseYear") or "")
        detail_path = item.get("detailPath") or item.get("detail_path") or ""
        subject_id = item.get("subjectId") or item.get("subject_id") or ""

        if not detail_path and subject_id:
            detail_path = str(subject_id)

        item_type = item.get("subjectType") or item.get("subject_type") or "movie"

        # Filter by year if provided
        if year and item_year and year != item_year:
            continue

        normalized.append({
            "title": item_title,
            "year": item_year,
            "detailPath": detail_path,
            "subjectId": subject_id,
            "type": item_type
        })

    return normalized


def extract_nuxt_state(html):
    nuxt_pattern = r'window\.__NUXT__\s*=\s*(\{.*?\});\s*</script>'
    match = re.search(nuxt_pattern, html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    state_pattern = r'window\.__NUXT_STATE__\s*=\s*(\{.*?\});'
    match = re.search(state_pattern, html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    data_pattern = r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>'
    match = re.search(data_pattern, html, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    return None


def get_subject_id_from_detail(detail_path):
    _ensure_session()

    if not detail_path.startswith("/"):
        detail_path = "/" + detail_path

    url = f"{BASE_URL}{DETAIL_PATH}{detail_path}"
    status, html = _request(url, headers={
        "Accept": "text/html,application/xhtml+xml",
        "Referer": BASE_URL + "/"
    })

    if status != 200 or not html:
        return None

    nuxt = extract_nuxt_state(html)
    if nuxt:
        try:
            res_data = nuxt.get("resData") or nuxt.get("state", {}).get("resData")
            if isinstance(res_data, dict):
                subject = res_data.get("subject") or res_data.get("data", {}).get("subject")
                if isinstance(subject, dict):
                    return subject.get("subjectId")
        except Exception:
            pass

    sid_match = re.search(r'"subjectId"\s*:\s*"(\d+)"', html)
    if sid_match:
        return sid_match.group(1)

    return None


# ============================================================
# Stream Extraction (All Qualities)
# ============================================================

def fetch_all_streams(subject_id, season=0, episode=0):
    _ensure_session()

    search_params = {
        "subjectId": subject_id,
        "se": season,
        "ep": episode
    }

    stream_url = f"{BASE_URL}{STREAM_PATH}?{urllib.parse.urlencode(search_params)}"
    headers = {"Referer": f"{BASE_URL}/movies/{subject_id}"}

    data = _json_request(stream_url, headers=headers)
    if not isinstance(data, dict):
        return []

    streams = data.get("streams") or []
    if not isinstance(streams, list):
        return []

    results = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue

        url = stream.get("url") or ""
        if not url:
            continue

        resolution = stream.get("resolutions") or stream.get("resolution") or 0
        try:
            resolution = int(resolution)
        except (ValueError, TypeError):
            resolution = 0

        size = stream.get("size") or 0
        duration = stream.get("duration") or 0
        fmt = stream.get("format") or "mp4"
        codec = stream.get("codecName") or stream.get("codec") or "h264"
        quality_label = f"{resolution}p" if resolution else "Auto"

        results.append({
            "url": url,
            "resolution": resolution,
            "quality": quality_label,
            "size": size,
            "duration": duration,
            "format": fmt,
            "codec": codec
        })

    results.sort(key=lambda x: x["resolution"])
    return results


def fetch_download_options(subject_id, season=0, episode=0):
    _ensure_session()

    search_params = {
        "subjectId": subject_id,
        "se": season,
        "ep": episode
    }

    download_url = f"{BASE_URL}{DOWNLOAD_PATH}?{urllib.parse.urlencode(search_params)}"
    headers = {"Referer": f"{BASE_URL}/movies/{subject_id}"}

    data = _json_request(download_url, headers=headers)
    if not isinstance(data, dict):
        return []

    files = data.get("files") or data.get("streams") or []
    if not isinstance(files, list):
        return []

    results = []
    for f in files:
        if not isinstance(f, dict):
            continue

        url = f.get("url") or ""
        if not url:
            continue

        resolution = f.get("resolutions") or f.get("resolution") or 0
        try:
            resolution = int(resolution)
        except (ValueError, TypeError):
            resolution = 0

        quality_label = f"{resolution}p" if resolution else "Auto"

        results.append({
            "url": url,
            "resolution": resolution,
            "quality": quality_label,
            "size": f.get("size", 0),
            "duration": f.get("duration", 0),
            "format": f.get("format", "mp4"),
            "codec": f.get("codecName", "h264")
        })

    results.sort(key=lambda x: x["resolution"])
    return results


# ============================================================
# Main Entry Point
# ============================================================

def get_streams(media_type, media_id, config=None):
    imdb_id = media_id
    season = 0
    episode = 0

    if ":" in media_id:
        parts = media_id.split(":", 2)
        imdb_id = parts[0]
        if len(parts) > 1:
            try:
                season = int(parts[1])
            except ValueError:
                season = 0
        if len(parts) > 2:
            try:
                episode = int(parts[2])
            except ValueError:
                episode = 0

    if not imdb_id.lower().startswith("tt"):
        return []

    tmdb_info = imdb_to_tmdb_info(imdb_id, media_type)
    if not tmdb_info:
        return []

    title = tmdb_info["title"]
    year = tmdb_info.get("year", "")

    search_results = search_moviebox(title, year, media_type)
    if not search_results:
        return []

    best_match = None
    for result in search_results:
        result_title = result.get("title", "").lower()
        if title.lower() in result_title or result_title in title.lower():
            best_match = result
            break

    if not best_match:
        best_match = search_results[0]

    detail_path = best_match.get("detailPath", "")
    subject_id = best_match.get("subjectId", "")

    if not subject_id and detail_path:
        subject_id = get_subject_id_from_detail(detail_path)

    if not subject_id:
        return []

    all_streams = []
    play_streams = fetch_all_streams(subject_id, season, episode)
    all_streams.extend(play_streams)

    download_streams = fetch_download_options(subject_id, season, episode)
    all_streams.extend(download_streams)

    if not all_streams:
        return []

    seen_urls = set()
    unique_streams = []
    for s in all_streams:
        if s["url"] not in seen_urls:
            seen_urls.add(s["url"])
            unique_streams.append(s)

    unique_streams.sort(key=lambda x: x["resolution"], reverse=True)

    output = []
    for stream in unique_streams:
        quality = stream["quality"]
        resolution = stream["resolution"]

        title_str = f"[{quality}] MovieBoxHD"
        if stream.get("codec"):
            title_str += f" ({stream['codec']})"

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": BASE_URL + "/",
            "Origin": BASE_URL,
        }

        item = {
            "name": TITLE,
            "title": title_str,
            "url": stream["url"],
            "behaviorHints": {
                "notMyMetadata": True,
                "proxyHeaders": {
                    "request": headers
                }
            }
        }

        if resolution >= 1080:
            item["behaviorHints"]["videoQuality"] = "1080p"
        elif resolution >= 720:
            item["behaviorHints"]["videoQuality"] = "720p"
        elif resolution >= 480:
            item["behaviorHints"]["videoQuality"] = "480p"
        else:
            item["behaviorHints"]["videoQuality"] = "360p"

        output.append(item)

    return output
