# Known Issues

Known bugs, limitations, and confirmed workarounds for `confluence-docs-publisher`.
Each entry includes a **TODO** tracking follow-up work.

---

## SSL certificate error on macOS (`CERTIFICATE_VERIFY_FAILED`)

### Symptom

Publishing fails immediately with:

```
ssl.SSLCertVerificationError: CERTIFICATE_VERIFY_FAILED
```

### Root cause

The **python.org** installer builds Python with its own CA bundle, but does not
install it by default. Until the bundle is installed, TLS connections (including
to Atlassian) fail.

Apple's system Python (`/usr/bin/python3`) does **not** have this problem — it
uses the system keychain.

### Quickest fix

Use the system Python:

```bash
/usr/bin/python3 confluence_publish.py ...
```

No install required. Works as-is on macOS.

### If you must use the python.org build

Run the CA-bundle installer that ships with it (adjust the version number):

```bash
/Applications/Python\ 3.x/Install\ Certificates.command
```

Double-clicking **Install Certificates.command** inside **Applications → Python 3.x**
does the same thing. Equivalent one-liner:

```bash
pip install --upgrade certifi
```

Confirm the fix before re-running the full publish:

```bash
python3 -c "import urllib.request; urllib.request.urlopen('https://www.atlassian.com'); print('TLS OK')"
```

### TODO

- [ ] **Promote `/usr/bin/python3` as the recommended interpreter** in the README
  troubleshooting section — it requires zero setup for most macOS users. Move it
  to the top of the fix, before the CA-bundle instructions.
- [ ] Make the version reference in the README version-agnostic (`Python 3.x`
  instead of a hardcoded minor version).

---

## Mermaid images show "Preview not available" in Confluence edit mode

### Symptom

Mermaid diagrams render correctly in Confluence **view mode** but appear as grey
"Preview not available" placeholders in **edit mode**. They cannot be resized
through the editor.

### Root cause

Confluence's editor cannot inline-preview attachment images referenced via the
`ac:image` / `ri:attachment` storage macro. This is a Confluence limitation, not
a tool bug. The images are present and correct; the editor just cannot render
them in the editing surface.

### Confirmed workaround

> **⚠️ Do all replacements before saving.**
> If you replace some images and save, the remaining attachment-referenced images
> lose their rendering too. Complete all replacements in one editing session, then
> save once.

1. **In view mode**, open every diagram image in a separate browser tab
   (right-click → Open image in new tab). This loads the actual PNG from
   Confluence's CDN into each tab.
2. Enter **edit mode**. The images show as "Preview not available".
3. For each image: switch to its tab, select and copy the PNG
   (Cmd+A / Ctrl+A then Cmd+C / Ctrl+C), then paste it in place of the
   placeholder in the editor.
4. Repeat for every image on the page.
5. **Save once** after all replacements are done. All images render correctly.

### TODO

- [ ] Investigate whether the `ac:image` macro supports a `width` attribute at
  publish time (e.g. `<ac:image ac:width="700"><ri:attachment ri:filename="..."/></ac:image>`).
  If so, add an `--img-width` CLI option to `confluence_publish.py` so the
  publisher sets a sensible default width on every diagram — eliminating most
  resize needs and reducing how often users hit the edit-mode limitation.
- [ ] Add this known limitation and workaround to the README troubleshooting
  section.

---

## Wikilink inside a code block breaks XML on publish

### Symptom

Publishing a document that contains a `[[wikilink]]` literally written inside a
fenced code block (` ``` `) fails with an XML parse error — mismatched tag — and
the entire publish aborts.

### Root cause

The wikilink extractor ran over the full document text **before** code fences
were masked. A `[[wikilink]]` inside a ` ``` ` block was extracted and converted
to an `<ac:link>` macro, which was then injected inside a `CDATA` section (where
the converter had already placed the code block content). `CDATA` does not allow
XML tags; the `<ac:link>` markup produced a mismatched-tag error that failed
`validate_storage()` before anything was sent to Confluence.

First encountered with a RabbitMQ document that had a `[[wikilink]]` example
inside a code fence.

### Fix — merged in [PR #1](../../pull/1) (2026-07-01)

`_extract_wikilinks` in `confluence_publish.py` now iterates line-by-line,
tracking an `in_fence` boolean that flips on/off at each ` ``` ` boundary. Lines
inside a fence pass through unmodified; lines outside receive the wikilink regex
substitution as before.

### TODO

- [x] ~~Port the fix to the repo and open a PR~~ — done, merged in PR #1.
- [ ] Add a regression test: a `.md` file with a `[[wikilink]]` inside a fenced
  code block should convert without error and leave the link text as-is inside
  the published `<code>` block.
- [ ] Audit whether the same masking gap exists for `_extract_callouts`. If a
  callout-style line (`> [!info]`) appears inside a code block, it may trigger
  the same class of bug.
- [ ] The merged fix only toggles fence state on backtick fences (` ``` `). It
  does **not** handle tilde fences (`~~~`) or 4-space indented code blocks.
  Wikilinks inside those styles will still be extracted. Low priority given the
  Obsidian-style Markdown this tool targets, but worth a follow-up patch.
