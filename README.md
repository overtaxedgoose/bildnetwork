# bildnetwork.org

A self-contained static copy of <https://bildnetwork.org>, captured from
Squarespace so the site can be hosted and edited outside Squarespace.

Everything the site needs is in this repository: every page, the site CSS,
Squarespace's platform scripts, images in every size the pages use, fonts,
and the lazily loaded feature scripts. Nothing is fetched from Squarespace
at runtime.

## Layout

| Path | What it is |
| --- | --- |
| `index.html` | Home page (`/`) |
| `daf/`, `events/`, `connect-with-bild/`, ... | One folder per page, each with an `index.html` |
| `thenetwork/` | The blog: post, category and tag pages |
| `404.html` | The site's not-found page (GitHub Pages serves it automatically) |
| `assets/css/` | The site's own stylesheet |
| `assets/template/` | The Squarespace template bundle and its feature chunks |
| `assets/universal/` | Squarespace platform scripts and styles |
| `assets/components/` | Squarespace block components (forms, image effects, social links, ...) |
| `assets/img/`, `assets/fonts/` | Images (each size the pages reference) and web fonts |
| `tools/mirror.py` | The script that produced all of the above |

All links and asset references are relative, so the site works from the
root of a domain, from a sub-path such as `username.github.io/bildnetwork/`,
or straight from a folder on disk.

## Preview locally

```bash
python -m http.server 8123 --bind 127.0.0.1
```

Then open <http://127.0.0.1:8123/>. Use `127.0.0.1` rather than `localhost`:
the Squarespace template bundle treats a host named `localhost` specially and
looks for its scripts in the wrong place.

## Refresh the copy from Squarespace

While the Squarespace site is still live, re-run the mirror to pick up any
content changes:

```bash
python -I -P tools/mirror.py .
```

It re-crawls the sitemap and every internal link, downloads all assets again
and rewrites the pages. Commit the result.

## Hosting on GitHub Pages

The repository is published with GitHub Pages from the `main` branch, root
folder. To serve it at `bildnetwork.org`:

1. Add a file named `CNAME` at the repository root containing `bildnetwork.org`
   (or set the custom domain in the repository's Pages settings, which creates
   that file).
2. At the DNS provider, point `bildnetwork.org` at GitHub Pages with four `A`
   records (`185.199.108.153`, `185.199.109.153`, `185.199.110.153`,
   `185.199.111.153`) and `www` as a `CNAME` to `overtaxedgoose.github.io`.
3. Turn on "Enforce HTTPS" in the Pages settings once the certificate is issued.

## What a static copy cannot do

These parts of the page depend on Squarespace's servers and stop working
once the site is served from here:

- **Forms** on the DAF and Connect pages post to Squarespace's form API.
  Replace them with a form service (Formspree, Netlify Forms, Google Forms,
  Tally, ...) before switching DNS.
- **Donate** links go to the Squarespace checkout at
  `salmon-blenny-h4hy.squarespace.com` and only work while that Squarespace
  site exists.
- **Cart, search and account** pages (`/cart`, `/search`, `/account`) are not
  included; the site does not use them.
- **Analytics** calls to `/api/census/...` fail silently. Add your own
  analytics snippet if wanted.
- **RSS** links (`/thenetwork?format=rss`) still point at the Squarespace feed.
