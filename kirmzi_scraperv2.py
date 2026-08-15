"""
Kirmzi TV Scraper for MegaSource
=================================
Protocol:
  TITLE, VERSION, DESCRIPTION
  get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id   : "tt0111161" (movie) | "tt0944947:1:1" (series:season:episode)

Features:
  - Turkish Series with Arabic subtitles
  - Multiple server extraction (Vidoba, AnaFast, MP4Plus, CDNPlus, etc.)
  - Direct episode page access
  - Uses only Python standard library (urllib + cookiejar)

Site: https://kirmzi.tv
Episode Pattern: https://kirmzi.tv/episode/مسلسل-NAME-الحلقة-N/
"""

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = "Kirmzi TV"
VERSION = "1.0.0"
DESCRIPTION = "Kirmzi TV - Turkish Series with Arabic Subtitles"

BASE_URL = "https://kirmzi.tv"

TMDB_API_KEY = "ce91d0c4d737fceb1801c2bf58417b4b"
TMDB_BASE = "https://api.themoviedb.org/3"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
# Arabic Text Helpers
# ============================================================

def _slugify_arabic(text):
    """Convert title to Arabic URL slug (kirmzi style)."""
    slug = text.lower().strip()
    # Replace spaces with hyphens
    slug = re.sub(r'\s+', '-', slug)
    # Remove special chars except Arabic, English, digits, hyphens
    slug = re.sub(r'[^\u0600-\u06FF\u0750-\u077F\w\d\-]', '', slug)
    # Remove multiple hyphens
    slug = re.sub(r'-+', '-', slug)
    return slug.strip('-')


# ============================================================
# Kirmzi Search
# ============================================================

def search_kirmzi(query):
    """
    Search Kirmzi TV for a series.
    Returns list of dicts: [{"title": ..., "url": ..., "slug": ...}]
    """
    search_url = f"{BASE_URL}/?s={urllib.parse.quote(query)}"
    status, html = _request(search_url)
    if status != 200 or not html:
        return []

    results = []

    # Pattern 1: episode/series links
    ep_pattern = r'href=["\']([^"\']*/episode/[^"\']*)["\'][^>]*>([^<]{3,})<'
    matches = re.findall(ep_pattern, html, re.IGNORECASE)
    for match in matches:
        link, title = match
        if not link.startswith("http"):
            link = BASE_URL + link
        title = re.sub(r'<[^>]+>', '', title).strip()
        slug = link.replace(BASE_URL, "").replace("/episode/", "").rstrip("/")
        if title and slug:
            results.append({"title": title, "url": link, "slug": slug})

    # Pattern 2: series/archive links
    series_pattern = r'href=["\']([^"\']*/(?:series|مسلسل)[^"\']*)["\'][^>]*>([^<]{3,})<'
    matches = re.findall(series_pattern, html, re.IGNORECASE)
    for match in matches:
        link, title = match
        if not link.startswith("http"):
            link = BASE_URL + link
        title = re.sub(r'<[^>]+>', '', title).strip()
        slug = link.replace(BASE_URL, "").rstrip("/")
        if title and slug and not any(r["url"] == link for r in results):
            results.append({"title": title, "url": link, "slug": slug})

    # Pattern 3: generic post links with Arabic titles
    post_pattern = r'<a[^>]+href=["\']([^"\']*kirmzi\.tv[^"\']*(?:episode|مسلسل|حلقة)[^"\']*)["\'][^>]*>([^<]{3,})<'
    matches = re.findall(post_pattern, html, re.IGNORECASE)
    for match in matches:
        link, title = match
        title = re.sub(r'<[^>]+>', '', title).strip()
        slug = link.replace(BASE_URL, "").rstrip("/")
        if title and slug and not any(r["url"] == link for r in results):
            results.append({"title": title, "url": link, "slug": slug})

    return results


