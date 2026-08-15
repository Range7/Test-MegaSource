"""
MegaSource + FaselHD (Ad-Break Support)
=======================================

Protocol
--------
Seguindo o protocolo do MegaSource, este arquivo define:

 TITLE, VERSION, DESCRIPTION
 get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id : "tt0111161" (filme) | "tt0944947:1:1" (serie: temporada: episodio)

Retorna streams com behaviorHints.proxyHeaders
Usa apenas a biblioteca padrao do Python (urllib + cookiejar).

FaselHD Integration:
- Usa backend Nuvio-compatible (145.241.158.129:3112)
- Preserva metadata de fasal/AdBreak do backend
- Converte IMDB -> TMDB automaticamente
"""

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request

TITLE = "MegaSource + FaselHD"
VERSION = "0.0.2"
DESCRIPTION = "Filmes e Series Dublados (watchplay) + FaselHD Arabic (Ad-Break)"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)
TMDB_API_KEY = "\x39\x32\x63\x31\x35\x30\x37\x63\x63\x31\x38\x64\x38\x35\x32\x39\x30\x65\x37\x61\x30\x62\x39\x36\x61\x62\x62\x33\x37\x33\x31\x36"
BASE_URL = "\x68\x74\x74\x70\x73\x3a\x2f\x2f\x76\x31\x2e\x77\x61\x74\x63\x68\x70\x6c\x61\x79\x2e\x73\x68\x6f\x70"

# FaselHD Backend (Nuvio-compatible — backend gerencia scraping e ad-breaks)
FASELHD_BACKEND = "http://145.241.158.129:3112"
FASELHD_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"

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

    if data.get("movie_results"):
        item = data["movie_results"][0]
        return {"type": "movie", "tmdb_id": item["id"], "title": item.get("title")}
    if data.get("tv_results"):
        item = data["tv_results"][0]
        return {"type": "tv", "tmdb_id": item["id"], "title": item.get("name")}
    return None


# ==================== WATCHPLAY (original) ====================

def movie(imdb_id):
    url = f"{BASE_URL}/movie/{urllib.parse.quote(imdb_id)}"
    status, body = _request(url, headers={"sec-fetch-dest": "iframe"})
    video_id = ""

    if status == 200:
        blocks = re.findall(
            r'<div class="option"(.*?)</div>\s*<span\s*class="dub"',
            body,
            re.S | re.I,
        )
        if blocks:
            for block in blocks:
                if "Dublado/Português" in block or "Dublado" in block:
                    match = re.search(r'data-id="(\d+)"', block)
                    if match:
                        video_id = match.group(1)
                        break
            if not video_id:
                for block in blocks:
                    match = re.search(r'data-id="(\d+)"', block)
                    if match:
                        video_id = match.group(1)
                        break

    if video_id:
        info = _get_player(video_id, url)
        if info:
            return info
    return {}


def series(imdb_id, season, episode):
    tmdb_info = imdb_to_tmdb(imdb_id)
    if not tmdb_info:
        return {}

    url = (
        f"{BASE_URL}/tvshow/{urllib.parse.quote(str(tmdb_info['tmdb_id']))}/"
        f"{season}/{episode}"
    )
    status, body = _request(url, headers={"sec-fetch-dest": "iframe"})
    content_id = ""

    if status == 200:
        cur_season = None
        cur_episode = None
        m_season = re.search(r"CURRENT_SEASON\s*=\s*'(\d+)'", body)
        m_episode = re.search(r"CURRENT_EPISODE\s*=\s*'(\d+)'", body)
        if m_season:
            cur_season = m_season.group(1)
        if m_episode:
            cur_episode = m_episode.group(1)

        if cur_season and cur_episode:
            pattern = (
                r'data-contentid="(\d+)"[^>]*data-season="'
                + re.escape(cur_season)
                + r'"[^>]*data-episode="'
                + re.escape(cur_episode)
                + '"'
            )
            match = re.search(pattern, body)
            if not match:
                pattern_alt = (
                    r'data-season="'
                    + re.escape(cur_season)
                    + r'"[^>]*data-episode="'
                    + re.escape(cur_episode)
                    + r'"[^>]*data-contentid="(\d+)"'
                )
                match = re.search(pattern_alt, body)
            if match:
                content_id = match.group(1)

    if not content_id:
        return {}

    api_headers = {
        "Origin": BASE_URL,
        "Referer": url,
        "x-requested-with": "XMLHttpRequest",
    }
    status_options, body_options = _request(
        BASE_URL + "/api",
        "POST",
        {"action": "getOptions", "contentid": content_id},
        headers=api_headers,
    )
    video_id = ""
    if status_options == 200:
        try:
            data = json.loads(body_options)
            options = data.get("data", {}).get("options", [])
            for option in options:
                if option.get("ID"):
                    video_id = option["ID"]
                    break
        except (ValueError, TypeError):
            pass

    if video_id:
        info = _get_player(video_id, url)
        if info:
            return info
    return {}


