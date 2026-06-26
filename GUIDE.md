# How to generate documentation for your repo

This guide shows you how to turn **any code repository** into a clean, numbered documentation set using `template.yaml` and your own Claude. No prior knowledge is needed — you only need `template.yaml` and the steps below.

Estimated time: about 10 to 30 minutes depending on the size of your repo.

---

## What it does

You point Claude at your repository and at `template.yaml`. Claude reads your code and writes a set of Markdown documents (Welcome, Architecture Overview, API Reference, and so on) into a folder you choose. You open that folder in Obsidian and read it like a wiki, with working links between pages and rendered diagrams.

The document set adapts to your repo automatically:
- Every repo gets the same **core documents** (the "universal" set).
- Documents that do not apply are skipped. A repo with no database gets no "Database Schema" page; a repo with no user interface gets no frontend pages.
- Each document is **re-framed** for what your repo is. "API Reference" means HTTP endpoints for a web service, exported functions for a library, and commands for a command-line tool.
- Your repo's own special subsystems get extra deep-dive documents (the "In Situ" set), discovered from your code.

---

## What you need

| Thing | Why | How to get it |
| ----- | --- | ------------- |
| **Claude Code** | This is the version of Claude that can read your files and write documents. Plain chat on the website cannot read a repository directly. | Install from <https://claude.com/claude-code>, then sign in. |
| **A repository to document** | The code Claude will read. Have it cloned locally. | Any local folder with code. |
| **`template.yaml`** | The recipe Claude follows. | Copy the `template.yaml` file from this folder to somewhere you can find it (for example, into your repo, or your home folder). |
| **Obsidian** | The app you read the result in. The documents use Obsidian-style links and diagrams. | Free download from <https://obsidian.md>. |

> [!tip] You do not need a database, a frontend, or any particular language.
> The template works for a backend service, a library, a command-line tool, a frontend app, a data pipeline, or infrastructure code, in any programming language.

---

## Step by step

### Step 1 — Put `template.yaml` where you can reach it
Copy `template.yaml` into a convenient place. The simplest option is to drop it inside the repo you want to document (for example at the repo root). You can delete it afterward.

### Step 2 — Decide where the documents will go
Pick an **empty folder** for the output. It can be anywhere, for example `~/Desktop/my-repo-docs`. This folder will become your Obsidian vault. Keeping it separate from the code keeps things tidy.

### Step 3 — Open Claude Code in your repo
Open a terminal, change into your repository folder, and start Claude Code:

```bash
cd /path/to/your/repo
claude
```