def get_series_episodes(series_slug, target_season=None, target_episode=None):
    """
    Get episode list from series page or build episode URL directly.
    Returns episode URL or None.
    """
    # Kirmzi pattern: /episode/مسلسل-NAME-الحلقة-N/
    # Try to build direct URL first
    if target_episode:
        # Pattern: مسلسل-NAME-الحلقة-EPISODE
        # Or: series-name-season-SE-episode-EP
        direct_patterns = [
            f"{BASE_URL}/episode/{series_slug}-الحلقة-{target_episode}/",
            f"{BASE_URL}/episode/{series_slug}-الحلقة-{target_episode}",
            f"{BASE_URL}/episode/مسلسل-{series_slug}-الحلقة-{target_episode}/",
            f"{BASE_URL}/episode/مسلسل-{series_slug}-الحلقة-{target_episode}",
        ]

        # If series_slug already contains "مسلسل-"
        if "مسلسل-" in series_slug:
            direct_patterns.extend([
                f"{BASE_URL}/episode/{series_slug}-الحلقة-{target_episode}/",
                f"{BASE_URL}/episode/{series_slug}-الحلقة-{target_episode}",
            ])

        for url in direct_patterns:
            status, html = _request(url)
            if status == 200 and html and len(html) > 1000:
                # Check if it looks like a valid episode page
                if any(marker in html.lower() for marker in [
                    "player", "iframe", "video", "server", "vidoba", "anafast",
                    "mp4plus", "cdnplus", "embed", "stream", "source"
                ]):
                    return url

    # Fallback: fetch series page and look for episode links
    series_url = f"{BASE_URL}/episode/{series_slug}/" if not series_slug.startswith("/") else f"{BASE_URL}{series_slug}"
    status, html = _request(series_url)
    if status == 200 and html:
        # Look for episode links
        ep_link_pattern = r'href=["\']([^"\']*(?:حلقة|episode)[^"\']*\d+[^"\']*)["\']'
        matches = re.findall(ep_link_pattern, html, re.IGNORECASE)
        for match in matches:
            if not match.startswith("http"):
                match = BASE_URL + match
            # Check if this matches target episode
            ep_num_match = re.search(r'(?:حلقة|episode)[\s\-]*(\d+)', match, re.IGNORECASE)
            if ep_num_match and target_episode:
                if ep_num_match.group(1) == str(target_episode):
                    return match

    return None


# ============================================================
# Server / Stream Extraction
# ============================================================

