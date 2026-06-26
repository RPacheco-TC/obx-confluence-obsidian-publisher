#!/usr/bin/env python3
"""confluence_publish.py — publish a folder of Markdown docs to Confluence Cloud.

Publishes an Obsidian-style Markdown doc set as a page tree under ONE parent page.
Reuses md_to_confluence.py for Markdown -> HTML, then post-processes into valid
Confluence storage format (code macros; info/note/tip/warning panels; autolink +
ampersand fixes; [[wikilinks]] -> page links), renders Mermaid to PNG and uploads
them as attachments, validates each body as XML, and creates or updates pages
idempotently (matched by title).

Safe by construction: it only ever creates/updates pages UNDER the parent you
pass, and never deletes anything.

Usage:
  python3 confluence_publish.py DOCS_DIR --space KEY --parent PAGE_ID [--dry-run]

  DOCS_DIR   folder of "NN - Title.md" files, with an optional "In Situ/" subfolder
  --space    Confluence space KEY (e.g. ~yourname for a personal space, or ENG)
  --parent   ID of the page to publish everything under
  --dry-run  print the CREATE/UPDATE plan and write nothing

Credentials come from the environment only (never commit them):
  CONFLUENCE_BASE_URL  (e.g. https://your-company.atlassian.net/wiki)
  CONFLUENCE_EMAIL
  CONFLUENCE_API_TOKEN

Not yet implemented (contributions welcome): a state.json page map (this matches
by title), content-hash skip of unchanged pages, exact heading-anchor links, and
--prune of pages whose source was removed.
"""
from __future__ import annotations
import os, re, json, base64, importlib.util, pathlib, argparse
import html as ihtml
import urllib.request, urllib.error, urllib.parse
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent

# --- reuse the existing converter for the bulk Markdown -> HTML -------------
_spec = importlib.util.spec_from_file_location("mdc", HERE / "md_to_confluence.py")
mdc = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(mdc)

# --------------------------------------------------------------------------- #
#  Storage-format transform (Markdown -> Confluence storage XHTML)
# --------------------------------------------------------------------------- #

# Obsidian callout type -> Confluence macro (info=blue, note=yellow, tip=green, warning=red)
CALLOUT_MACRO = {
    "info": "info", "note": "info", "abstract": "info", "summary": "info",
    "tldr": "info", "question": "info", "faq": "info", "quote": "info",
    "cite": "info", "example": "info", "todo": "info",
    "tip": "tip", "hint": "tip", "success": "tip", "check": "tip", "done": "tip",
    "important": "note",
    "warning": "warning", "caution": "warning", "attention": "warning",
    "danger": "warning", "error": "warning", "failure": "warning",
    "fail": "warning", "bug": "warning",
}

_CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\][+-]?\s*(.*)$")


def _extract_callouts(md: str):
    """Pull callout blocks out of the markdown, returning (md_with_tokens, macros).

    Each callout becomes a Confluence panel macro; in the markdown it is replaced
    by a placeholder paragraph the bulk converter passes through untouched."""
    lines = md.split("\n")
    out, macros, i = [], {}, 0
    while i < len(lines):
        m = _CALLOUT_RE.match(lines[i])
        if not m:
            out.append(lines[i]); i += 1; continue
        ctype = m.group(1).lower()
        title = m.group(2).strip()
        i += 1
        body = []
        while i < len(lines) and lines[i].startswith(">"):
            body.append(re.sub(r"^>\s?", "", lines[i])); i += 1
        macro = CALLOUT_MACRO.get(ctype, "info")
        body_html = mdc.convert_markdown_to_html("\n".join(body)) if body else ""
        title_html = f"<p><strong>{mdc.process_inline(title)}</strong></p>\n" if title else ""
        token = f"xCALLOUT{len(macros)}x"
        macros[token] = (
            f'<ac:structured-macro ac:name="{macro}"><ac:rich-text-body>\n'
            f"{title_html}{body_html}\n"
            f"</ac:rich-text-body></ac:structured-macro>"
        )
        out += ["", token, ""]
    return "\n".join(out), macros


def _fix_autolinks(html: str) -> str:
    return re.sub(r"<(https?://[^>\s]+)>", r'<a href="\1">\1</a>', html)


def _escape_bare_amp(html: str) -> str:
    return re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#x?[0-9a-fA-F]+);)", "&amp;", html)


def _code_blocks_to_macro(html: str) -> str:
    def repl(m):
        text = ihtml.unescape(m.group(1)).rstrip("\n")
        text = text.replace("]]>", "]]]]><![CDATA[>")  # CDATA-safe
        return ('<ac:structured-macro ac:name="code"><ac:plain-text-body>'
                f"<![CDATA[{text}]]></ac:plain-text-body></ac:structured-macro>")
    return re.sub(r"<pre><code>(.*?)</code></pre>", repl, html, flags=re.S)


_VALIDATE_WRAP = ('<root xmlns:ac="urn:ac" xmlns:ri="urn:ri">{}</root>')


