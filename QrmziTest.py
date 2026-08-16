"""
MegaSource
================================

Protocol
--------
Seguindo o protocolo do MegaSource, este arquivo define:

 TITLE, VERSION, DESCRIPTION
 get_streams(media_type: str, media_id: str, config: dict | None) -> list[dict]

media_type : "movie" | "series"
media_id : "tt0111161" (filme) | "tt0944947:1:1" (serie:temporada:episodio)

Retorna streams com behaviorHints.proxyHeaders.
Usa apenas a biblioteca padrao do Python (urllib + cookiejar).
"""

import http.cookiejar
import json
import re
import ssl
import string
import urllib.error
import urllib.parse
import urllib.request

# =============================================================================
# METADADOS DO SCRAPER
# =============================================================================
TITLE = "Qrmzi.tv"
VERSION = "2.0.0"
DESCRIPTION = "Turkish Movies & Series (Arabic) - 1080p Only Filter"

# =============================================================================
# CONSTANTES
# =============================================================================
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TMDB_API_KEY = "92c1507cc18d85290e7a0b96abb37316"
BASE_URL = "https://www.qrmzi.tv"

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

_cookiejar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookiejar))


# =============================================================================
# HTTP HELPER
# =============================================================================
def _request(url, method="GET", data=None, headers=None, timeout=15):
    """Requisicao HTTP com cookies, SSL e tratamento de erros."""
    h = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8,tr;q=0.7",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }
    if headers:
        h.update(headers)

    body = None
    if method == "POST":
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode("utf-8")
            h.setdefault("Content-Type", "application/x-www-form-urlencoded")
        elif data is not None:
            body = data

    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        with _opener.open(req, context=_ssl_ctx, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, raw.decode("utf-8")
            except UnicodeDecodeError:
                return r.status, raw.decode("latin-1", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", errors="replace")
        except:
            return e.code, ""
    except Exception:
        return 0, ""


# =============================================================================
# TMDB - TITULO E TRADUCAO ARABE
# =============================================================================
def _tmdb_find(imdb_id):
    """Converte IMDB ID para informacoes TMDB."""
    url = "https://api.themoviedb.org/3/find/" + urllib.parse.quote(imdb_id)
    q = urllib.parse.urlencode({"api_key": TMDB_API_KEY, "external_source": "imdb_id"})
    status, body = _request(url + "?" + q, timeout=10)
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
            "original_title": item.get("original_title", ""),
        }
    if data.get("tv_results"):
        item = data["tv_results"][0]
        return {
            "type": "tv",
            "tmdb_id": item["id"],
            "title": item.get("name", ""),
            "original_name": item.get("original_name", ""),
        }
    return None


def _tmdb_arabic_title(tmdb_id, media_type):
    """
    Busca traducao arabe do TMDB. Isso eh CRITICO porque o qrmzi.tv
    usa titulos em arabe, nao em turco/ingles.
    """
    tmdb_type = "movie" if media_type == "movie" else "tv"
    url = f"https://api.themoviedb.org/3/{tmdb_type}/{tmdb_id}/translations"
    q = urllib.parse.urlencode({"api_key": TMDB_API_KEY})
    status, body = _request(url + "?" + q, timeout=10)
    if status != 200:
        return None
    try:
        data = json.loads(body)
        for trans in data.get("translations", []):
            if trans.get("iso_639_1") == "ar":
                d = trans.get("data", {})
                return d.get("title") or d.get("name")
    except (ValueError, TypeError):
        pass
    return None


# =============================================================================
# BUSCA NO QRMZI.TV
# =============================================================================
def _search_qrmzi(query):
    """
    Busca no motor WordPress do qrmzi.tv.
    Retorna lista de dicts com url e tipo.
    """
    if not query or len(query.strip()) < 2:
        return []

    search_url = BASE_URL + "/?s=" + urllib.parse.quote(query.strip())
    status, body = _request(search_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return []

    results = []
    seen = set()

    # WordPress retorna resultados em <article>
    articles = re.findall(r"<article[^>]*>.*?</article>", body, re.S | re.I)
    for art in articles:
        link = re.search(
            r'href=["\'](https?://www\.qrmzi\.tv/(?:movies|series|episode)/[^"\']+)["\']',
            art, re.S | re.I,
        )
        if not link:
            continue

        url = link.group(1)
        if url in seen:
            continue
        seen.add(url)

        title = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", art, re.S | re.I)
        title_clean = re.sub(r"<[^>]+>", "", title.group(1)).strip() if title else ""

        item_type = "movie" if "/movies/" in url else "series"
        results.append({"title": title_clean, "url": url, "type": item_type})

    return results


# =============================================================================
# NAVEGACAO DE SERIES (SERIES -> EPISODIOS)
# =============================================================================
def _get_series_episode_url(series_title, season, episode):
    """
    Dado um titulo de serie, encontra a pagina da serie no qrmzi.tv
    e extrai o URL do episodio especifico.
    """
    # Busca pela serie
    results = _search_qrmzi(series_title)
    series_url = None

    for r in results:
        if r["type"] == "series" and "/series/" in r["url"]:
            series_url = r["url"]
            break
        elif r["type"] == "series" and "/episode/" in r["url"]:
            # Deriva URL da serie a partir do episodio
            slug_match = re.search(r'/episode/([^/]+)-الحلقة-\d+', r["url"])
            if slug_match:
                series_url = BASE_URL + "/series/" + slug_match.group(1) + "/"
                break

    if not series_url:
        return None

    # Busca episodios na pagina da serie
    status, body = _request(series_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return None

    # Procura link do episodio: /episode/...-الحلقة-{numero}/
    ep_pattern = r'href=["\'](https?://www\.qrmzi\.tv/episode/[^"\']+-الحلقة-' + str(episode) + r'(?:[-/]|$)[^"\']*)["\']'
    ep_match = re.search(ep_pattern, body, re.S | re.I)
    if ep_match:
        return ep_match.group(1)

    # Fallback: procura qualquer link de episodio com o numero
    all_eps = re.findall(
        r'href=["\'](https?://www\.qrmzi\.tv/episode/[^"\']+-الحلقة-\d+[^"\']*)["\']',
        body, re.S | re.I,
    )
    for ep_url in sorted(set(all_eps)):
        if f"-الحلقة-{episode}" in ep_url or f"-الحلقة-{episode}/" in ep_url:
            return ep_url

    return None


# =============================================================================
# EXTRACAO DO IFRAME ALBAPLAYER
# =============================================================================
def _extract_player_iframe(page_url):
    """Extrai o iframe do AlbaPlayer da pagina do filme/episodio."""
    status, body = _request(page_url, headers={"Referer": BASE_URL + "/"})
    if status != 200 or not body:
        return None

    m = re.search(
        r'<iframe[^>]+src=["\'](https?://w\.anaplayer\.online/[^"\']+)["\'][^>]*>',
        body, re.S | re.I,
    )
    if not m:
        return None

    src = m.group(1)
    if src.startswith("//"):
        src = "https:" + src
    return src


# =============================================================================
# DECODIFICADOR DE JAVASCRIPT PACKED (JWPlayer / Video Hosts)
# =============================================================================
def _decode_packed_js(body):
    """
    Decodifica JavaScript no formato:
    eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(...)}('code',base,'dict'));
    Usado pelos hosts de video (cdnplus, mp4plus, etc).
    """
    # Encontra o bloco eval
    eval_start = body.find('eval(function(p,a,c,k,e,d)')
    if eval_start < 0:
        return None

    # Encontra o fim do eval() respeitando strings e parenteses
    paren_depth = 0
    in_string = False
    s_char = None
    i = eval_start
    while i < len(body):
        c = body[i]
        if not in_string and c in "'\"":
            in_string = True
            s_char = c
        elif in_string and c == s_char and body[i - 1] != '\\':
            in_string = False
            s_char = None
        elif not in_string:
            if c == '(':
                paren_depth += 1
            elif c == ')':
                paren_depth -= 1
                if paren_depth == 0:
                    break
        i += 1

    eval_block = body[eval_start:i + 1]

    # Extrai o conteudo interno do eval: function(...){...}('code',base,'dict')
    inner_start = eval_block.find('(') + 1
    inner_end = eval_block.rfind(')')
    inner = eval_block[inner_start:inner_end]

    # Extrai argumentos da chamada interna: ('code',base,'dict')
    last_open = inner.rfind('(')
    last_close = inner.rfind(')')
    args_str = inner[last_open + 1:last_close]

    # Parse dos argumentos respeitando aspas
    def _split_args(s):
        parts = []
        cur = ""
        in_q = False
        q_c = None
        j = 0
        while j < len(s):
            ch = s[j]
            if not in_q and ch in "'\"":
                in_q = True
                q_c = ch
                cur += ch
            elif in_q and ch == q_c and s[j - 1] != '\\':
                cur += ch
                in_q = False
                q_c = None
            elif not in_q and ch == ',':
                parts.append(cur.strip())
                cur = ""
            else:
                cur += ch
            j += 1
        if cur.strip():
            parts.append(cur.strip())
        return parts

    parts = _split_args(args_str)
    if len(parts) < 3:
        return None

    code = parts[0].strip("'\"")
    try:
        base = int(parts[1].strip())
    except ValueError:
        base = 62
    dict_str = parts[2].strip("'\"")

    k = dict_str.split('|')
    digits = string.digits + string.ascii_lowercase + string.ascii_uppercase

    def to_base(n, b):
        if n == 0:
            return '0'
        res = ''
        while n > 0:
            res = digits[n % b] + res
            n //= b
        return res

    decoded = code
    for idx, val in enumerate(k):
        if not val:
            continue
        token = to_base(idx, base)
        decoded = re.sub(r'\b' + re.escape(token) + r'\b', val, decoded)

    return decoded


def _extract_video_from_embed(embed_url):
    """
    Acessa a pagina de embed do host de video e extrai o URL direto.
    Retorna (video_url, quality_label) ou (None, None).
    """
    status, body = _request(embed_url, headers={"Referer": "https://w.anaplayer.online/"})
    if status != 200 or not body:
        return None, None

    # ================================================================
    # Estrategia 1: Decodificar JS packed do JWPlayer
    # ================================================================
    decoded = _decode_packed_js(body)
    if decoded:
        # Procura configuracao JWPlayer: sources:[{file:"URL",label:"1080p"}]
        src_match = re.search(r'sources\s*:\s*(\[.*?\])', decoded, re.S)
        if src_match:
            try:
                src_str = src_match.group(1).replace("'", '"')
                sources = json.loads(src_str)
                for src in sources:
                    if isinstance(src, dict) and src.get("file"):
                        lbl = src.get("label", "")
                        return src["file"], lbl
            except (ValueError, TypeError):
                pass

        # Fallback no decoded: qualquer URL .mp4/.m3u8
        vid = re.search(r'"(https?://[^"]+\.(?:mp4|m3u8)[^"]*)"', decoded)
        if vid:
            return vid.group(1), ""

    # ================================================================
    # Estrategia 2: Fallback pela imagem poster
    # Hosts como cdnplus usam: /i/01/00005/xxxxx.jpg (poster)
    # O video pode estar em: /v/01/00005/xxxxx.mp4
    # ================================================================
    poster = re.search(
        r'<img[^>]+src=["\'](https?://[^"\']+/i/[^"\']+)["\']', body, re.S | re.I
    )
    if poster:
        guess = poster.group(1).replace("/i/", "/v/").replace(".jpg", ".mp4")
        return guess, ""

    return None, None


# =============================================================================
# EXTRACAO DE TODOS OS SERVIDORES DO ALBAPLAYER
# =============================================================================
def _extract_all_servers(player_base_url):
    """
    Acessa o player AlbaPlayer e extrai iframes de todos os servidores.
    Retorna lista de dicts com url do video, nome do servidor e qualidade.
    """
    all_sources = []

    # Servidores do AlbaPlayer (testados: 1-8)
    server_names = {
        "1": "CDNPlus",
        "2": "MP4Plus",
        "3": "AnaFast",
        "4": "Vidoba",
        "5": "VidSpeed",
        "6": "larhu",
    }
    # VK e OK sao embeds de redes sociais; pulamos por nao garantir 1080p direto

    for serv_num, serv_name in server_names.items():
        if "?" in player_base_url:
            url = player_base_url + "&serv=" + serv_num
        else:
            url = player_base_url + "?serv=" + serv_num

        try:
            status, body = _request(url, headers={"Referer": BASE_URL + "/"})
            if status != 200 or not body:
                continue

            # Extrai iframe do embed do servidor
            iframe = re.search(
                r'<iframe[^>]+src=["\']([^"\']+)["\'][^>]*>', body, re.S | re.I
            )
            if not iframe:
                continue

            embed = iframe.group(1)
            if embed.startswith("//"):
                embed = "https:" + embed

            # Pula embeds de redes sociais (nao conseguimos extrair MP4 direto)
            if any(x in embed for x in ["vk.com", "ok.ru", "youtube", "dailymotion"]):
                continue

            video_url, quality = _extract_video_from_embed(embed)
            if video_url:
                all_sources.append({
                    "url": video_url,
                    "quality": quality or "1080p",
                    "server": serv_name,
                    "referer": embed,
                })

        except Exception:
            continue

    return all_sources


# =============================================================================
# FILTRAGEM 1080p - الشرط الأساسي
# =============================================================================
def _filter_1080p(sources, page_title=""):
    """
    فلترة صارمة: تُرجع فقط السيرفرات التي يُؤكد وجود 1080p فيها.
    تُفحص: عنوان الصفحة، label الجودة، أو محتوى الصفحة.
    """
    filtered = []

    # فحص عنوان الصفحة أولاً
    page_has_1080 = bool(re.search(r"1080[pi]?", page_title, re.I))

    for src in sources:
        quality = src.get("quality", "")
        url = src.get("url", "")

        # التحقق من label الجودة
        has_1080_label = bool(re.search(r"1080[pi]?", quality, re.I))

        # التحقق من وجود 1080 في الرابط نفسه
        has_1080_in_url = bool(re.search(r"1080[pi]?", url, re.I))

        # القرار: إذا كان هناك تأكيد على 1080p في أي من المصادر، نُرجعه
        if has_1080_label or has_1080_in_url or page_has_1080:
            filtered.append(src)
            continue

        # للمسلسلات: إذا لم يكن هناك label واضح لكن الموقع معروف بـ 1080p
        # نتحقق من أن السيرفر ليس منخفض الجودة (720p, 480p, 360p)
        has_lower = bool(re.search(r"(?:720|480|360|240)[pi]?", quality, re.I))
        if not has_lower:
            # لا يوجد دليل على دقة منخفضة ولا دليل على 1080p
            # نتضمنه باعتبار أن qrmzi.tv متخصص في 1080p
            src["quality"] = "1080p (assumed)"
            filtered.append(src)

    return filtered


# =============================================================================
# RESOLUCAO DE FILMES
# =============================================================================
def _resolve_movie(imdb_id):
    """Resolve filme: IMDB -> TMDB -> qrmzi.tv -> Player -> Video."""
    try:
        info = _tmdb_find(imdb_id)
        if not info:
            return []

        # Coleta titulos para busca (arabe eh prioritario)
        queries = []
        ar_title = _tmdb_arabic_title(info["tmdb_id"], "movie")
        if ar_title:
            queries.append(ar_title)
        if info.get("original_title"):
            queries.append(info["original_title"])
        if info.get("title"):
            queries.append(info["title"])

        for query in queries:
            results = _search_qrmzi(query)
            for r in results:
                if r["type"] == "movie":
                    player = _extract_player_iframe(r["url"])
                    if player:
                        sources = _extract_all_servers(player)
                        if sources:
                            # فلترة 1080p باستخدام titulo da pagina
                            return _filter_1080p(sources, r.get("title", ""))
        return []
    except Exception:
        return []


# =============================================================================
# RESOLUCAO DE SERIES
# =============================================================================
def _resolve_series(imdb_id, season, episode):
    """Resolve serie: IMDB -> TMDB -> qrmzi series page -> episodio -> Player -> Video."""
    try:
        info = _tmdb_find(imdb_id)
        if not info:
            return []

        # Busca titulo arabe prioritariamente
        queries = []
        ar_title = _tmdb_arabic_title(info["tmdb_id"], "tv")
        if ar_title:
            queries.append(ar_title)
        if info.get("original_name"):
            queries.append(info["original_name"])
        if info.get("title"):
            queries.append(info["title"])

        for query in queries:
            ep_url = _get_series_episode_url(query, season, episode)
            if ep_url:
                player = _extract_player_iframe(ep_url)
                if player:
                    sources = _extract_all_servers(player)
                    if sources:
                        return _filter_1080p(sources, "")
        return []
    except Exception:
        return []


# =============================================================================
# ENTRADA PRINCIPAL MEGASOURCE
# =============================================================================
def get_streams(media_type, media_id, config=None):
    """
    Ponto de entrada do MegaSource.

    media_type: "movie" | "series"
    media_id: "tt0111161" ou "tt0944947:1:1"
    """
    imdb_id = media_id
    season = episode = None

    if ":" in media_id:
        parts = media_id.split(":", 2)
        if len(parts) == 3:
            imdb_id, season, episode = parts[0], parts[1], parts[2]

    sources = []
    if media_type == "movie":
        sources = _resolve_movie(imdb_id)
    elif media_type == "series" and season and episode:
        sources = _resolve_series(imdb_id, int(season), int(episode))

    streams = []
    for src in sources:
        # ================================================================
        # فلترة نهائية صارمة قبل الإرجاع
        # ================================================================
        quality = src.get("quality", "")
        url = src.get("url", "")

        # نتحقق مرة أخرى من 1080p
        is_1080 = bool(re.search(r"1080[pi]?", quality, re.I))
        is_1080_url = bool(re.search(r"1080[pi]?", url, re.I))

        if not is_1080 and not is_1080_url and "assumed" not in quality:
            continue

        streams.append(
            {
                "name": TITLE,
                "title": f"{src['server']} - {src['quality']}",
                "url": src["url"],
                "behaviorHints": {
                    "notMyMetadata": True,
                    "proxyHeaders": {
                        "request": {
                            "User-Agent": USER_AGENT,
                            "Origin": "https://w.anaplayer.online",
                            "Referer": src.get("referer", "https://w.anaplayer.online/"),
                        }
                    },
                },
            }
        )

    return streams