def extract_servers(episode_url):
    """
    Extract all server/stream URLs from episode page.
    Returns list of dicts: [{"name": ..., "url": ..., "quality": ...}]
    """
    status, html = _request(episode_url)
    if status != 200 or not html:
        return []

    servers = []

    # Pattern 1: Server buttons with data attributes
    # <button data-server="vidoba" data-link="...">
    server_btn_pattern = r'data-server=["\']([^"\']+)["\'][^>]*data-link=["\']([^"\']+)["\']'
    matches = re.findall(server_btn_pattern, html, re.IGNORECASE)
    for server_name, link in matches:
        if not link.startswith("http"):
            link = BASE_URL + link if link.startswith("/") else "https://" + link
        servers.append({"name": server_name, "url": link, "quality": "Auto"})

    # Pattern 2: Server tabs/links
    tab_pattern = r'<a[^>]+href=["\']([^"\']+)["\'][^>]*class=["\'][^"\']*server[^"\']*["\'][^>]*>([^<]*)</a>'
    matches = re.findall(tab_pattern, html, re.IGNORECASE)
    for link, server_name in matches:
        if not link.startswith("http"):
            link = BASE_URL + link if link.startswith("/") else "https://" + link
        name = re.sub(r'<[^>]+>', '', server_name).strip() or "Server"
        if link and not any(s["url"] == link for s in servers):
            servers.append({"name": name, "url": link, "quality": "Auto"})

    # Pattern 3: iframe embeds (most common)
    iframe_pattern = r'<iframe[^>]+src=["\']([^"\']+)["\'][^>]*>'
    matches = re.findall(iframe_pattern, html, re.IGNORECASE)
    for i, match in enumerate(matches):
        if match.startswith("//"):
            match = "https:" + match
        elif match.startswith("/"):
            match = BASE_URL + match
        if match and not any(s["url"] == match for s in servers):
            servers.append({"name": f"Embed-{i+1}", "url": match, "quality": "Auto"})

    # Pattern 4: video/source tags
    source_pattern = r'<source[^>]+src=["\']([^"\']+)["\'][^>]*>'
    matches = re.findall(source_pattern, html, re.IGNORECASE)
    for match in matches:
        if match.startswith("//"):
            match = "https:" + match
        elif match.startswith("/"):
            match = BASE_URL + match
        if match and not any(s["url"] == match for s in servers):
            quality = "Auto"
            if "1080" in match: quality = "1080p"
            elif "720" in match: quality = "720p"
            elif "480" in match: quality = "480p"
            elif "360" in match: quality = "360p"
            servers.append({"name": "Direct", "url": match, "quality": quality})

    # Pattern 5: JSON data in scripts (player configuration)
    script_pattern = r'<script[^>]*>(.*?)</script>'
    for script in re.findall(script_pattern, html, re.IGNORECASE | re.DOTALL):
        # Look for sources array
        try:
            json_pattern = r'(\{[^}]*(?:sources|tracks|file|url)[^}]*\})'
            for json_match in re.findall(json_pattern, script):
                data = json.loads(json_match)
                sources = data.get("sources") or []
                if isinstance(sources, list):
                    for src in sources:
                        if isinstance(src, dict):
                            url = src.get("file") or src.get("src") or src.get("url")
                            if url:
                                label = src.get("label") or src.get("quality") or "Auto"
                                if url.startswith("//"): url = "https:" + url
                                if url and not any(s["url"] == url for s in servers):
                                    servers.append({"name": "Player", "url": url, "quality": label})
                        elif isinstance(src, str):
                            if src.startswith("//"): src = "https:" + src
                            if src and not any(s["url"] == src for s in servers):
                                servers.append({"name": "Player", "url": src, "quality": "Auto"})
        except Exception:
            pass

        # Look for direct MP4/m3u8 URLs in scripts
        url_patterns = [
            r'(https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*)',
            r'(https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)',
        ]
        for pattern in url_patterns:
            for url_match in re.findall(pattern, script, re.IGNORECASE):
                if url_match and not any(s["url"] == url_match for s in servers):
                    quality = "Auto"
                    if "1080" in url_match: quality = "1080p"
                    elif "720" in url_match: quality = "720p"
                    elif "480" in url_match: quality = "480p"
                    elif "360" in url_match: quality = "360p"
                    servers.append({"name": "Direct", "url": url_match, "quality": quality})

    # Pattern 6: AJAX/API endpoints
    ajax_pattern = r'data-ajax=["\']([^"\']+)["\']|data-api=["\']([^"\']+)["\']'
    matches = re.findall(ajax_pattern, html, re.IGNORECASE)
    for match in matches:
        for group in match:
            if group:
                if not group.startswith("http"):
                    group = BASE_URL + group if group.startswith("/") else "https://" + group
                # Try to resolve AJAX endpoint
                ajax_status, ajax_html = _request(group, headers={"Referer": episode_url, "X-Requested-With": "XMLHttpRequest"})
                if ajax_status == 200 and ajax_html:
                    # Look for video URL in response
                    vid_match = re.search(r'(https?://[^"\'\s<>]+\.(?:mp4|m3u8)[^"\'\s<>]*)', ajax_html, re.IGNORECASE)
                    if vid_match:
                        url = vid_match.group(1)
                        if url and not any(s["url"] == url for s in servers):
                            servers.append({"name": "AJAX", "url": url, "quality": "Auto"})

    return servers


