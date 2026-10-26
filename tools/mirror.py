#!/usr/bin/env python3
"""
mirror.py - make a self-contained static copy of the Squarespace site
bildnetwork.org.

Usage:
    python -I -P tools/mirror.py <output-dir>

What it does
  1. Reads sitemap.xml and the home page, then follows every internal link it
     finds, so every public page (blog posts, category and tag pages, the
     404 page) is captured.
  2. Downloads every stylesheet, script, image, font and uploaded file the
     pages reference, including references hidden in srcset/data-src
     attributes, inline <style> blocks and JSON-escaped URLs inside scripts.
  3. Follows url() references inside downloaded CSS so fonts and background
     images used only from CSS are captured too.
  4. Rewrites every reference to a relative local path, so the copy works
     from any static host (GitHub Pages, Netlify, a plain folder).

Re-run it any time to refresh the copy from the live Squarespace site.
"""
import gzip
import hashlib
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SITE_HOST = "bildnetwork.org"
SITE = f"https://{SITE_HOST}"
# Squarespace's own hostname for this site. bildnetwork.org itself now points
# at GitHub Pages, so the live Squarespace content is crawled from this host;
# the pages it serves still link to bildnetwork.org, which is what gets
# rewritten to relative paths.
SQSP_INTERNAL_HOST = "salmon-blenny-h4hy.squarespace.com"
SOURCE = f"https://{SQSP_INTERNAL_HOST}"
ASSET_HOSTS = {
    "images.squarespace-cdn.com",
    "static1.squarespace.com",
    "static.squarespace.com",
    "assets.squarespace.com",
    "definitions.sqspcdn.com",
    "file.squarespace-cdn.com",
    "fonts.squarespace.com",
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

# Dynamic Squarespace features that cannot exist on a static host.
SKIP_PAGE_PREFIXES = ("/cart", "/search", "/api/", "/config", "/account",
                      "/checkout", "/commerce", "/static/", "/universal/",
                      "/sitemap.xml", "/robots.txt", "/rss", "/feed", "/s/")
IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".avif"}
FONT_EXTS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
FILE_EXTS = IMG_EXTS | FONT_EXTS | {".css", ".js", ".pdf", ".mp4", ".mp3",
                                    ".json", ".zip", ".doc", ".docx", ".xml"}

HOSTS_ALT = "|".join(re.escape(h) for h in
                     sorted(ASSET_HOSTS | {SITE_HOST, SQSP_INTERNAL_HOST}))
# absolute or protocol-relative URL to one of the hosts we care about
URL_RE = re.compile(r'(?:https?:)?//(?:' + HOSTS_ALT +
                    r')(?=[/?#"\'\s<>)]|$)[^\s"\'<>()\\]*')
# root-relative attribute values such as href="/s/file.pdf"
ROOTREL_RE = re.compile(
    r'''\b(?:src|href|data-src|data-image|poster|data-href)\s*=\s*(["'])'''
    r'''(/(?!/)[^"'\s<>]*)\1''', re.I)
A_HREF_RE = re.compile(r'''(<a\b[^>]*?\bhref\s*=\s*)(["'])([^"']*)\2''', re.I)
CSS_URL_RE = re.compile(r'''url\(\s*(["']?)([^"')]+)\1\s*\)''')
CSS_IMPORT_RE = re.compile(r'''@import\s+(["'])([^"']+)\1''')
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
WIN_BAD = re.compile(r'[<>:"|?*\\]')


def log(*a):
    print(*a, flush=True)


def clean(s, n=40):
    s = SAFE_RE.sub("-", s).strip("-.")
    s = re.sub(r"-{2,}", "-", s)
    return s[:n] or "file"


def normalize(u):
    """Entity-decode and make an absolute https URL."""
    u = html.unescape(u).strip()
    if u.startswith("//"):
        u = "https:" + u
    elif u.startswith("http://"):
        u = "https://" + u[7:]
    return u