def validate_storage(html: str) -> None:
    """Raise ET.ParseError with a precise location if the body is not well-formed."""
    ET.fromstring(_VALIDATE_WRAP.format(html))


# --- wikilinks -> Confluence page links ------------------------------------
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _wikilink_macro(target_title: str, display: str) -> str:
    t = target_title.replace('"', "&quot;")
    return (f'<ac:link><ri:page ri:content-title="{t}" />'
            f"<ac:plain-text-link-body><![CDATA[{display}]]></ac:plain-text-link-body></ac:link>")


def _extract_wikilinks(md: str):
    """Replace [[Target]], [[Target#Anchor]], [[Target|alias]] with tokens + ac:link.

    Page-level links by title (the published title == the wikilink target). The
    heading #anchor is dropped for now (Confluence heading anchors are a separate
    scheme — D9); the link still lands on the right page."""
    links = {}

    def repl(m):
        content = m.group(1).strip()
        alias = None
        if "|" in content:
            content, alias = (s.strip() for s in content.split("|", 1))
        target = content.split("#", 1)[0].strip()
        display = alias if alias else content
        token = f"xLINK{len(links)}x"
        links[token] = _wikilink_macro(target, display)
        return token

    return _WIKILINK_RE.sub(repl, md), links


# --- rendered mermaid <img> -> attachment + ac:image -----------------------
_IMG_RE = re.compile(r'<img src="img/([^"]+)"[^>]*/>')


def _images_to_attachments(html: str, img_dir):
    names = []

    def repl(m):
        names.append(m.group(1))
        return f'<ac:image><ri:attachment ri:filename="{m.group(1)}" /></ac:image>'

    html = _IMG_RE.sub(repl, html)
    atts = [(fn, str(pathlib.Path(img_dir) / fn)) for fn in names]
    return html, atts


def md_to_storage(md: str, img_dir=None):
    """Markdown -> (storage XHTML, [(attachment_filename, filepath), ...]).

    img_dir, when given, is where Mermaid PNGs are rendered (and uploaded from)."""
    md = mdc.strip_frontmatter(md)
    md, links = _extract_wikilinks(md)        # before conversion (converter flattens them)
    md, macros = _extract_callouts(md)
    prev_dir, prev_rel = mdc._current_img_dir, mdc._current_img_rel
    if img_dir is not None:
        pathlib.Path(img_dir).mkdir(parents=True, exist_ok=True)
        mdc._current_img_dir = pathlib.Path(img_dir); mdc._current_img_rel = "img"
    try:
        html = mdc.convert_markdown_to_html(md)   # renders Mermaid to PNG when img_dir set
    finally:
        mdc._current_img_dir, mdc._current_img_rel = prev_dir, prev_rel
    for token, macro in macros.items():
        html = html.replace(f"<p>{token}</p>", macro)
    html, atts = _images_to_attachments(html, img_dir) if img_dir else (html, [])
    html = _fix_autolinks(html)
    html = _escape_bare_amp(html)
    html = _code_blocks_to_macro(html)        # last: creates CDATA the amp-escape must not touch
    for token, macro in links.items():
        html = html.replace(token, macro)
    validate_storage(html)
    return html, atts


# --------------------------------------------------------------------------- #
#  Confluence Cloud REST client (env auth)
# --------------------------------------------------------------------------- #

def _cfg():
    return (os.environ["CONFLUENCE_BASE_URL"].rstrip("/"),
            os.environ["CONFLUENCE_EMAIL"], os.environ["CONFLUENCE_API_TOKEN"])


def _auth_header():
    _, email, token = _cfg()
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def _req(method, url, data=None, headers=None):
    h = {"Authorization": _auth_header(), "Accept": "application/json"}
    if headers:
        h.update(headers)
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(r, timeout=60) as resp:
        body = resp.read().decode()
        return resp.status, (json.loads(body) if body else {})


def get_page(page_id):
    base, *_ = _cfg()
    return _req("GET", f"{base}/api/v2/pages/{page_id}?body-format=storage")[1]


def create_page(space_id, parent_id, title, storage):
    base, *_ = _cfg()
    payload = {"spaceId": space_id, "status": "current", "title": title,
               "parentId": parent_id,
               "body": {"representation": "storage", "value": storage}}
    return _req("POST", f"{base}/api/v2/pages",
                json.dumps(payload).encode(), {"Content-Type": "application/json"})[1]


def update_page(page_id, title, storage, version_message=""):
    base, *_ = _cfg()
    cur = get_page(page_id)
    payload = {"id": str(page_id), "status": "current", "title": title,
               "body": {"representation": "storage", "value": storage},
               "version": {"number": cur["version"]["number"] + 1, "message": version_message}}
    return _req("PUT", f"{base}/api/v2/pages/{page_id}",
                json.dumps(payload).encode(), {"Content-Type": "application/json"})[1]


