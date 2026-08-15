"""
CEE Buzz Scraper for MegaSource
================================
Protocol:
  TITLE, VERSION, DESCRIPTION
  get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id   : "tt0111161" (movie) | "tt0944947:1:1" (series:season:episode)

Features:
  - Movies & TV Series support
  - Direct CDN MP4 extraction from cee.buzz video pages
  - UUID-based stream URL pattern matching
  - Uses only Python standard library (urllib + cookiejar)

Site: https://cee.buzz
Video Page: https://cee.buzz/video/ar/{id}?show=true
CDN Pattern: https://cdn.cee.buzz/vascin24-mp4/{UUID}_video.mp4
"""

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = "CEE Buzz"
VERSION = "2.0.0"
DESCRIPTION = "CEE Buzz Arabic Movies & Series - Iraq"

BASE_URL = "https://cee.buzz"
CDN_BASE = "https://cdn.cee.buzz"

TMDB_API_KEY = "9801b6b0548ad57581d111ea690c85c8"
TMDB_BASE = "https://api.themoviedb.org/3"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


# ============================================================
# HTTP Helpers
# ============================================================

def _request(url, method="GET", headers=None, data=None, timeout=25):
    request_headers = dict(DEFAULT_HEADERS)
    if headers:
        request_headers.update(headers)

    body = None
    if method == "POST" and data is not None:
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
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
    except Exception as e:
        return 0, str(e)


def _json_request(url, method="GET", headers=None, data=None, timeout=25):
    status, text = _request(url, method, headers, data, timeout)
    if status < 200 or status > 299:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


# ============================================================
# TMDB Helpers
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
# CEE Buzz Search
# ============================================================

def search_cee_buzz(query):
    """
    Search CEE Buzz for a title.
    Returns list of dicts: [{"title": ..., "id": ..., "url": ...}]
    """
    search_url = f"{BASE_URL}/search?q={urllib.parse.quote(query)}"
    status, html = _request(search_url)
    if status != 200 or not html:
        return []

    results = []

    # Pattern 1: /video/ar/5820?show=true
    video_pattern = r'href=["\']([^"\']*/video/(?:ar|en)/(\d+)(?:\?[^"\']*)?)["\'][^>]*>([^<]{3,})<'
    matches = re.findall(video_pattern, html, re.IGNORECASE)
    for match in matches:
        link, vid_id, title = match
        if not link.startswith("http"):
            link = BASE_URL + link
        title = re.sub(r'<[^>]+>', '', title).strip()
        if title and vid_id:
            results.append({"title": title, "id": vid_id, "url": link})

    # Pattern 2: data-id attributes
    data_pattern = r'data-id=["\'](\d+)["\'][^>]*>.*?<a[^>]+href=["\']([^"\']*video[^"\']*)["\'][^>]*>([^<]{3,})<'
    matches = re.findall(data_pattern, html, re.IGNORECASE | re.DOTALL)
    for match in matches:
        vid_id, link, title = match
        if not link.startswith("http"):
            link = BASE_URL + link
        title = re.sub(r'<[^>]+>', '', title).strip()
        if title and vid_id and not any(r["id"] == vid_id for r in results):
            results.append({"title": title, "id": vid_id, "url": link})

    # Pattern 3: generic video links
    link_pattern = r'href=["\']([^"\']*/(?:video|watch|movie|film)[^"\']*\d+[^"\']*)["\'][^>]*>([^<]{3,})<'
    matches = re.findall(link_pattern, html, re.IGNORECASE)
    for match in matches:
        link, title = match
        if not link.startswith("http"):
            link = BASE_URL + link
        title = re.sub(r'<[^>]+>', '', title).strip()
        id_match = re.search(r'/(\d+)(?:\?|$)', link)
        vid_id = id_match.group(1) if id_match else ""
        if title and vid_id and not any(r["id"] == vid_id for r in results):
            results.append({"title": title, "id": vid_id, "url": link})

    return results


# ============================================================
# Stream Extraction from Video Page
# ============================================================

