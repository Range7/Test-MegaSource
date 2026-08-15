"""
Akwam Scraper for MegaSource
=============================
Protocol:
  TITLE, VERSION, DESCRIPTION
  get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id   : "tt0111161" (movie) | "tt0944947:1:1" (series:season:episode)

Features:
  - Movies & TV Series support
  - All qualities: 1080p, 720p, 480p, 360p
  - Follows Akwam link chain: quality-tab -> /link/ -> /download/ -> direct URL
  - Uses only Python standard library (urllib + cookiejar)

Based on akwam-dl by elmoiv (https://github.com/elmoiv/akwam-dl)
"""

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = "Akwam"
VERSION = "2.0.0"
DESCRIPTION = "Akwam Arabic Movies & Series - All Qualities"

BASE_URL = "https://akwam.it"

TMDB_API_KEY = "9801b6b0548ad57581d111ea690c85c8"
TMDB_BASE = "https://api.themoviedb.org/3"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/137.0.0.0 Safari/537.36"
)

# Regex patterns (from akwam-dl)
RGX_DL_URL = r'https?://(\w*\.*\w+\.\w+/link/\d+)'
RGX_SHORTEN_URL = r'https?://(\w*\.*\w+\.\w+/download/.*?)"'
RGX_DIRECT_URL = r'([a-z0-9]{4,}\.\w+\.\w+/download/.*?)"'
RGX_QUALITY_TAG = r'tab-content quality.*?a href="' + RGX_DL_URL + r'"'
RGX_SIZE_TAG = r'font-size-14 mr-auto">([0-9.MGB ]+)'

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


# ============================================================
# HTTP Helpers
# ============================================================

def _request(url, method="GET", headers=None, data=None, timeout=20):
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)

    body = None
    if method == "POST" and data is not None:
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
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
# Akwam Search
# ============================================================

def search_akwam(query):
    """Search Akwam for a query. Returns dict of {title: url}."""
    search_url = f"{BASE_URL}/search?q={urllib.parse.quote(query)}"
    status, html = _request(search_url)
    if status != 200 or not html:
        return {}

    results = {}

    # Pattern 1: movie/series cards with links
    # Typical: <a href="/movie/12345-title" class="...">...</a>
    card_pattern = r'<a[^>]+href=["\']([^"\']*(?:movie|series|show)[^"\']*\d+[^"\']*)["\'][^>]*>[^<]*<[^>]*>([^<]*)</'
    matches = re.findall(card_pattern, html, re.IGNORECASE)
    for match in matches:
        link, title = match
        if not link.startswith("http"):
            link = BASE_URL + link
        title = re.sub(r'<[^>]+>', '', title).strip()
        if title and link:
            results[title] = link

    # Pattern 2: alternative card structure
    alt_pattern = r'<a[^>]+href=["\']([^"\']*(?:movie|series)[^"\']*\d+[^"\']*)["\'][^>]*>.*?<h[1-6][^>]*>([^<]*)</h'
    matches = re.findall(alt_pattern, html, re.IGNORECASE | re.DOTALL)
    for match in matches:
        link, title = match
        if not link.startswith("http"):
            link = BASE_URL + link
        title = re.sub(r'<[^>]+>', '', title).strip()
        if title and link and title not in results:
            results[title] = link

    # Pattern 3: search results list
    list_pattern = r'href=["\']([^"\']*(?:movie|series)[^"\']*\d+[^"\']*)["\'][^>]*>([^<]{3,})<'
    matches = re.findall(list_pattern, html, re.IGNORECASE)
    for match in matches:
        link, title = match
        if not link.startswith("http"):
            link = BASE_URL + link
        title = re.sub(r'<[^>]+>', '', title).strip()
        if title and link and title not in results:
            results[title] = link

    return results


# ============================================================
# Quality & Stream Extraction
# ============================================================

