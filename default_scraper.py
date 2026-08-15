"""
MegaSource — FaselHD Only (Ad-Break / فاصل اعلاني)
====================================================

Protocolo MegaSource:
  get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id   : "tt0111161" (filme) | "tt0944947:1:1" (serie:temporada:episodio)

FaselHD usa backend Nuvio-compatible (145.241.158.129:3112).
O backend gerencia scraping, links e metadata de ad-break.
"""

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

TITLE = "FaselHD"
VERSION = "1.0"
DESCRIPTION = "FaselHD Arabic — Ad-Break support via backend"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

# TMDB API key (hex-decoded do original)
TMDB_API_KEY = "92c1507cc18d85290e7a0b96abb37316"

# FaselHD backend (mesmo usado pelo plugin Nuvio)
FASELHD_BACKEND = "http://145.241.158.129:3112"
FASELHD_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)

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
    """Converte IMDB ID para TMDB ID + tipo + titulo."""
    find_url = (
        "https://api.themoviedb.org/3/find/"
        + urllib.parse.quote(imdb_id)
        + "?"
        + urllib.parse.urlencode(
            {"api_key": TMDB_API_KEY, "external_source": "imdb_id"}
        )
    )
    status, body = _request(find_url)
    if status != 200:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None

    if data.get("movie_results"):
        item = data["movie_results"][0]
        return {"type": "movie", "tmdb_id": item["id"], "title": item.get("title", "")}
    if data.get("tv_results"):
        item = data["tv_results"][0]
        return {"type": "tv", "tmdb_id": item["id"], "title": item.get("name", "")}
    return None


def faselhd_streams(media_type, media_id):
    """
    Busca streams no backend FaselHD.
    Preserva todo metadata do backend (adBreaks, skip, legendas, etc).
    """
    parts = media_id.split(":")
    imdb_id = parts[0]
    season = int(parts[1]) if len(parts) > 1 else None
    episode = int(parts[2]) if len(parts) > 2 else None

    # FaselHD precisa de TMDB ID
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
        status, body = _request(backend_url, headers={"User-Agent": FASELHD_UA})
        if status != 200:
            return []

        data = json.loads(body)
        streams = data.get("streams", [])

        normalized = []
        for stream in streams:
            if not isinstance(stream, dict):
                continue
            if not stream.get("url"):
                continue

            # Nome visivel
            name = stream.get("name", "FaselHD")
            if "FaselHD" not in name:
                name = f"FaselHD - {name}"

            norm = {
                "name": name,
                "title": stream.get("title", tmdb_info.get("title", "Unknown")),
                "url": stream["url"],
            }

            # Headers / proxyHeaders (compativel MegaSource)
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


def get_streams(media_type, media_id, config=None):
    # Apenas FaselHD
    return faselhd_streams(media_type, media_id)
