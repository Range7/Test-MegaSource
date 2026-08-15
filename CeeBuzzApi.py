"""
MegaSource — Cee.buzz Only
==========================

Protocolo MegaSource:
  get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id   : "tt0111161" (filme) | "tt0944947:1:1" (serie:temporada:episodio)

Cee.buzz API:
  Base    : https://cee.buzz
  API v2  : https://cee.buzz/api/android

Fluxo:
  1. IMDB -> TMDB (titulo + ano)
  2. Busca no Cee por titulo
  3. Match por titulo/ano -> cee_id (nb)
  4. Series: busca episodios -> encontra SxE -> cee_id do episodio
  5. Busca links diretos + legendas
"""

import http.cookiejar
import json
import urllib.error
import urllib.parse
import urllib.request

TITLE = "Cee"
VERSION = "1.0"
DESCRIPTION = "Cee.buzz Arabic Movies & Series"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
)

TMDB_API_KEY = "1c29a5198ee1854bd5eb45dbe8d17d92"

CEE_BASE = "https://cee.buzz"
CEE_API = f"{CEE_BASE}/api/android"

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
        with _opener.open(req, timeout=20) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception:
        return 0, ""


def imdb_to_tmdb(imdb_id):
    """Converte IMDB ID para TMDB (titulo, ano, tipo)."""
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


def _to_str(val):
    """Converte valor API para string."""
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(int(val))
    return str(val)


def _search_cee(title, ctype, year=None):
    """
    Busca no Cee.buzz por titulo.
    ctype: 'movies' ou 'series'
    Retorna lista de dicts com nb, title, year, kind, img
    """
    encoded = urllib.parse.quote(title)
    year_range = "1900,2026"

    search_url = (
        f"{CEE_API}/AdvancedSearch?"
        f"level=0&videoTitle={encoded}&staffTitle={encoded}"
        f"&year={year_range}&page=0&type={ctype}&itemsPerPage=30"
    )

    status, body = _request(search_url)
    if status != 200:
        return []

    try:
        data = json.loads(body)
        if not isinstance(data, list):
            return []
    except (ValueError, TypeError):
        return []

    results = []
    for item in data:
        if not isinstance(item, dict):
            continue

        nb = item.get("nb")
        if nb is None:
            continue
        nb = _to_str(nb)
        if not nb:
            continue

        en_title = item.get("en_title") or item.get("title") or ""
        ar_title = item.get("ar_title") or ""
        item_year = _to_str(item.get("year"))
        kind = item.get("kind")
        if isinstance(kind, str):
            try:
                kind = int(kind)
            except (ValueError, TypeError):
                kind = None

        img = item.get("imgObjUrl") or item.get("img") or ""

        results.append({
            "nb": nb,
            "title": en_title or ar_title,
            "year": item_year,
            "kind": kind,
            "img": img,
        })

    return results


def _score_match(result, query_title, query_year):
    """Pontua match por titulo e ano."""
    score = 0
    r_title = (result.get("title") or "").lower().strip()
    q_title = query_title.lower().strip()

    if r_title == q_title:
        score = 100
    elif r_title.startswith(q_title):
        score = 80
    elif q_title in r_title:
        score = 60
    else:
        # Token matching
        q_tokens = [t for t in q_title.split() if len(t) > 2]
        matches = sum(1 for t in q_tokens if t in r_title)
        score = 30 + matches * 10

    # Year bonus
    if query_year and result.get("year") and query_year in str(result.get("year")):
        score += 20

    return score


def _find_best_match(results, title, year=None):
    """Encontra o melhor match."""
    if not results:
        return None

    scored = [( _score_match(r, title, year), r ) for r in results]
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]

    if best_score < 25:
        return None
    return best


def _get_video_links(cee_id):
    """Busca links de video diretos."""
    url = f"{CEE_API}/transcoddedFiles/id/{cee_id}"
    status, body = _request(url)
    if status != 200:
        return []

    try:
        data = json.loads(body)
        if not isinstance(data, list):
            return []
    except (ValueError, TypeError):
        return []

    links = []
    for item in data:
        if not isinstance(item, dict):
            continue
        video_url = item.get("videoUrl")
        resolution = item.get("resolution") or "Unknown"
        if video_url and isinstance(video_url, str):
            links.append({"url": video_url, "resolution": resolution})
    return links


