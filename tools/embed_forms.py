#!/usr/bin/env python3
"""
embed_forms.py - swap Squarespace form blocks for embedded Google Forms.

Usage:
    python -I -P tools/embed_forms.py <site-dir>

Reads tools/forms.json, a map from a Squarespace form id to the Google Form
that replaces it:

    {
      "6791199fc837f91415252c8e": {
        "name": "DAF",
        "url": "https://docs.google.com/forms/d/e/<form-key>/viewform?embedded=true",
        "height": 1200
      }
    }

Every page under <site-dir> that contains a form block with one of those ids
gets the block's content replaced by an <iframe> showing the Google Form.
Safe to run repeatedly (an already embedded form is updated in place), and
mirror.py runs it automatically after refreshing the copy from Squarespace.
"""
import json
import os
import re
import sys

BLOCK_RE = re.compile(r'<div class="sqs-block website-component-block[^"]*\bform-block\b[^"]*"[^>]*>', re.I)
CONTENT_RE = re.compile(r'<div class="sqs-block-content">', re.I)
FORM_ID_RE = re.compile(r'id="form-context-([0-9a-f]+)"|data-form-id="([0-9a-f]+)"')
DIV_RE = re.compile(r'<div\b|</div>', re.I)


def find_div_end(text, start):
    """Index just past the </div> that closes the <div> starting at `start`."""
    depth = 0
    for m in DIV_RE.finditer(text, start):
        depth += 1 if m.group(0)[1] != "/" else -1
        if depth == 0:
            return m.end()
    return -1


def embed_html(form_id, form):
    name = form.get("name", "Form")
    url = form["url"].split("?")[0]
    # The forms require a Google sign-in (that is the spam protection), and a
    # browser that blocks third-party cookies may not show the sign-in inside
    # the frame, so always offer a plain link to the form as well.
    return (
        f'<div class="google-form-embed" data-form-id="{form_id}" style="max-width:720px;margin:0 auto;">'
        f'<iframe src="{url}?embedded=true" title="{name}" width="100%" height="{form.get("height", 1200)}" '
        f'frameborder="0" marginheight="0" marginwidth="0" loading="lazy" '
        f'style="display:block;width:100%;border:0;">Loading…</iframe>'
        f'<p style="text-align:center;font-size:0.85em;margin:1em 0 0;">'
        f'Trouble seeing the form? <a href="{url}" target="_blank" rel="noopener">Open it in a new tab</a>.'
        f'</p></div>'
    )


def apply(text, forms):
    """Return (new_text, number_of_forms_replaced)."""
    pieces, pos, count = [], 0, 0
    for bm in BLOCK_RE.finditer(text):
        if bm.start() < pos:
            continue
        block_end = find_div_end(text, bm.start())
        cm = CONTENT_RE.search(text, bm.end(), block_end)
        if not cm:
            continue
        content_end = find_div_end(text, cm.start())
        inner = text[cm.end():content_end - len("</div>")]
        idm = FORM_ID_RE.search(inner)
        form_id = (idm.group(1) or idm.group(2)) if idm else None
        if not form_id or form_id not in forms:
            continue
        new_inner = embed_html(form_id, forms[form_id])
        # Strip the attributes that make Squarespace's form component try to
        # initialise this block (it would throw "Form context script not found").
        opening = re.sub(r'\s+data-(?:block-scripts|definition-name|website-component-id)="[^"]*"',
                         "", bm.group(0))
        if new_inner == inner and opening == bm.group(0):
            continue
        pieces.append(text[pos:bm.start()])
        pieces.append(opening)
        pieces.append(text[bm.end():cm.end()])
        pieces.append(new_inner)
        pos = content_end - len("</div>")
        count += 1
    pieces.append(text[pos:])
    return "".join(pieces), count


def run(site_dir):
    """Apply tools/forms.json to every page under site_dir; return pages changed."""
    cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forms.json")
    if not os.path.exists(cfg):
        return 0
    with open(cfg, encoding="utf-8") as f:
        forms = json.load(f)
    changed = 0
    for root, dirs, files in os.walk(site_dir):
        dirs[:] = [d for d in dirs if d not in ("assets", "tools", ".git", ".claude")]
        for name in files:
            if not name.endswith(".html"):
                continue
            path = os.path.join(root, name)
            with open(path, encoding="utf-8") as f:
                text = f.read()
            new, n = apply(text, forms)
            if n:
                with open(path, "w", encoding="utf-8", newline="") as f:
                    f.write(new)
                changed += 1
                print(f"  {os.path.relpath(path, site_dir)}: {n} form(s) embedded", flush=True)
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(f"{run(os.path.abspath(sys.argv[1]))} page(s) changed.")
