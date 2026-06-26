# confluence-docs-publisher

Turn any code repository into a clean, numbered documentation set, then publish it to Confluence Cloud — with rendered diagrams and working cross-page links.

There are two stages, and they are independent:

1. **Generate** — point your own Claude at a repo and a spec (`template.yaml`); it writes a numbered Markdown doc set you review in Obsidian.
2. **Publish** — `confluence_publish.py` uploads that doc set to Confluence Cloud as a page tree under one parent page, idempotently and safely.

The Markdown is the source of truth; Confluence is a derived view you can re-publish at any time.

---

## What you need

| Tool | For | Notes |
| ---- | --- | ----- |
| **Python 3.9+** | Publishing | Standard library only; no `pip install` required. |
| **Node.js + `npx`** | Diagrams | Used to render Mermaid diagrams to PNG (`@mermaid-js/mermaid-cli`, fetched on first use). Optional — without it, diagrams fall back to a code block. |
| **Claude Code** | Generating | Only needed for stage 1. See [`GUIDE.md`](GUIDE.md). |
| **Obsidian** | Reading/editing | The generated docs use Obsidian wikilinks and Mermaid. Free from <https://obsidian.md>. |
| **A Confluence Cloud account + API token** | Publishing | Token: <https://id.atlassian.com/manage-profile/security/api-tokens> |

---

## Repository contents

| File | What it is |
| ---- | ---------- |
| `template.yaml` | The doc-set spec the generator follows (universal sections + per-repo "In Situ" deep-dives, adapted to the repo's archetype). |
| `GUIDE.md` | Step-by-step walkthrough for stage 1 (generate docs with your own Claude). |
| `confluence_publish.py` | The publisher (stage 2). A self-contained CLI. |
| `md_to_confluence.py` | Markdown → Confluence-storage conversion library used by the publisher. |
| `.env.example` | Template for the three credentials (copy to `.env`). |

---

## Stage 1 — Generate the docs

Full instructions are in [`GUIDE.md`](GUIDE.md). In short: open Claude Code in your repo, paste the generation prompt from the guide (with `template.yaml`), and it writes a folder like:

```
my-repo-docs/
├── 00 - Index.md
├── 01 - Welcome and Quick Start.md
├── 02 - Architecture Overview.md
├── ...
└── In Situ/
    └── <repo-specific deep-dives>.md
```

Review and edit the Markdown before publishing. It is the source of truth.

---

## Stage 2 — Publish to Confluence

### 1. Set your credentials

```bash
cp .env.example .env      # then edit .env with your base URL, email, and token
set -a; . ./.env; set +a  # load them into your shell (never commit .env)
```

The base URL for Confluence Cloud ends in `/wiki`, for example `https://your-company.atlassian.net/wiki`.

### 2. Choose the space and parent page

The tool publishes everything under **one parent page** you specify, and never touches anything outside it. You need two values:

- **Space key** — the part after `/spaces/` in the URL: `…/wiki/spaces/`**`DOCS`**`/…`. A team space has a short key like `DOCS` or `ENG`; a personal space key starts with `~`.
- **Parent page id** — you must create a **page** (not a folder) in that space to hold the docs; everything is published as children of it. Create it (you need permission to add pages there), then copy its id from the URL: `…/pages/`**`123456789`**`/…`. You can keep that page inside a Confluence folder for tidiness; the tool still targets the page.

Tip: trial it in your **personal space** (`~yourname`) first, then repoint at the team space by changing `--space` and `--parent`.

### 3. Dry-run, then publish

```bash
# See exactly what would happen — writes nothing:
python3 confluence_publish.py my-repo-docs --space DOCS --parent 123456789 --dry-run

# Publish for real:
python3 confluence_publish.py my-repo-docs --space DOCS --parent 123456789
```

The tool prints a per-page plan (`CREATE` / `UPDATE`) and how many diagrams each page carries. Re-running updates the same pages in place (matched by title), so it is safe to run repeatedly.

### What it produces

- The numbered docs become child pages of your parent page.
- The `In Situ/` folder becomes an `In Situ` page with the deep-dives beneath it.
- Mermaid diagrams are rendered to PNG, uploaded as attachments, and embedded.
- `[[wikilinks]]` become real Confluence page links.
- Code blocks become code macros; Obsidian callouts (`> [!info]`, `> [!warning]`, …) become colored panels.

---

## Safety

The publisher is non-destructive by construction:

- It only ever **creates or updates pages under the parent page id you pass**. It does not scan, edit, or touch anything elsewhere in the space.
- It **never deletes** anything.
- Each page body is **validated as XML before it is sent**, so malformed content fails locally instead of producing broken pages.
- Credentials are read from the environment only and are never written to disk by the tool.

The worst realistic failure is a mis-formatted page under your own parent, which you can edit or delete.

---

## Status and roadmap

Working today: end-to-end generation and publishing, including code macros, colored panels, tables, Mermaid diagrams as attachments, and wikilink-to-Confluence-link conversion.

Not yet implemented (contributions welcome):

- A `state.json` page map (currently pages are matched by title), to survive renames and skip unchanged pages.
- Content-hash skip of unchanged pages.
- Exact heading-anchor links (`[[Page#Heading]]` currently lands on the page, not the heading).
- A `--prune` option to remove pages whose source doc was deleted (off by default).

---

## License

MIT — see [`LICENSE`](LICENSE).