def extract_streams(video_id, media_type="movie", season=None, episode=None):
    """
    Fetch video page and extract CDN stream URLs.
    Returns list of dicts: [{"url": ..., "quality": ..., "resolution": ...}]
    """
    # Build video page URL
    if media_type == "series" and season and episode:
        video_url = f"{BASE_URL}/video/ar/{video_id}?show=true&season={season}&episode={episode}"
    else:
        video_url = f"{BASE_URL}/video/ar/{video_id}?show=true"

    status, html = _request(video_url)
    if status != 200 or not html:
        return []

    streams = []

    # Pattern 1: Direct CDN MP4 URLs (cee.buzz pattern)
    # Example: https://cdn.cee.buzz/vascin24-mp4/C0C30791-6712-C5BE-2D46-F95E5FB7C8A3_video.mp4
    cdn_pattern = r'(https?://cdn\.cee\.buzz/vascin24-mp4/[A-F0-9-]+_video\.mp4[^"\'\s<>]*)'
    for match in re.findall(cdn_pattern, html, re.IGNORECASE):
        quality = "Auto"
        resolution = 0
        if "1080" in match or "1080p" in match.lower():
            quality = "1080p"
            resolution = 1080
        elif "720" in match or "720p" in match.lower():
            quality = "720p"
            resolution = 720
        elif "480" in match or "480p" in match.lower():
            quality = "480p"
            resolution = 480
        elif "360" in match or "360p" in match.lower():
            quality = "360p"
            resolution = 360

        if match not in [s["url"] for s in streams]:
            streams.append({"url": match, "quality": quality, "resolution": resolution})

    # Pattern 2: Generic CDN URLs
    generic_cdn = r'(https?://cdn\.cee\.buzz/[^"\'\s<>]+\.(?:mp4|m3u8)[^"\'\s<>]*)'
    for match in re.findall(generic_cdn, html, re.IGNORECASE):
        if match not in [s["url"] for s in streams]:
            streams.append({"url": match, "quality": "Auto", "resolution": 0})

    # Pattern 3: video/source tags
    source_pattern = r'<(?:video|source)[^>]+src=["\']([^"\']+)["\'][^>]*>'
    for match in re.findall(source_pattern, html, re.IGNORECASE):
        if match.startswith("//"):
            match = "https:" + match
        elif match.startswith("/"):
            match = BASE_URL + match
        if ".mp4" in match or ".m3u8" in match:
            if match not in [s["url"] for s in streams]:
                streams.append({"url": match, "quality": "Auto", "resolution": 0})

    # Pattern 4: data-src / data-url attributes
    data_pattern = r'data-(?:src|url|video|stream|file)=["\']([^"\']+)["\']'
    for match in re.findall(data_pattern, html, re.IGNORECASE):
        if ".mp4" in match or ".m3u8" in match or "cdn.cee.buzz" in match:
            if match.startswith("//"):
                match = "https:" + match
            elif match.startswith("/"):
                match = BASE_URL + match
            if match not in [s["url"] for s in streams]:
                streams.append({"url": match, "quality": "Auto", "resolution": 0})

    # Pattern 5: JSON in scripts
    script_pattern = r'<script[^>]*>(.*?)</script>'
    for script in re.findall(script_pattern, html, re.IGNORECASE | re.DOTALL):
        # Look for video URL patterns
        url_patterns = [
            r'(https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*)',
            r'(https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)',
            r'["\']url["\']\s*:\s*["\']([^"\']+)["\']',
            r'["\']src["\']\s*:\s*["\']([^"\']+)["\']',
            r'["\']file["\']\s*:\s*["\']([^"\']+)["\']',
        ]
        for pattern in url_patterns:
            for url_match in re.findall(pattern, script, re.IGNORECASE):
                if ".mp4" in url_match or ".m3u8" in url_match or "cdn.cee.buzz" in url_match:
                    if url_match.startswith("//"):
                        url_match = "https:" + url_match
                    elif url_match.startswith("/"):
                        url_match = BASE_URL + url_match
                    if url_match not in [s["url"] for s in streams]:
                        streams.append({"url": url_match, "quality": "Auto", "resolution": 0})

        # Look for player config JSON
        try:
            json_pattern = r'(\{[^}]*(?:sources|tracks|file|url|video)[^}]*\})'
            for json_match in re.findall(json_pattern, script):
                data = json.loads(json_match)
                sources = data.get("sources") or []
                if isinstance(sources, list):
                    for src in sources:
                        if isinstance(src, dict):
                            url = src.get("file") or src.get("src") or src.get("url")
                            if url:
                                label = src.get("label") or src.get("quality") or "Auto"
                                res = 0
                                if "1080" in label: res = 1080
                                elif "720" in label: res = 720
                                elif "480" in label: res = 480
                                elif "360" in label: res = 360
                                if url not in [s["url"] for s in streams]:
                                    streams.append({"url": url, "quality": label, "resolution": res})
                        elif isinstance(src, str):
                            if src not in [s["url"] for s in streams]:
                                streams.append({"url": src, "quality": "Auto", "resolution": 0})
        except Exception:
            pass

    # Pattern 6: iframe embeds
    iframe_pattern = r'<iframe[^>]+src=["\']([^"\']+)["\'][^>]*>'
    for match in re.findall(iframe_pattern, html, re.IGNORECASE):
        if match.startswith("//"):
            match = "https:" + match
        elif match.startswith("/"):
            match = BASE_URL + match
        iframe_streams = _resolve_iframe(match)
        for s in iframe_streams:
            if s["url"] not in [x["url"] for x in streams]:
                streams.append(s)

    return streams