def extract_qualities(page_html):
    """
    Extract quality links from movie/episode page.
    Returns dict of {quality_label: link_url}
    """
    qualities = {}

    # Clean HTML for regex
    clean_html = page_html.replace('\n', '')

    # Find all quality tabs
    # Pattern: tab-content quality...>1080p<...a href="https://.../link/12345"
    quality_patterns = [
        (r'tab-content quality[^"\']*1080[^"\']*"[^>]*>.*?<a[^>]+href=["\']([^"\']*/link/\d+)["\']', "1080p"),
        (r'tab-content quality[^"\']*720[^"\']*"[^>]*>.*?<a[^>]+href=["\']([^"\']*/link/\d+)["\']', "720p"),
        (r'tab-content quality[^"\']*480[^"\']*"[^>]*>.*?<a[^>]+href=["\']([^"\']*/link/\d+)["\']', "480p"),
        (r'tab-content quality[^"\']*360[^"\']*"[^>]*>.*?<a[^>]+href=["\']([^"\']*/link/\d+)["\']', "360p"),
    ]

    for pattern, quality in quality_patterns:
        match = re.search(pattern, clean_html, re.IGNORECASE)
        if match:
            link = match.group(1)
            if not link.startswith("http"):
                link = BASE_URL + link
            qualities[quality] = link

    # Fallback: generic quality extraction
    if not qualities:
        # Find all /link/ URLs and try to associate with quality
        link_pattern = r'<a[^>]+href=["\']([^"\']*/link/\d+)["\'][^>]*>([^<]*(?:1080|720|480|360)[^<]*)</a>'
        matches = re.findall(link_pattern, clean_html, re.IGNORECASE)
        for link, label in matches:
            if not link.startswith("http"):
                link = BASE_URL + link
            if "1080" in label:
                qualities["1080p"] = link
            elif "720" in label:
                qualities["720p"] = link
            elif "480" in label:
                qualities["480p"] = link
            elif "360" in label:
                qualities["360p"] = link

    return qualities


def resolve_link_chain(link_url):
    """
    Follow Akwam link chain:
    /link/12345 -> redirect -> /download/... -> direct URL
    Returns the final direct URL or None.
    """
    # Step 1: Visit the link page (follows redirects automatically)
    status, html = _request(link_url)
    if status != 200 or not html:
        return None

    # Step 2: Find shortened download URL
    shorten_match = re.search(RGX_SHORTEN_URL, html, re.IGNORECASE)
    if not shorten_match:
        # Try alternative pattern
        shorten_match = re.search(r'href=["\']([^"\']*/download/[^"\']*)["\']', html, re.IGNORECASE)
    if not shorten_match:
        return None

    shorten_url = "https://" + shorten_match.group(1)

    # Step 3: Visit shortened URL (follows redirects)
    status, html = _request(shorten_url)
    if status != 200 or not html:
        return None

    # Step 4: Extract direct URL
    direct_match = re.search(RGX_DIRECT_URL, html, re.IGNORECASE)
    if not direct_match:
        # Try alternative patterns
        direct_match = re.search(r'(https?://[a-z0-9]{4,}\.\w+\.\w+/download/[^"\'\s<>]+)', html, re.IGNORECASE)
    if not direct_match:
        return None

    direct_url = direct_match.group(1)
    if not direct_url.startswith("http"):
        direct_url = "https://" + direct_url

    return direct_url


