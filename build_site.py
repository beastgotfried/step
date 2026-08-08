#!/usr/bin/env python3
"""Mirror the published Framer site into a self-hostable static bundle.

Usage:
    python3 build_site.py [ORIGIN] [OUTDIR]
    python3 build_site.py https://ankush.space dist
    python3 build_site.py http://127.0.0.1:8080 dist    # for local testing

Why asset URLs stay absolute
----------------------------
Framer's runtime resolves its lazy-loaded chunks with `new URL(chunk, base)`.
A relative base ("../assets/...") is not a valid URL base, so rewriting assets
to relative paths makes the runtime throw "Failed to construct 'URL': Invalid
base URL". React's error boundary then replaces the whole tree and the page
renders as empty chrome. Assets are therefore rewritten to ORIGIN-absolute
URLs, which means ORIGIN must match wherever the bundle is actually served.
"""
import hashlib
import html
import json
import pathlib
import re
import shutil
import sys
import urllib.parse
import urllib.request

SRC = "https://brilliant-imagine-119149.framer.app"
ORIGIN = (sys.argv[1] if len(sys.argv) > 1 else "https://ankush.space").rstrip("/")
OUT = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else "dist")

# route -> output file. Framer serves extensionless routes; we emit directory
# indexes so any static host resolves them without rewrite rules.
PAGES = {
    "/": "index.html",
    "/projects": "projects/index.html",
    "/projects/agenta": "projects/agenta/index.html",
    "/projects/gpt": "projects/gpt/index.html",
    "/projects/zenspace": "projects/zenspace/index.html",
    "/projects/sign-language-detection": "projects/sign-language-detection/index.html",
    "/terms": "terms/index.html",
    "/privacy-policy": "privacy-policy/index.html",
}

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"
}
# Every host Framer serves runtime assets from. events.framer.com is deliberately
# absent: it only serves the analytics beacon, which strip_framer() removes, so
# mirroring it would download a script that never gets referenced.
HOSTS = (
    "framerusercontent.com",
    "fonts.gstatic.com",
    "app.framerstatic.com",
)
ABS_URL = re.compile(
    r"https://(?:" + "|".join(h.replace(".", r"\.") for h in HOSTS) + r")/[^\s\"'`\)<>\\]+"
)
# Chunks referenced only from inside other chunks, as import("./name.mjs").
REL_MJS = re.compile(r"[\"'`]\./([A-Za-z0-9._\-]+\.mjs)[\"'`]")

TEXTUAL = ("javascript", "css", "json", "text")
TEXT_EXT = (".mjs", ".css", ".js", ".json")

# Framer's analytics beacon: a plain <script async src="...events.framer.com/...">
# right after <body>. Not React-managed, so deleting it outright is safe. The
# pattern matches both the original URL and the ORIGIN-rewritten form.
BEACON = re.compile(r"<script[^>]*events\.framer\.com[^>]*>\s*</script>\s*", re.I)
BADGE_COMMENT = re.compile(r"<!--\s*Made in Framer[^>]*-->\s*")
# The badge div is hidden with CSS rather than removed from the HTML. It sits
# inside React Suspense markers (<!--$-->), and a hydration mismatch on this
# bundle trips GracefullyDegradingErrorBoundary, which replaces the entire tree
# with empty chrome and logs nothing. Not a trade worth making for a badge.
BADGE_CSS = "<style>#__framer-badge-container{display:none!important}</style>"


def strip_framer(text):
    """Remove Framer's tracking beacon and hide its "Made in Framer" badge."""
    text = BEACON.sub("", text)
    text = BADGE_COMMENT.sub("", text)
    if BADGE_CSS not in text:
        text = text.replace("</head>", f"{BADGE_CSS}</head>", 1)
    return text


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read(), resp.headers.get("Content-Type", "")


def clean_url(url):
    """Trim trailing junk captured when a URL is embedded in JS or HTML."""
    url = html.unescape(url)
    url = url.split("`")[0].split('"')[0].split("'")[0]
    return url.rstrip(".,;:")


def find_urls(text):
    return {clean_url(m) for m in ABS_URL.findall(text)}


assets = {}  # remote url -> bundle-relative path