def upload_attachment(page_id, filepath, filename):
    """v1 multipart attachment upload (re-upload to same filename updates in place)."""
    base, *_ = _cfg()
    boundary = "----confluencepublishboundary"
    data = pathlib.Path(filepath).read_bytes()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n", data, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return _req("POST", f"{base}/rest/api/content/{page_id}/child/attachment", body,
                {"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "X-Atlassian-Token": "no-check"})[1]


def existing_attachment_names(page_id):
    """Filenames already attached to a page (so we skip re-uploading content-hashed PNGs)."""
    base, *_ = _cfg()
    try:
        _, d = _req("GET", f"{base}/api/v2/pages/{page_id}/attachments?limit=250")
    except urllib.error.HTTPError:
        return set()
    return {a.get("title") for a in d.get("results", [])}


def find_page_id_by_title(space_id, title):
    base, *_ = _cfg()
    _, d = _req("GET", f"{base}/api/v2/spaces/{space_id}/pages?limit=250")
    for p in d.get("results", []):
        if p.get("title") == title:
            return p["id"]
    return None


def resolve_space_id(space_key):
    """Resolve a space KEY (e.g. ~yourname or ENG) to its numeric space id."""
    base, *_ = _cfg()
    _, d = _req("GET", f"{base}/api/v2/spaces?keys={urllib.parse.quote(space_key)}")
    results = d.get("results", [])
    if not results:
        raise SystemExit(f"Space not found for key: {space_key}")
    return results[0]["id"]


def publish_page(space_id, parent_id, title, md, img_dir, dry_run=False):
    """Idempotent create/update of one page + upload of its rendered diagrams."""
    html, atts = md_to_storage(md, img_dir)   # always convert + validate (catches errors early)
    pid = find_page_id_by_title(space_id, title)
    action = "UPDATE" if pid else "CREATE"
    if dry_run:
        return action, pid, atts
    if pid:
        update_page(pid, title, html, "republish")
    else:
        pid = create_page(space_id, parent_id, title, html)["id"]
    existing = existing_attachment_names(pid) if atts else set()
    for fn, fp in atts:                       # attach AFTER the page exists
        if fn in existing:                    # content-hashed name already present -> identical, skip
            continue
        upload_attachment(pid, fp, fn)
    return action, pid, atts


def publish_set(regen_dir, space_id, parent_id, img_dir, dry_run=False):
    """Publish a whole doc-set folder: numbered pages under the parent, In Situ
    docs under an 'In Situ' container page. Idempotent (create-or-update by title)."""
    regen = pathlib.Path(regen_dir)
    report = []
    for f in sorted(regen.glob("*.md")):                     # 00..NN top-level
        action, pid, atts = publish_page(space_id, parent_id, f.stem, f.read_text(), img_dir, dry_run)
        report.append((f.stem, action, len(atts)))
    insitu = regen / "In Situ"
    if insitu.is_dir():
        cid = find_page_id_by_title(space_id, "In Situ")
        if not cid and not dry_run:
            cid = create_page(space_id, parent_id, "In Situ",
                              "<p>Stack-specific deep-dive docs for this repository.</p>")["id"]
        if not cid:
            report.append(("In Situ", "CREATE", 0))          # container page would be created
        for f in sorted(insitu.glob("*.md")):
            action, pid, atts = publish_page(space_id, cid or parent_id, f.stem, f.read_text(), img_dir, dry_run)
            report.append(("In Situ/" + f.stem, action, len(atts)))
    return report


# --------------------------------------------------------------------------- #
#  CLI
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(
        description="Publish a folder of Markdown docs to Confluence Cloud under one parent page.")
    ap.add_argument("docs_dir", help='folder of "NN - Title.md" docs (optional "In Situ/" subfolder)')
    ap.add_argument("--space", required=True, help="Confluence space KEY (e.g. ~yourname or ENG)")
    ap.add_argument("--parent", required=True, help="ID of the parent page to publish under")
    ap.add_argument("--img-dir", default=None,
                    help="where to render Mermaid PNGs (default: <docs_dir>/.img)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the CREATE/UPDATE plan and write nothing")
    args = ap.parse_args()

    missing = [v for v in ("CONFLUENCE_BASE_URL", "CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN")
               if not os.environ.get(v)]
    if missing:
        raise SystemExit("Missing environment variable(s): " + ", ".join(missing))
    if not pathlib.Path(args.docs_dir).is_dir():
        raise SystemExit(f"Not a folder: {args.docs_dir}")

    space_id = resolve_space_id(args.space)
    img_dir = args.img_dir or str(pathlib.Path(args.docs_dir) / ".img")
    report = publish_set(args.docs_dir, space_id, args.parent, img_dir, dry_run=args.dry_run)

    print(f"\n{'ACTION':7} {'DIAGRAMS':8} TITLE")
    for title, action, n in report:
        print(f"{action:7} {n:<8} {title}")
    mode = "DRY-RUN (nothing written)" if args.dry_run else "published"
    print(f"\n{len(report)} pages {mode} — space {args.space}, parent {args.parent}")


if __name__ == "__main__":
    main()