### Step 4 — Paste the generation prompt
Copy the entire block in the [The generation prompt](#the-generation-prompt) section below, fill in the two paths at the top, and paste it into Claude Code. Claude will work through your repo and write the documents into your output folder. It will tell you when it is done.

### Step 5 — Review what it wrote
Claude generates from your **current code**, so the facts should be accurate, but it is still machine-written. Skim the documents. Fix anything that looks off — these are normal Markdown files.

### Step 6 — Open the folder in Obsidian
Open Obsidian, choose **Open folder as vault**, and select your output folder. The pages, links, and diagrams will render. That is your documentation.

---

## The generation prompt

Fill in the two paths on the first two lines, then paste the whole thing into Claude Code.

```
You are going to generate a documentation set for THIS repository by following a spec file.

SPEC FILE:    <path to template.yaml, e.g. ./template.yaml>
OUTPUT FOLDER: <path to your empty output folder, e.g. /Users/me/Desktop/my-repo-docs>

Do this in order:

1. CLASSIFY the repo from its code:
   - Pick ONE archetype from the spec's `archetype` block (service, library, cli,
     frontend, mobile, data-pipeline, or infra), based on what this repo mainly is.
   - Evaluate the `detect` feature-gates: does it have a frontend? does it own a
     database schema? Use the spec's signals. If a database signal is only "weak"
     (a bare driver, a stray .sql file), do NOT assume a schema doc — ask me.
   - Tell me the archetype and gate results before generating, in one short line.

2. PLAN the set:
   - Take the universal sections from the spec whose `when:` condition passes for
     this repo (skip frontend docs if there is no frontend, skip the database doc
     if there is no owned schema).
   - Sort them by their `order` field, then number them gap-free 01, 02, 03 ...
     (the skipped ones must NOT leave a hole in the numbering).
   - Then DISCOVER "In Situ" docs: scan the repo for any significant, cohesive
     subsystem a newcomer could not understand from the universal docs alone, and
     propose one deep-dive doc per subsystem, titled with the subsystem's real
     name. Zero is a valid answer. These are unnumbered.

3. GENERATE each document into the OUTPUT FOLDER, following the spec exactly:
   - Read the matching `sections` entry in the spec for each doc and follow its
     `intent`, adapted to this repo's archetype.
   - Follow the spec's `meta.conventions`: open with YAML frontmatter (title), then
     one H1 repeating "NN - Title"; H2 section headings are UNNUMBERED; use Obsidian
     callouts; emit native ```mermaid``` blocks where useful; write in FULL FORMS,
     never contractions ("it is", not "it's").
   - Ground every fact in code you actually read. Do not invent versions, ports,
     paths, or commands. If unsure, say so in the doc.
   - Put numbered universal docs at the top level of the output folder. Put In Situ
     docs (unnumbered) in an "In Situ" subfolder.

4. CROSS-LINKS:
   - Link to a numbered doc with its FULL name: [[03 - Domain Concepts]], never the
     bare [[Domain Concepts]].
   - Link to an In Situ doc by its bare title: [[Some Subsystem]].
   - Only use #heading anchors for links inside the SAME document, to headings you
     wrote yourself (use the exact heading text).

5. FINALIZE:
   - Generate "00 - Index.md" LAST, listing every document with a one-line summary.
   - Re-check every [[link]]: fix any bare-title link to a numbered doc into its
     full [[NN - Title]] form, and confirm every link points at a file that exists.
   - Report: the archetype, the list of documents you created, and any links or
     facts you were unsure about.
```

> [!tip] Large repositories
> If your repo is very large, Claude may generate the documents one at a time and take a while. That is fine — let it work. You can also ask it to "generate only docs 01 to 04 first" and continue later.

---

## What you get

A folder like this (the exact list depends on your repo):

```
my-repo-docs/
├── 00 - Index.md
├── 01 - Welcome and Quick Start.md
├── 02 - Architecture Overview.md
├── 03 - Domain Concepts.md
├── 04 - Code Architecture.md
├── 05 - API Reference.md
├── ... (more, numbered with no gaps)
└── In Situ/
    ├── <Your Subsystem>.md
    └── <Another Subsystem>.md
```

- **Numbered docs** are the core set; the numbers are always gap-free.
- **In Situ docs** are the deep-dives specific to your repo. There may be several, or none.

---

## Tips and troubleshooting

- **A link shows "not created yet" in Obsidian.** A link to a numbered doc must use the full `[[NN - Title]]` form. Ask Claude to "normalize all bare-title links to their NN - Title form." (The prompt already asks for this, but it is the most common slip.)
- **A diagram does not render.** Obsidian is strict about characters inside Mermaid labels. Ask Claude to "fix the Mermaid diagram in <file> so it renders in Obsidian" — the spec's `mermaid` block has the rules it will follow.
- **The archetype is wrong** (for example it called your component library a "frontend app"). Tell Claude the correct archetype and ask it to regenerate. The spec expects a human to confirm this.
- **You want to regenerate later** after the code changes. Generate into a fresh folder and compare, or ask Claude to regenerate specific documents. Do not let it blindly overwrite docs you have hand-edited; ask for a diff first.
- **Keep the Markdown as the source of truth.** Edit the generated files directly when something is wrong; they are plain Markdown.

---

## In one sentence

Install Claude Code and Obsidian, copy `template.yaml` next to your repo, paste the generation prompt into Claude Code with your two paths filled in, then open the output folder in Obsidian.