def _get_subtitles(cee_id):
    """Busca legendas."""
    url = f"{CEE_API}/allVideoInfo/id/{cee_id}"
    status, body = _request(url)
    if status != 200:
        return []

    try:
        data = json.loads(body)
        if not isinstance(data, dict):
            return []
    except (ValueError, TypeError):
        return []

    subs = []
    translations = data.get("translations")
    if isinstance(translations, list):
        for sub in translations:
            if not isinstance(sub, dict):
                continue
            file_url = sub.get("file")
            lang = sub.get("name") or "Unknown"
            if file_url and isinstance(file_url, str):
                subs.append({"url": file_url, "lang": lang})
    return subs


def _get_episodes(cee_id):
    """Busca lista de episodios de uma serie."""
    url = f"{CEE_API}/videoSeason/id/{cee_id}"
    status, body = _request(url)
    if status != 200:
        return []

    try:
        data = json.loads(body)
        if not isinstance(data, list):
            return []
    except (ValueError, TypeError):
        return []

    episodes = []
    for item in data:
        if not isinstance(item, dict):
            continue

        nb = item.get("nb")
        if nb is None:
            continue
        nb = _to_str(nb)
        if not nb:
            continue

        ep_num_raw = item.get("episodeNummer") or item.get("episode") or "1"
        season_raw = item.get("season") or "1"

        try:
            ep_num = int(str(ep_num_raw))
        except (ValueError, TypeError):
            ep_num = 1

        try:
            season_num = int(str(season_raw))
        except (ValueError, TypeError):
            season_num = 1

        episodes.append({
            "nb": nb,
            "season": season_num,
            "episode": ep_num,
            "title": item.get("en_title") or item.get("title") or f"S{season_num}E{ep_num}",
        })

    return episodes


def cee_streams(media_type, media_id):
    """Busca streams no Cee.buzz."""
    parts = media_id.split(":")
    imdb_id = parts[0]
    season = int(parts[1]) if len(parts) > 1 else None
    episode = int(parts[2]) if len(parts) > 2 else None

    # 1. IMDB -> TMDB
    tmdb_info = imdb_to_tmdb(imdb_id)
    if not tmdb_info:
        return []

    title = tmdb_info.get("title", "")
    year = tmdb_info.get("year", "")
    if not title:
        return []

    # 2. Busca no Cee
    ctype = "movies" if media_type == "movie" else "series"
    results = _search_cee(title, ctype, year)

    # 3. Match
    match = _find_best_match(results, title, year)
    if not match:
        return []

    cee_id = match["nb"]
    cee_title = match.get("title") or title

    # 4. Series: encontra episodio especifico
    if media_type == "series" and season and episode:
        episodes = _get_episodes(cee_id)
        target_ep = None
        for ep in episodes:
            if ep["season"] == season and ep["episode"] == episode:
                target_ep = ep
                break

        if not target_ep:
            return []

        cee_id = target_ep["nb"]
        cee_title = target_ep.get("title") or cee_title

    # 5. Links de video
    links = _get_video_links(cee_id)
    if not links:
        return []

    # 6. Legendas
    subs = _get_subtitles(cee_id)

    # 7. Monta streams
    normalized = []
    for link in links:
        resolution = link.get("resolution", "Unknown")
        stream_name = f"Cee - {resolution}"

        norm = {
            "name": stream_name,
            "title": cee_title,
            "url": link["url"],
            "behaviorHints": {
                "notMyMetadata": True,
                "proxyHeaders": {
                    "request": {
                        "User-Agent": USER_AGENT,
                        "Referer": CEE_BASE,
                    }
                },
            },
        }

        # Legendas (se disponiveis)
        if subs:
            norm["subtitles"] = [
                {"url": s["url"], "lang": s["lang"]} for s in subs
            ]

        normalized.append(norm)

    return normalized


def get_streams(media_type, media_id, config=None):
    return cee_streams(media_type, media_id)