def local_path(url):
    """Map a remote asset URL to a collision-free path inside the bundle."""
    if url in assets:
        return assets[url]
    parts = urllib.parse.urlparse(url)
    path = parts.path.lstrip("/") or "index"
    # A path that is also a directory elsewhere would collide on disk.
    if "." not in path.rsplit("/", 1)[-1]:
        path += "/_file"
    # Same file, different query (image resizes) must not overwrite each other.
    if parts.query:
        digest = hashlib.md5(parts.query.encode()).hexdigest()[:8]
        stem, _, ext = path.rpartition(".")
        path = f"{stem}__{digest}.{ext}" if ext else f"{path}__{digest}"
    rel = f"assets/{parts.netloc.replace(':', '_')}/{path}"
    assets[url] = rel
    return rel


def main():
    if OUT.exists():
        shutil.rmtree(OUT)

    fetched, failed, textfiles, pages_raw = set(), [], {}, {}

    queue = []
    for route in PAGES:
        try:
            data, _ = fetch(SRC + route)
        except Exception as exc:
            failed.append((route, str(exc)[:50]))
            continue
        text = data.decode("utf-8", "replace")
        pages_raw[route] = text
        queue += list(find_urls(text))

    # Breadth-first over assets; textual assets are scanned for more URLs.
    while queue:
        url = queue.pop()
        if url in fetched:
            continue
        fetched.add(url)
        dest = OUT / local_path(url)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            data, ctype = fetch(url)
            dest.write_bytes(data)
        except Exception as exc:
            failed.append((url, type(exc).__name__))
            continue
        if any(k in ctype for k in TEXTUAL) or url.split("?")[0].endswith(TEXT_EXT):
            try:
                text = data.decode("utf-8", "replace")
            except Exception:
                continue
            textfiles[local_path(url)] = text
            for found in find_urls(text):
                if found not in fetched:
                    queue.append(found)

    # Resolve chunks reachable only via relative import() inside other chunks.
    site_remote = next((u.rsplit("/", 1)[0] + "/" for u in assets if "/sites/" in u), None)
    if site_remote:
        probe = site_remote + "probe.mjs"
        site_dir = (OUT / local_path(probe)).parent
        del assets[probe]
        seen = {p.name for p in site_dir.glob("*.mjs")}
        pending = []
        for chunk in site_dir.glob("*.mjs"):
            pending += REL_MJS.findall(chunk.read_text(encoding="utf-8", errors="replace"))
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            try:
                data, _ = fetch(site_remote + name)
            except Exception:
                continue
            (site_dir / name).write_bytes(data)
            rel = f"{site_dir.relative_to(OUT)}/{name}"
            assets[site_remote + name] = rel
            text = data.decode("utf-8", "replace")
            textfiles[rel] = text
            for found in REL_MJS.findall(text):
                if found not in seen:
                    pending.append(found)

    def rewrite(text):
        # Longest-first so query variants win over their bare counterparts.
        for url in sorted(assets, key=len, reverse=True):
            target = f"{ORIGIN}/{assets[url]}"
            if url in text:
                text = text.replace(url, target)
            escaped = html.escape(url)
            if escaped != url and escaped in text:
                text = text.replace(escaped, target)
        return text

    for rel, text in textfiles.items():
        path = OUT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rewrite(text), encoding="utf-8")

    for route, dest in PAGES.items():
        if route not in pages_raw:
            continue
        text = strip_framer(rewrite(pages_raw[route]).replace(SRC, ORIGIN))
        path = OUT / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    # Framer's own 404 route is not published; reuse the homepage shell so the
    # client router can still resolve unknown paths.
    if "/" in pages_raw:
        shutil.copyfile(OUT / "index.html", OUT / "404.html")

    (OUT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}/sitemap.xml\n", encoding="utf-8"
    )
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for route in PAGES:
        sitemap.append(f"  <url><loc>{ORIGIN}{route}</loc></url>")
    sitemap.append("</urlset>")
    (OUT / "sitemap.xml").write_text("\n".join(sitemap) + "\n", encoding="utf-8")

    print(f"origin : {ORIGIN}")
    print(f"output : {OUT}")
    print(f"pages  : {len(pages_raw)}/{len(PAGES)}")
    print(f"assets : {len(fetched) - len(failed)} ok / {len(failed)} failed")
    for url, err in failed[:5]:
        print(f"   FAIL {err} {str(url)[:80]}")
    return 0 if len(pages_raw) == len(PAGES) else 1


if __name__ == "__main__":
    sys.exit(main())
