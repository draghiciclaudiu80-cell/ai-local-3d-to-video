"""Web tools for the chat. The chat asks the user before every use (unless they allowed it in Settings)."""
import html
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import MEDIA, load_settings
from .tor import tor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126 Safari/537.36"}


def _client() -> httpx.Client:
    """Every web request of the chat goes through here: through the built-in Tor (a fresh route per search) —
    or your own proxy if you set one. With Tor on, nothing is ever sent around it."""
    proxy = load_settings().get("web_proxy") or None  # e.g. socks5://127.0.0.1:9150 for Tor Browser
    if not proxy and tor.wanted():
        tor.ready()
        proxy = tor.proxy()
    return httpx.Client(headers=UA, follow_redirects=True, timeout=40 if proxy else 25, proxy=proxy)


def _text(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<(br|/p|/div|/li|/h\d|/tr)[^>]*>", "\n", raw)
    raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\r]+", " ", raw)).strip()


DDG_ONION = "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/html/"


def _via_tor() -> bool:
    return not load_settings().get("web_proxy") and tor.wanted()


def search(query: str, n: int = 6) -> list[dict]:
    """Through Tor: DuckDuckGo's own onion address first (it never blocks it; tested 403 from some Tor exits on the
    normal address), then the normal address on a fresh route."""
    urls = [DDG_ONION, "https://html.duckduckgo.com/html/", "https://html.duckduckgo.com/html/"] if _via_tor()         else ["https://html.duckduckgo.com/html/"]
    r, err = None, None
    for url in urls:
        try:
            with _client() as c:  # a new client = a new Tor route
                got = c.post(url, data={"q": query})
                got.raise_for_status()
        except httpx.HTTPError as e:
            err = e
            continue
        r = got
        if "result__a" in got.text:
            break
    if r is None:
        raise err
    out = []
    for m in re.finditer(r'(?s)<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'class="result__snippet"[^>]*>(.*?)</a>', r.text):
        url = m.group(1)
        if "uddg=" in url:  # DuckDuckGo redirect link -> real address
            url = unquote(parse_qs(urlparse(url).query).get("uddg", [url])[0])
        out.append({"title": _text(m.group(2)), "url": url, "snippet": _text(m.group(3))})
        if len(out) >= n:
            break
    return out


def read(url: str, limit: int = 6000) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    with _client() as c:
        r = c.get(url)
        r.raise_for_status()
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", r.text)
    return {"url": str(r.url), "title": _text(title.group(1)) if title else "", "text": _text(r.text)[:limit]}


def images(query: str, n: int = 20, page: int = 1) -> list[dict]:
    """Real photos of a subject from free picture libraries: Openverse (Flickr and more, adult content off), then
    Wikimedia Commons. Bing/Google/DuckDuckGo block apps like this one (Bing answered with random pictures).
    The small previews are saved on this PC, so the chat still shows them later — even offline."""
    found = []
    with _client() as c:
        try:
            r = c.get("https://api.openverse.org/v1/images/", params={"q": query, "page_size": n, "page": page, "mature": "false"})
            r.raise_for_status()
            for x in r.json().get("results", []):
                if x.get("url"):
                    found.append({"title": x.get("title") or "", "image": x["url"], "thumb_url": x.get("thumbnail") or x["url"],
                                  "page": x.get("foreign_landing_url") or x["url"],
                                  "tags": [t.get("name", "") for t in x.get("tags") or []][:15],
                                  "credit": " · ".join(v for v in (x.get("creator"), x.get("source"),
                                                                   (x.get("license") or "").upper()) if v)})
        except (httpx.HTTPError, ValueError, KeyError):
            pass  # rate limit / offline: Wikimedia below
        if len(found) < n:
            try:
                r = c.get("https://commons.wikimedia.org/w/api.php", params={
                    "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6,
                    "gsrlimit": n - len(found), "gsroffset": (page - 1) * n, "prop": "imageinfo", "iiprop": "url", "iiurlwidth": 400, "format": "json"})
                pages = sorted(((r.json().get("query") or {}).get("pages") or {}).values(), key=lambda p: p.get("index", 0))
                for p in pages:
                    ii = (p.get("imageinfo") or [{}])[0]
                    if ii.get("thumburl"):
                        found.append({"title": re.sub(r"\.\w+$", "", p["title"].removeprefix("File:")), "image": ii["url"],
                                      "thumb_url": ii["thumburl"], "page": ii.get("descriptionurl") or ii["url"],
                                      "tags": [], "credit": "Wikimedia Commons"})
            except (httpx.HTTPError, ValueError, KeyError):
                pass

        _previews(c, found[:n])
    return [p for p in found[:n] if p.get("thumb")]


def _previews(c: httpx.Client, items: list[dict]) -> None:
    """Saves each item's small preview on this PC (the chat shows them later too, even offline)."""
    folder = MEDIA / "web"
    folder.mkdir(exist_ok=True)

    def keep(p: dict) -> None:
        try:
            t = c.get(p["thumb_url"])
            if t.status_code == 200 and t.headers.get("content-type", "").startswith("image/") and len(t.content) < 5e6:
                name = f"{uuid.uuid4().hex[:12]}.jpg"
                (folder / name).write_bytes(t.content)
                p["thumb"] = f"/media/web/{name}"
        except httpx.HTTPError:
            pass
    with ThreadPoolExecutor(8) as ex:
        list(ex.map(keep, items))


def videos(query: str, n: int = 12) -> list[dict]:
    """YouTube results (title, length, channel, preview) — they play in the normal web browser.
    The EU cookie-consent page is skipped with YouTube's own 'reject all' cookie."""
    with _client() as c:
        r = c.get("https://www.youtube.com/results", params={"search_query": query, "hl": "en"},
                  headers={"Cookie": "SOCS=CAI"})
        r.raise_for_status()
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", r.text)
        found, stack = [], [json.loads(m.group(1))] if m else []
        while stack and len(found) < n:  # walk the page data in order; every "videoRenderer" is one video
            o = stack.pop()
            if isinstance(o, dict):
                v = o.get("videoRenderer")
                if isinstance(v, dict) and v.get("videoId"):
                    vid = v["videoId"]
                    found.append({"title": "".join(x.get("text", "") for x in (v.get("title") or {}).get("runs", [])),
                                  "url": f"https://www.youtube.com/watch?v={vid}",
                                  "thumb_url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
                                  "length": (v.get("lengthText") or {}).get("simpleText") or "LIVE",
                                  "channel": ((v.get("ownerText") or {}).get("runs") or [{}])[0].get("text", "")})
                    continue
                stack.extend(reversed(list(o.values())))
            elif isinstance(o, list):
                stack.extend(reversed(o))
        _previews(c, found)
    return [v for v in found if v.get("thumb")]
