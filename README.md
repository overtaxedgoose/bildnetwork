# bildnetwork.org

The static site behind <https://bildnetwork.org>, captured from Squarespace
so it can be hosted and edited outside Squarespace. It is published with
GitHub Pages from the `main` branch of this repository.

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
| `CNAME` | Tells GitHub Pages to serve the site at `bildnetwork.org` |
| `assets/css/` | The site's own stylesheet |
| `assets/template/` | The Squarespace template bundle and its feature chunks |
| `assets/universal/` | Squarespace platform scripts and styles |
| `assets/components/` | Squarespace block components (forms, image effects, social links, ...) |
| `assets/img/`, `assets/fonts/` | Images (each size the pages reference) and web fonts |
| `tools/mirror.py` | Re-captures the site from Squarespace |
| `tools/embed_forms.py`, `tools/forms.json` | Swap the Squarespace form blocks for Google Forms |

All links and asset references are relative, so the site works from the
root of a domain, from a sub-path such as `username.github.io/bildnetwork/`,
or straight from a folder on disk.

## Editing

Edit the HTML in place and push to `main`; GitHub Pages republishes within a
minute or two. To preview locally:

```bash
python -m http.server 8123 --bind 127.0.0.1
```

Then open <http://127.0.0.1:8123/>. Use `127.0.0.1` rather than `localhost`:
the Squarespace template bundle treats a host named `localhost` specially and
looks for its scripts in the wrong place.

## Forms

The DAF and Connect pages originally used Squarespace form blocks, which
only work on Squarespace. They are replaced by embedded Google Forms owned
by patrick@jajehgroup.com. `tools/forms.json` maps each Squarespace form id
to the Google Form that takes its place:

| Page | Google Form | Replaces Squarespace form id |
| --- | --- | --- |
| `daf/` | "DAF Form": Name, Phone, DAF Goal, newsletter opt-in | `6791199fc837f91415252c8e` |
| `connect-with-bild/` | "Enrollment": Name, Entity Name, Year Established, Industry, Website, Zipcode, Revenue, Project, Interests | `65a17ec67a678e53eb0fe693` |

Both forms collect the respondent's verified Google email, limit each person
to one response and only accept responses from signed-in Google accounts;
that sign-in requirement is the spam protection. Because a browser that
blocks third-party cookies may not show the sign-in inside the embedded
frame, every embed also carries an "open it in a new tab" link.

Responses land in each form's Responses tab (and a linked Google Sheet if
you add one there). To be emailed about new responses, open the form,
Responses, the three-dot menu, "Get email notifications for new responses".

To point a page at a different form, change its `url` in `tools/forms.json`
(the responder link, with or without `?embedded=true`), adjust `height` to
the form's length, and run:

```bash
python -I -P tools/embed_forms.py .
```

## Refresh the copy from Squarespace

While the Squarespace site still exists, re-run the mirror to pick up any
content changes made there. It crawls Squarespace's own hostname for the
site (`salmon-blenny-h4hy.squarespace.com`), since `bildnetwork.org` now
serves this copy:

```bash
python -I -P tools/mirror.py .
```

It re-crawls the sitemap and every internal link, downloads all assets again,
rewrites the pages and re-applies the Google Forms. Commit the result.

## Domain and DNS

The domain is registered at Namecheap. `bildnetwork.org` points at GitHub
Pages and HTTPS is enforced. Two DNS records are still worth tidying up:

- The apex has one `A` record (`185.199.110.153`). GitHub recommends all four:
  `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`.
- `www` is still a `CNAME` to Squarespace (`ext-cust.squarespace.com`), which
  redirects to `bildnetwork.org` for now but will break when the Squarespace
  site is cancelled. Change it to a `CNAME` to `overtaxedgoose.github.io`.

Email for `@bildnetwork.org` is handled by Namecheap's free email forwarding
(the `eforward*.registrar-servers.com` MX records). Forwarders, including a
catch-all, are managed in the Namecheap dashboard under Domain List > Manage >
Redirect Email.

## What still depends on Squarespace

- **Donate** links go to the Squarespace checkout at
  `salmon-blenny-h4hy.squarespace.com` and only work while that Squarespace
  site exists.
- **RSS** links (`/thenetwork?format=rss`) still point at the Squarespace feed.
- **Cart, search and account** pages (`/cart`, `/search`, `/account`) are not
  included; the site does not use them.
- **Analytics** calls to `/api/census/...` fail silently. Add your own
  analytics snippet if wanted.