def resolve_server_url(server_url):
    """
    Resolve a server/embed URL to find the actual video stream.
    Handles common embed types.
    """
    streams = []
    status, html = _request(server_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not html:
        return streams

    # Look for direct video URLs
    patterns = [
        r'(https?://[^"\'\s<>]+\.mp4[^"\'\s<>]*)',
        r'(https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)',
        r'<source[^>]+src=["\']([^"\']+)["\']',
        r'["\']file["\']\s*:\s*["\']([^"\']+)["\']',
        r'["\']src["\']\s*:\s*["\']([^"\']+)["\']',
    ]
    for pattern in patterns:
        for match in re.findall(pattern, html, re.IGNORECASE):
            if match.startswith("//"):
                match = "https:" + match
            if match and match not in [s["url"] for s in streams]:
                quality = "Auto"
                if "1080" in match: quality = "1080p"
                elif "720" in match: quality = "720p"
                elif "480" in match: quality = "480p"
                elif "360" in match: quality = "360p"
                streams.append({"url": match, "quality": quality})

    # Look for nested iframes
    iframe_pattern = r'<iframe[^>]+src=["\']([^"\']+)["\'][^>]*>'
    for match in re.findall(iframe_pattern, html, re.IGNORECASE):
        if match.startswith("//"):
            match = "https:" + match
        elif match.startswith("/"):
            parsed = urllib.parse.urlparse(server_url)
            base = f"{parsed.scheme}://{parsed.netloc}"
            match = base + match
        nested = resolve_server_url(match)
        for s in nested:
            if s["url"] not in [x["url"] for x in streams]:
                streams.append(s)

    # Look for player config JSON
    script_pattern = r'<script[^>]*>(.*?)</script>'
    for script in re.findall(script_pattern, html, re.IGNORECASE | re.DOTALL):
        try:
            json_pattern = r'(\{[^}]*["\']sources["\'][^}]*\})'
            for json_match in re.findall(json_pattern, script):
                data = json.loads(json_match)
                sources = data.get("sources") or []
                if isinstance(sources, list):
                    for src in sources:
                        if isinstance(src, dict):
                            url = src.get("file") or src.get("src") or src.get("url")
                            if url:
                                label = src.get("label") or src.get("quality") or "Auto"
                                if url not in [s["url"] for s in streams]:
                                    streams.append({"url": url, "quality": label})
                        elif isinstance(src, str):
                            if src not in [s["url"] for s in streams]:
                                streams.append({"url": src, "quality": "Auto"})
        except Exception:
            pass

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

    # Kirmzi is mainly for TV series
    if media_type != "series" or not season or not episode:
        # Still try to search for movies
        pass

    # Step 1: Get title from TMDB
    tmdb_info = imdb_to_tmdb_info(imdb_id, "series" if media_type == "series" else "movie")
    if not tmdb_info:
        return []

    title = tmdb_info["title"]
    year = tmdb_info.get("year", "")

    # Step 2: Search Kirmzi
    search_results = search_kirmzi(title)

    # Filter by year if provided
    if year and search_results:
        filtered = [r for r in search_results if year in r["title"]]
        if filtered:
            search_results = filtered

    if not search_results:
        # Try with Arabic prefix
        search_results = search_kirmzi(f"مسلسل {title}")
        if not search_results and year:
            search_results = search_kirmzi(f"مسلسل {title} {year}")
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

    series_slug = best_match.get("slug", "")
    if not series_slug:
        return []

    # Step 3: Get episode URL
    episode_url = get_series_episodes(series_slug, season, episode)
    if not episode_url:
        return []

    # Step 4: Extract servers from episode page
    servers = extract_servers(episode_url)
    if not servers:
        return []

    # Step 5: Resolve servers to streams
    all_streams = []
    for server in servers:
        resolved = resolve_server_url(server["url"])
        for stream in resolved:
            stream["server_name"] = server["name"]
            all_streams.append(stream)
        # Also include the server URL itself (might be direct playable)
        if not resolved:
            all_streams.append({
                "url": server["url"],
                "quality": server["quality"],
                "server_name": server["name"]
            })

    if not all_streams:
        return []

    # Deduplicate
    seen_urls = set()
    unique_streams = []
    for s in all_streams:
        if s["url"] not in seen_urls:
            seen_urls.add(s["url"])
            unique_streams.append(s)

    # Sort by quality
    quality_order = {"1080p": 4, "720p": 3, "480p": 2, "360p": 1, "Auto": 0}
    unique_streams.sort(key=lambda x: quality_order.get(x["quality"], 0), reverse=True)

    # Build MegaSource output
    output = []
    for stream in unique_streams:
        quality = stream["quality"]
        server_name = stream.get("server_name", "Kirmzi")
        title_str = f"[{quality}] {server_name}"

        headers = {
            "User-Agent": USER_AGENT,
            "Referer": episode_url,
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

        res = quality_order.get(quality, 0)
        if res >= 4:
            item["behaviorHints"]["videoQuality"] = "1080p"
        elif res >= 3:
            item["behaviorHints"]["videoQuality"] = "720p"
        elif res >= 2:
            item["behaviorHints"]["videoQuality"] = "480p"
        else:
            item["behaviorHints"]["videoQuality"] = "360p"

        output.append(item)

    return output