def trim_match(m):
    """Cut a regex match at HTML-entity boundaries and trailing punctuation."""
    for stop in ("&quot;", "&#", "&lt;", "&gt;", "&apos;"):
        i = m.find(stop)
        if i != -1:
            m = m[:i]
    return m.rstrip(".,;:")


def fetch(url, retries=3):
    """Return (bytes, status, content_type). bytes is None on failure."""
    req_url = urllib.parse.quote(url, safe="%:/?&=+@#,;~-._!*'()$[]")
    last = None
    for i in range(retries):
        try:
            # No Accept header on purpose: with one, the image CDN negotiates
            # WebP; without it, it serves the original PNG/JPEG files.
            req = urllib.request.Request(
                req_url, headers={"User-Agent": UA,
                                  "Accept-Language": "en-US,en;q=0.9"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    data = gzip.decompress(data)
                return data, r.status, r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body = b""
            try:
                body = e.read()
                if e.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
            except Exception:
                pass
            if e.code in (404, 410, 403):
                return body, e.code, e.headers.get("Content-Type", "")
            last = e
        except Exception as e:  # network hiccup, retry
            last = e
        time.sleep(1.5 * (i + 1))
    return None, -1, str(last)


def ext_from_ctype(ctype):
    ctype = (ctype or "").split(";")[0].strip().lower()
    return {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/svg+xml": ".svg", "image/webp": ".webp", "image/x-icon": ".ico",
        "image/vnd.microsoft.icon": ".ico", "text/css": ".css",
        "application/javascript": ".js", "text/javascript": ".js",
        "font/woff2": ".woff2", "font/woff": ".woff", "application/pdf": ".pdf",
        "application/json": ".json",
    }.get(ctype, "")


def asset_local(url, ctype=""):
    """Local path (relative to the site root) for an asset URL."""
    p = urllib.parse.urlsplit(url)
    host = p.netloc.lower()
    path = urllib.parse.unquote(p.path)
    segs = [s for s in path.split("/") if s]
    name = segs[-1] if segs else "file"
    stem, ext = os.path.splitext(name)
    ext = ext.lower()
    if not ext or len(ext) > 6:
        stem, ext = name, ext_from_ctype(ctype)
    fmt = urllib.parse.parse_qs(p.query).get("format", [""])[0]
    fmt = ("-" + clean(fmt, 12)) if fmt else ""
    h8 = hashlib.sha1(url.encode()).hexdigest()[:8]

    # Names are kept short: Windows limits a full path to 260 characters.

    # Squarespace component bundles load their chunks ("18018.js",
    # "image-effect-liquid.js") from the directory of the running script, so
    # keep each component's files together and keep chunk names unchanged.
    if (host == "definitions.sqspcdn.com" and len(segs) >= 4
            and segs[0] == "website-component-definition"):
        comp = segs[2].replace("website.components.", "")
        ver = segs[3].rsplit("_", 1)[-1]
        fname = name.replace("website.components.", "")
        return f"assets/components/{clean(comp, 20)}-{clean(ver, 8)}/{clean(fname, 44)}"
    if host == "assets.squarespace.com":
        stem = re.sub(r"-min(\.[a-z]{2}-[A-Z]{2})?$", "", stem)
        return f"assets/universal/{clean(stem, 44)}-{h8}{ext}"
    if host == "static1.squarespace.com" and segs[:2] == ["static", "vta"]:
        return f"assets/template/{clean(stem, 36)}{fmt}-{h8}{ext}"
    if host == "static1.squarespace.com" and "versioned-site-css" in path:
        return f"assets/css/{clean(stem, 32)}-{h8}{ext}"
    if host in ("file.squarespace-cdn.com", "fonts.squarespace.com") or ext in FONT_EXTS:
        return f"assets/fonts/{clean(stem, 32)}-{h8}{ext}"
    if host == SITE_HOST and segs[:1] == ["s"]:
        return f"assets/files/{clean(stem, 40)}-{h8}{ext}"
    if ext in IMG_EXTS or host == "images.squarespace-cdn.com":
        return f"assets/img/{clean(stem, 32)}{fmt}-{h8}{ext or '.bin'}"
    cat = {".css": "css", ".js": "js"}.get(ext, "files")
    return f"assets/{cat}/{clean(stem, 32)}{fmt}-{h8}{ext or '.bin'}"


def is_asset_url(url):
    p = urllib.parse.urlsplit(url)
    host = p.netloc.lower()
    if host in ASSET_HOSTS:
        return p.path not in ("", "/")
    if host == SITE_HOST:
        path = p.path
        ext = os.path.splitext(path)[1].lower()
        return path.startswith("/s/") or ext in FILE_EXTS
    return False


def page_local(path):
    """Local file for a site page path such as /thenetwork/tag/Atlanta+GA."""
    path = urllib.parse.unquote(path).strip("/")
    if not path:
        return "index.html"
    parts = [WIN_BAD.sub("-", s) for s in path.split("/")]
    return "/".join(parts) + "/index.html"


def rel_link(from_local, to_local, is_dir=False):
    start = os.path.dirname(from_local) or "."
    target = (os.path.dirname(to_local) or ".") if is_dir else to_local
    r = os.path.relpath(target, start).replace(os.sep, "/")
    if is_dir:
        r = "./" if r == "." else r.rstrip("/") + "/"
    return urllib.parse.quote(r, safe="/+~-._")


def site_page_path(href):
    """Return (path, fragment) if href points at a page on this site, else None."""
    u = html.unescape(href).strip()
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith(("http://", "https://")):
        p = urllib.parse.urlsplit(u)
        if p.netloc.lower() not in (SITE_HOST, "www." + SITE_HOST, SQSP_INTERNAL_HOST):
            return None
        path, query, frag = p.path or "/", p.query, p.fragment
    elif u.startswith("/"):
        p = urllib.parse.urlsplit(u)
        path, query, frag = p.path, p.query, p.fragment
    else:
        return None
    if query:
        return None  # ?format=rss, ?offset=... are dynamic; leave untouched
    if path.rstrip("/").lower().startswith(SKIP_PAGE_PREFIXES):
        return None
    if os.path.splitext(path)[1].lower() in FILE_EXTS:
        return None
    return path, frag


class Mirror:
    def __init__(self, out):
        self.out = out
        self.pages = {}        # path -> html text
        self.page_file = {}    # path -> local file
        self.assets = {}       # normalized url -> (bytes, ctype, local)
        self.failed = {}       # normalized url -> reason
        self.css_text = {}     # normalized url -> text
        self.dir_aliases = {}  # remote directory url -> local directory

    # ---- phase 1: pages -------------------------------------------------
    def crawl_pages(self):
        queue = ["/"]
        data, st, _ = fetch(SOURCE + "/sitemap.xml")
        if data:
            for loc in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", data.decode("utf-8", "replace")):
                r = site_page_path(loc)
                if r:
                    queue.append(r[0])
        seen = set()
        while queue:
            path = queue.pop(0)
            key = path.rstrip("/") or "/"
            if key in seen:
                continue
            seen.add(key)
            data, st, ctype = fetch(SOURCE + key)
            if data is None or st != 200 or "html" not in ctype:
                log(f"  page {key}: status {st} ({ctype}) - skipped")
                continue
            text = data.decode("utf-8", "replace")
            self.pages[key] = text
            self.page_file[key] = page_local(key)
            log(f"  page {key} -> {self.page_file[key]} ({len(data)//1024} KB)")
            for m in A_HREF_RE.finditer(text):
                r = site_page_path(m.group(3))
                if r and (r[0].rstrip("/") or "/") not in seen:
                    queue.append(r[0])
        # Squarespace's custom 404 page, served by GitHub Pages as 404.html
        data, st, ctype = fetch(SOURCE + "/this-page-does-not-exist-404-probe")
        if data and st == 404 and "html" in ctype:
            self.pages["/404"] = data.decode("utf-8", "replace")
            self.page_file["/404"] = "404.html"
            log("  page /404 -> 404.html")

    # ---- phase 2: assets ------------------------------------------------
    def find_asset_urls(self, text, base_url=None, css=False):
        found = set()
        probe = text.replace("\\/", "/")
        for m in URL_RE.finditer(probe):
            u = normalize(trim_match(m.group(0)))
            if is_asset_url(u):
                found.add(u)
        if css:
            for m in list(CSS_URL_RE.finditer(probe)) + list(CSS_IMPORT_RE.finditer(probe)):
                ref = m.group(2).strip()
                if ref.startswith(("data:", "#", "about:")):
                    continue
                u = normalize(urllib.parse.urljoin(base_url, ref))
                if is_asset_url(u):
                    found.add(u)
        else:
            for m in ROOTREL_RE.finditer(probe):
                u = SITE + html.unescape(m.group(2))
                if is_asset_url(u):
                    found.add(u)
        return found

    def download(self, urls, local_for=None):
        urls = [u for u in urls if u not in self.assets and u not in self.failed]
        if not urls:
            return []
        log(f"  downloading {len(urls)} assets ...")

        def one(u):
            # files uploaded to the site (/s/...) live on the Squarespace host
            src = SOURCE + u[len(SITE):] if u.startswith(SITE + "/") else u
            data, st, ctype = fetch(src)
            return u, data, st, ctype

        new = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            for u, data, st, ctype in ex.map(one, urls):
                if data is None or st != 200 or ("text/html" in ctype and not u.endswith(".html")):
                    self.failed[u] = f"status {st} {ctype}"
                    continue
                local = (local_for or {}).get(u) or asset_local(u, ctype)
                self.assets[u] = (data, ctype, local)
                new.append(u)
                if local.endswith(".css") or "text/css" in ctype:
                    self.css_text[u] = data.decode("utf-8", "replace")
        return new

    def crawl_assets(self):
        wanted = set()
        for path, text in self.pages.items():
            wanted |= self.find_asset_urls(text)
        pending = self.download(wanted)
        # follow url() references inside CSS until nothing new appears
        while pending:
            more = set()
            for u in pending:
                if u in self.css_text:
                    more |= self.find_asset_urls(self.css_text[u], base_url=u, css=True)
            pending = self.download(more)
        self.capture_template_chunks()

    def capture_template_chunks(self):
        """The template's site-bundle lazy-loads feature chunks (lightbox,
        galleries, section dividers, ...) from
        Static.SQUARESPACE_CONTEXT.templateScriptsRootUrl + "scripts/<name>.<hash>.js".
        Download them next to the bundle and point the root URL at the copy.
        Hashes are shortened to 8 characters (and the bundle's chunk table
        patched to match) to keep Windows paths under 260 characters."""
        bundle = next((u for u in self.assets
                       if "/static/vta/" in u and "site-bundle" in u and u.endswith(".js")), None)
        if not bundle:
            return
        data, ctype, local = self.assets[bundle]
        text = data.decode("utf-8", "replace")
        m = re.search(r'"scripts/"\+\((\{[^}]*\})\[(\w)\]\|\|\2\)\+"\."\+(\{[^}]*\})\[\2\]\+"\.js"', text)
        if not m:
            log("  template chunk table not found in site bundle; chunks stay on the CDN")
            return
        names = dict(re.findall(r'(\d+):"([^"]*)"', m.group(1)))
        hashes = dict(re.findall(r'(\d+):"([^"]*)"', m.group(3)))
        root = bundle.rsplit("/scripts/", 1)[0] + "/scripts/"
        local_for = {}
        for cid, h in hashes.items():
            name = names.get(cid, cid)
            if name.endswith("-editor"):      # only used inside the Squarespace editor
                continue
            local_for[f"{root}{name}.{h}.js"] = f"assets/template/scripts/{name}.{h[:8]}.js"
        log(f"  template chunks: {len(local_for)} referenced by the site bundle")
        self.download(set(local_for), local_for)
        short = "{" + ",".join(f'{cid}:"{h[:8]}"' for cid, h in hashes.items()) + "}"
        text = text.replace(m.group(3), short, 1)
        self.assets[bundle] = (text.encode("utf-8"), ctype, local)
        self.dir_aliases[root] = "assets/template/scripts/"
        self.failed.pop(root, None)

    # ---- phase 3: rewrite and write -------------------------------------
    def replacements(self, text, from_local, base_url=None, css=False):
        """List of (raw-string-as-it-appears, replacement) pairs."""
        pairs = {}
        probe = text.replace("\\/", "/")
        for m in URL_RE.finditer(probe):
            raw = trim_match(m.group(0))
            u = normalize(raw)
            if u in self.assets:
                pairs[raw] = rel_link(from_local, self.assets[u][2])
            elif u in self.dir_aliases:
                pairs[raw] = rel_link(from_local, self.dir_aliases[u] + "x", is_dir=True)
        if css:
            for m in list(CSS_URL_RE.finditer(probe)) + list(CSS_IMPORT_RE.finditer(probe)):
                ref = m.group(2).strip()
                u = normalize(urllib.parse.urljoin(base_url, ref))
                if u in self.assets and ref not in pairs:
                    pairs[ref] = rel_link(from_local, self.assets[u][2])
        else:
            for m in ROOTREL_RE.finditer(probe):
                raw = m.group(2)
                u = SITE + html.unescape(raw)
                if u in self.assets:
                    pairs[raw] = rel_link(from_local, self.assets[u][2])
        return sorted(pairs.items(), key=lambda kv: -len(kv[0]))

    def apply(self, text, pairs):
        for raw, rep in pairs:
            text = text.replace(raw, rep)
            esc_raw = raw.replace("/", "\\/")
            if esc_raw != raw and esc_raw in text:
                text = text.replace(esc_raw, rep.replace("/", "\\/"))
        return text

    def rewrite_page(self, path, text):
        local = self.page_file[path]

        def fix_href(m):
            r = site_page_path(m.group(3))
            if not r:
                return m.group(0)
            target, frag = r
            key = target.rstrip("/") or "/"
            if key not in self.page_file:
                return m.group(0)
            link = rel_link(local, self.page_file[key], is_dir=True)
            if frag:
                link += "#" + frag
            return f"{m.group(1)}{m.group(2)}{link}{m.group(2)}"

        text = A_HREF_RE.sub(fix_href, text)
        return self.apply(text, self.replacements(text, local))

    def write(self, local, data):
        full = os.path.join(self.out, local)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)

    def write_all(self):
        for path, text in self.pages.items():
            self.write(self.page_file[path], self.rewrite_page(path, text).encode("utf-8"))
        for u, (data, ctype, local) in self.assets.items():
            if u in self.css_text:
                data = self.apply(self.css_text[u],
                                  self.replacements(self.css_text[u], local, base_url=u, css=True)
                                  ).encode("utf-8")
            self.write(local, data)
        self.write(".nojekyll", b"")
        # Swap the Squarespace form blocks for the Google Forms listed in
        # tools/forms.json (this script runs with -P, so import explicitly).
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import embed_forms
        log(f"Embedded Google Forms in {embed_forms.run(self.out)} page(s).")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = os.path.abspath(sys.argv[1])
    os.makedirs(out, exist_ok=True)
    m = Mirror(out)
    log("Crawling pages ...")
    m.crawl_pages()
    log(f"{len(m.pages)} pages. Collecting assets ...")
    m.crawl_assets()
    log(f"{len(m.assets)} assets downloaded, {len(m.failed)} failed.")
    for u, why in sorted(m.failed.items()):
        log(f"  FAILED {u}: {why}")
    log("Writing files ...")
    m.write_all()
    total = sum(len(d) for d, _, _ in m.assets.values())
    log(f"Done: {len(m.pages)} pages, {len(m.assets)} assets ({total/1e6:.1f} MB) -> {out}")


if __name__ == "__main__":
    main()