def extract_episodes(series_page_html):
    """
    Extract episode list from series page.
    Returns list of (episode_name, episode_url) tuples.
    """
    episodes = []

    # Pattern 1: episode cards/links
    ep_pattern = r'<a[^>]+href=["\']([^"\']*(?:episode|ep)[^"\']*\d+[^"\']*)["\'][^>]*>([^<]*(?:حلقة|Episode|EP)[^<]*)</a>'
    matches = re.findall(ep_pattern, series_page_html, re.IGNORECASE)
    for link, name in matches:
        if not link.startswith("http"):
            link = BASE_URL + link
        name = re.sub(r'<[^>]+>', '', name).strip()
        if name and link:
            episodes.append((name, link))

    # Pattern 2: alternative episode structure
    alt_pattern = r'href=["\']([^"\']*(?:episode|ep)[^"\']*\d+[^"\']*)["\'][^>]*>\s*<[^>]*>\s*([^<]*(?:حلقة|Episode)[^<]*)<'
    matches = re.findall(alt_pattern, series_page_html, re.IGNORECASE)
    for link, name in matches:
        if not link.startswith("http"):
            link = BASE_URL + link
        name = re.sub(r'<[^>]+>', '', name).strip()
        if name and link and (name, link) not in episodes:
            episodes.append((name, link))

    # Pattern 3: season/episode list
    season_pattern = r'<a[^>]+href=["\']([^"\']*season[^"\']*\d+[^"\']*)["\'][^>]*>([^<]*)</a>'
    matches = re.findall(season_pattern, series_page_html, re.IGNORECASE)
    for link, name in matches:
        if not link.startswith("http"):
            link = BASE_URL + link
        name = re.sub(r'<[^>]+>', '', name).strip()
        if name and link and (name, link) not in episodes:
            episodes.append((name, link))

    return episodes


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

    # Step 2: Search Akwam
    search_results = search_akwam(title)
    if not search_results:
        # Try with year appended
        if year:
            search_results = search_akwam(f"{title} {year}")
        if not search_results:
            return []

    # Find best match
    best_url = None
    for result_title, result_url in search_results.items():
        if title.lower() in result_title.lower() or result_title.lower() in title.lower():
            best_url = result_url
            break

    if not best_url:
        best_url = list(search_results.values())[0]

    # Step 3: Extract streams based on type
    all_streams = []

    if media_type == "movie":
        # Fetch movie page
        status, page_html = _request(best_url)
        if status != 200 or not page_html:
            return []

        qualities = extract_qualities(page_html)
        for quality, link_url in qualities.items():
            direct_url = resolve_link_chain(link_url)
            if direct_url:
                all_streams.append({
                    "url": direct_url,
                    "quality": quality,
                    "resolution": int(quality.replace("p", "")) if quality.replace("p", "").isdigit() else 0,
                })

    elif media_type == "series" and season and episode:
        # Fetch series page
        status, page_html = _request(best_url)
        if status != 200 or not page_html:
            return []

        episodes = extract_episodes(page_html)
        if not episodes:
            return []

        # Try to find matching episode
        target_ep = None
        for ep_name, ep_url in episodes:
            # Match by season and episode number
            ep_match = re.search(r'(?:حلقة|Episode|EP|E)\s*(\d+)', ep_name, re.IGNORECASE)
            if ep_match:
                ep_num = ep_match.group(1)
                if ep_num == str(episode).zfill(1):
                    target_ep = (ep_name, ep_url)
                    break

        # Fallback: use episode index
        if not target_ep and episodes:
            try:
                ep_idx = int(episode) - 1
                if 0 <= ep_idx < len(episodes):
                    target_ep = episodes[ep_idx]
            except (ValueError, IndexError):
                pass

        if target_ep:
            _, ep_url = target_ep
            status, ep_html = _request(ep_url)
            if status == 200 and ep_html:
                qualities = extract_qualities(ep_html)
                for quality, link_url in qualities.items():
                    direct_url = resolve_link_chain(link_url)
                    if direct_url:
                        all_streams.append({
                            "url": direct_url,
                            "quality": quality,
                            "resolution": int(quality.replace("p", "")) if quality.replace("p", "").isdigit() else 0,
                        })

    if not all_streams:
        return []

    # Sort by resolution descending (highest first)
    all_streams.sort(key=lambda x: x["resolution"], reverse=True)

    # Build MegaSource output
    output = []
    seen_urls = set()

    for stream in all_streams:
        url = stream["url"]
        if url in seen_urls:
            continue
        seen_urls.add(url)

        quality = stream["quality"]
        title_str = f"[{quality}] Akwam"

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