def _resolve_iframe(iframe_url):
    """Resolve iframe to find direct video streams."""
    streams = []
    status, html = _request(iframe_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not html:
        return streams

    patterns = [
        r'(https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*)',
        r'(https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)',
        r'<source[^>]+src=["\']([^"\']+)["\']',
        r'["\']file["\']\s*:\s*["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html, re.IGNORECASE):
            if match.startswith("//"):
                match = "https:" + match
            if match not in [s["url"] for s in streams]:
                streams.append({"url": match, "quality": "Auto", "resolution": 0})

    return streams


# ============================================================
# Main Entry Point
# ============================================================

def get_streams(media_type, media_id, config=None):
    imdb_id = media_id
    season = None
    episode = None

    if ":" in media_id:
        parts = media_id.split(":", 2)
        imdb_id = parts[0]
        if len(parts) > 1:
            season = parts[1]
        if len(parts) > 2:
            episode = parts[2]

    if not imdb_id.lower().startswith("tt"):
        return []

    # Step 1: Get title from TMDB
    tmdb_info = imdb_to_tmdb_info(imdb_id, media_type)
    if not tmdb_info:
        return []

    title = tmdb_info["title"]
    year = tmdb_info.get("year", "")

    # Step 2: Search CEE Buzz
    search_results = search_cee_buzz(title)

    # Filter by year
    if year and search_results:
        filtered = [r for r in search_results if year in r["title"]]
        if filtered:
            search_results = filtered

    if not search_results:
        if year:
            search_results = search_cee_buzz(f"{title} {year}")
        if not search_results:
            return []

    # Find best match
    best_match = None
    for result in search_results:
        result_title = result.get("title", "").lower()
        if title.lower() in result_title or result_title in title.lower():
            best_match = result
            break

    if not best_match:
        best_match = search_results[0]

    video_id = best_match.get("id", "")
    if not video_id:
        return []

    # Step 3: Extract streams
    streams = extract_streams(video_id, media_type, season, episode)

    if not streams:
        return []

    # Sort by resolution descending
    streams.sort(key=lambda x: x["resolution"], reverse=True)

    # Build MegaSource output
    output = []
    seen_urls = set()

    for stream in streams:
        url = stream["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)

        quality = stream["quality"]
        title_str = f"[{quality}] CEE Buzz"

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": BASE_URL + "/",
        }

        item = {
            "name": TITLE,
            "title": title_str,
            "url": url,
            "behaviorHints": {
                "notMyMetadata": True,
                "proxyHeaders": {
                    "request": headers
                }
            }
        }

        if stream["resolution"] >= 1080:
            item["behaviorHints"]["videoQuality"] = "1080p"
        elif stream["resolution"] >= 720:
            item["behaviorHints"]["videoQuality"] = "720p"
        elif stream["resolution"] >= 480:
            item["behaviorHints"]["videoQuality"] = "480p"
        else:
            item["behaviorHints"]["videoQuality"] = "360p"

        output.append(item)

    return output