def _get_player(video_id, referer):
    api_headers = {
        "Origin": BASE_URL,
        "Referer": referer,
        "x-requested-with": "XMLHttpRequest",
    }
    status, body = _request(
        BASE_URL + "/api",
        "POST",
        {"action": "getPlayer", "video_id": video_id},
        headers=api_headers,
    )
    if status != 200:
        return {}
    try:
        data = json.loads(body)
        video_url = data.get("data", {}).get("video_url")
    except (ValueError, TypeError):
        return {}
    if not video_url:
        return {}
    return {
        "url": video_url,
        "User-Agent": USER_AGENT,
        "Origin": BASE_URL,
        "Referer": BASE_URL + "/",
    }


# ==================== FASELHD (Ad-Break via backend) ====================

def _faselhd_request(url):
    """Requisicao com headers especificos do FaselHD."""
    headers = {"User-Agent": FASELHD_UA}
    return _request(url, headers=headers)


def faselhd_streams(media_type, media_id):
    """
    Busca streams no backend FaselHD (compativel Nuvio).
    O backend gerencia scraping, resolucao de links e deteccao de ad-breaks.
    Preservamos TODO metadata retornado (incluindo adBreaks, skip, legendas, etc).
    """
    parts = media_id.split(":")
    imdb_id = parts[0]
    season = int(parts[1]) if len(parts) > 1 else None
    episode = int(parts[2]) if len(parts) > 2 else None

    # FaselHD usa TMDB ID
    tmdb_info = imdb_to_tmdb(imdb_id)
    if not tmdb_info:
        return []

    tmdb_id = tmdb_info["tmdb_id"]

    if media_type == "movie":
        fasel_type = "movie"
        id_str = str(tmdb_id)
    else:
        fasel_type = "series"
        id_str = f"{tmdb_id}:{season or 1}:{episode or 1}"

    backend_url = f"{FASELHD_BACKEND}/resolve/{fasel_type}/{id_str}"

    try:
        status, body = _faselhd_request(backend_url)
        if status != 200:
            return []

        data = json.loads(body)
        streams = data.get("streams", [])

        normalized = []
        for stream in streams:
            if not isinstance(stream, dict):
                continue

            # Nome do stream
            name = stream.get("name", "FaselHD")
            if "FaselHD" not in name:
                name = f"FaselHD - {name}"

            norm = {
                "name": name,
                "title": stream.get("title", tmdb_info.get("title", "Unknown")),
                "url": stream.get("url", ""),
            }

            # Preserva behaviorHints se o backend ja enviou (MegaSource / Stremio nativo)
            if "behaviorHints" in stream:
                norm["behaviorHints"] = stream["behaviorHints"]
            else:
                # Converte headers estilo Nuvio para MegaSource proxyHeaders
                hdrs = stream.get("headers", {})
                if hdrs:
                    norm["behaviorHints"] = {
                        "notMyMetadata": True,
                        "proxyHeaders": {"request": hdrs},
                    }
                else:
                    norm["behaviorHints"] = {
                        "notMyMetadata": True,
                        "proxyHeaders": {
                            "request": {
                                "User-Agent": FASELHD_UA,
                                "Referer": "https://faselhd.io/",
                            }
                        },
                    }

            # Preserva QUALQUER campo extra do backend:
            # adBreaks, skip, subtitles, quality, size, provider, etc.
            for key, value in stream.items():
                if key not in norm:
                    norm[key] = value

            normalized.append(norm)

        return normalized

    except Exception:
        return []


# ==================== MAIN ====================

def get_streams(media_type, media_id, config=None):
    imdb_id = media_id
    season = episode = None
    if ":" in media_id:
        parts = media_id.split(":", 2)
        imdb_id, season, episode = parts[0], parts[1], parts[2]

    all_streams = []

    # 1) Fonte original watchplay
    if media_type == "movie":
        info = movie(imdb_id)
    elif media_type == "series" and season and episode:
        info = series(imdb_id, int(season), int(episode))
    else:
        info = {}

    if info and info.get("url"):
        all_streams.append(
            {
                "name": "WatchPlay",
                "title": "Dublado",
                "url": info["url"],
                "behaviorHints": {
                    "notMyMetadata": True,
                    "proxyHeaders": {
                        "request": {
                            "User-Agent": info.get("User-Agent", USER_AGENT),
                            "Origin": info.get("Origin", BASE_URL),
                            "Referer": info.get("Referer", BASE_URL + "/"),
                        }
                    },
                },
            }
        )

    # 2) Fonte FaselHD (com suporte a ad-break via backend)
    fasel_streams = faselhd_streams(media_type, media_id)
    all_streams.extend(fasel_streams)

    return all_streams
