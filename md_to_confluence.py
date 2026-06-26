#!/usr/bin/env python3
"""Markdown -> Confluence storage-format conversion helpers.

A library of pure functions used by confluence_publish.py to turn Obsidian-style
Markdown into Confluence-compatible HTML: inline formatting, tables, lists,
callouts, code, and Mermaid rendering (via npx @mermaid-js/mermaid-cli).

Requirements: Python 3.9+, and `npx` on PATH for Mermaid rendering (optional;
falls back to a styled block if unavailable).
"""

from __future__ import annotations  # PEP 563: defer annotation eval so the
# `X | None` / `tuple[str, ...]` syntax below also runs on Python 3.9 (the
# system interpreter on this machine), not just the documented 3.10+.

import re
import os
import subprocess
import sys
import tempfile
import hashlib
from pathlib import Path


# --------------------------------------------------------------------------- #
#  Mermaid rendering
# --------------------------------------------------------------------------- #

# Set by process_file() before calling convert_markdown_to_html()
_current_img_dir: Path | None = None
_current_img_rel: str = ""  # relative path from HTML file to img dir


def render_mermaid_png(mermaid_code: str, img_dir: Path, img_rel: str) -> str | None:
    """Render Mermaid code to PNG via mmdc, return ``<img>`` tag or ``None`` on failure."""
    digest = hashlib.md5(mermaid_code.encode()).hexdigest()[:10]
    filename = f"mermaid_{digest}.png"
    out_path = img_dir / filename

    if out_path.exists():
        return f'<img src="{img_rel}/{filename}" alt="Mermaid diagram" />'

    img_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.mmd', delete=False) as f:
        f.write(mermaid_code)
        tmp_mmd = f.name

    try:
        result = subprocess.run(
            ['npx', '-y', '-p', '@mermaid-js/mermaid-cli', 'mmdc',
             '-i', tmp_mmd, '-o', str(out_path),
             '-b', 'white', '-s', '2', '-q'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and out_path.exists():
            return f'<img src="{img_rel}/{filename}" alt="Mermaid diagram" />'
        else:
            print(f"    WARNING: mmdc failed: {result.stderr[:200]}")
            return None
    except Exception as e:
        print(f"    WARNING: mmdc error: {e}")
        return None
    finally:
        os.unlink(tmp_mmd)

# --------------------------------------------------------------------------- #
#  Markdown helpers
# --------------------------------------------------------------------------- #


def strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block (``---`` … ``---``) if present."""
    if text.startswith('---\n') or text.startswith('---\r\n'):
        m = re.match(r'^---\r?\n.*?\r?\n---\r?\n?', text, re.DOTALL)
        if m:
            return text[m.end():]
    return text


def convert_wikilinks(text: str) -> str:
    """Convert Obsidian ``[[wikilinks]]`` to plain text (internal, not useful in Confluence).

    ``[[Page|Alias]]`` -> ``Alias``; ``[[Page#Heading]]`` -> ``Page``;
    ``![[embed]]`` -> ``embed``. The leading ``!`` of an embed is dropped.
    """
    def repl(m: re.Match) -> str:
        inner = m.group(1)
        if '|' in inner:
            return inner.split('|', 1)[1].strip()
        return inner.split('#', 1)[0].strip()
    return re.sub(r'!?\[\[([^\]]+)\]\]', repl, text)


def strip_glossary_links(text: str) -> str:
    """Remove glossary markdown links, keep the link text."""
    return re.sub(r'\[([^\]]+)\]\(\.\./(?:\.\./)?glossary/[^)]+\)', r'\1', text)


def convert_internal_links(text: str) -> str:
    """Convert remaining internal links to plain text.

    Handles ``[t](file.md)``, ``[t](file.md#frag)`` and same-page section
    links ``[t](#anchor)`` — none of these resolve in Confluence, which
    generates its own heading anchors.
    """
    return re.sub(r'\[([^\]]+)\]\((?:[^)]*\.md(?:#[^)]*)?|#[^)]*)\)', r'\1', text)


def escape_html(text: str) -> str:
    """Escape HTML special chars in text content."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def process_inline(text: str) -> str:
    """Process inline markdown: bold, italic, code, links. Produces well-formed XHTML.

    Code spans and links are masked BEFORE emphasis and escaping, so that
    (a) stray ``*``/``_`` inside code (globs, regexes, generics) never create
    crossing ``<em>`` tags, and (b) literal ``<`` ``>`` ``&`` in ordinary text are
    escaped without corrupting the tags we generate. This is what keeps the output
    valid Confluence storage format (XHTML).
    """
    text = strip_glossary_links(text)
    text = convert_wikilinks(text)
    text = convert_internal_links(text)

    store: list[str] = []

    def stash(html: str) -> str:
        store.append(html)
        return f'\x00{len(store) - 1}\x00'

    # Inline code `code` — escape content, then mask so emphasis/escaping skip it.
    text = re.sub(r'`([^`]+)`',
                  lambda m: stash('<code>' + escape_html(m.group(1)) + '</code>'), text)
    # External links [text](url)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',
                  lambda m: stash('<a href="' + m.group(2).replace('&', '&amp;') + '">'
                                  + escape_html(m.group(1)) + '</a>'), text)
    # Bare autolinks <http(s)://...>
    text = re.sub(r'<(https?://[^>\s]+)>',
                  lambda m: stash('<a href="' + m.group(1).replace('&', '&amp;') + '">'
                                  + m.group(1) + '</a>'), text)

    # Escape stray < > & in the remaining plain text (masked spans are inert \x00N\x00).
    text = escape_html(text)

    # Emphasis — safe now: no code/links inside, placeholders are inert.
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
    text = re.sub(r'(?<!\w)\*([^*]+)\*(?!\w)', r'<em>\1</em>', text)
    text = re.sub(r'(?<!\w)_([^_]+)_(?!\w)', r'<em>\1</em>', text)

    # Restore masked code/link spans.
    text = re.sub(r'\x00(\d+)\x00', lambda m: store[int(m.group(1))], text)
    return text

# --------------------------------------------------------------------------- #
#  Tables
# --------------------------------------------------------------------------- #


def convert_table(lines: list[str]) -> str:
    """Convert markdown table lines to HTML table."""
    if len(lines) < 2:
        return ''

    html = '<table>\n<thead>\n<tr>\n'
    headers = [cell.strip() for cell in lines[0].strip('|').split('|')]
    for h in headers:
        html += f'<th>{process_inline(h)}</th>\n'
    html += '</tr>\n</thead>\n<tbody>\n'

    for row_line in lines[2:]:  # skip separator line
        if not row_line.strip():
            continue
        cells = [cell.strip() for cell in row_line.strip('|').split('|')]
        html += '<tr>\n'
        for c in cells:
            html += f'<td>{process_inline(c)}</td>\n'
        html += '</tr>\n'

    html += '</tbody>\n</table>\n'
    return html

# --------------------------------------------------------------------------- #
#  Blockquote / callout helpers
# --------------------------------------------------------------------------- #


def _parse_blockquote_segments(content_lines: list[str]) -> list[tuple[str, str]]:
    """Parse blockquote content into ``('inline', html)`` or ``('block', html)`` segments."""
    segments = []
    text_buf: list[str] = []
    i = 0

    def flush_text():
        if text_buf:
            segments.append(('inline', f'<p>{process_inline(" ".join(text_buf))}</p>'))
            text_buf.clear()

    while i < len(content_lines):
        line = content_lines[i]
        # Fenced code block
        if line.startswith('```'):
            flush_text()
            code_lines = []
            i += 1
            while i < len(content_lines) and not content_lines[i].startswith('```'):
                code_lines.append(content_lines[i])
                i += 1
            i += 1  # skip closing ```
            code_content = escape_html('\n'.join(code_lines))
            segments.append(('block', f'<pre><code>{code_content}</code></pre>'))
            continue
        # Unordered list item
        if re.match(r'^[-*]\s', line):
            flush_text()
            items = []
            while i < len(content_lines) and re.match(r'^[-*]\s', content_lines[i]):
                item_text = re.sub(r'^[-*]\s+', '', content_lines[i])
                items.append(f'<li>{process_inline(item_text)}</li>')
                i += 1
            segments.append(('inline', '<ul>\n' + '\n'.join(items) + '\n</ul>'))
            continue
        # Ordered list item
        if re.match(r'^\d+\.\s', line):
            flush_text()
            items = []
            while i < len(content_lines) and re.match(r'^\d+\.\s', content_lines[i]):
                item_text = re.sub(r'^\d+\.\s+', '', content_lines[i])
                items.append(f'<li>{process_inline(item_text)}</li>')
                i += 1
            segments.append(('inline', '<ol>\n' + '\n'.join(items) + '\n</ol>'))
            continue
        # Table
        if '|' in line and i + 1 < len(content_lines) and re.match(r'^[\s|:-]+$', content_lines[i + 1]):
            flush_text()
            table_lines = []
            while i < len(content_lines) and '|' in content_lines[i]:
                table_lines.append(content_lines[i])
                i += 1
            segments.append(('block', convert_table(table_lines)))
            continue
        # Empty line = paragraph break
        if not line:
            flush_text()
            i += 1
            continue
        text_buf.append(line)
        i += 1
    flush_text()
    return segments


def _render_blockquote_split(content_lines: list[str], wrapper_open: str, wrapper_close: str) -> str:
    """Render blockquote content, pulling tables/code outside the wrapper for Confluence."""
    segments = _parse_blockquote_segments(content_lines)
    parts: list[str] = []
    inline_buf: list[str] = []
    first = True

    def flush_inline():
        nonlocal first
        if inline_buf:
            opener = wrapper_open if first else '<blockquote>\n'
            first = False
            parts.append(opener + '\n'.join(inline_buf) + '\n' + wrapper_close)
            inline_buf.clear()

    for kind, html in segments:
        if kind == 'block':
            flush_inline()
            parts.append(html)
        else:
            inline_buf.append(html)

    flush_inline()
    return '\n'.join(parts)

# --------------------------------------------------------------------------- #
#  List converters
# --------------------------------------------------------------------------- #


def convert_list_block(lines: list[str], start: int) -> str:
    """Convert an unordered list block to HTML."""
    items = []
    i = start
    while i < len(lines):
        line = lines[i]
        match = re.match(r'^(\s*)[-*]\s+(.*)', line)
        if not match:
            break
        indent = len(match.group(1))
        text = process_inline(match.group(2))

        i += 1
        while i < len(lines):
            next_match = re.match(r'^(\s*)[-*]\s', lines[i])
            if next_match and len(next_match.group(1)) > indent:
                nested_html = convert_list_block(lines, i)
                while i < len(lines) and (re.match(r'^(\s*)[-*]\s', lines[i]) and len(re.match(r'^(\s*)', lines[i]).group(1)) > indent):
                    i += 1
                text += '\n' + nested_html
                break
            else:
                break

        items.append(f'<li>{text}</li>')

    return '<ul>\n' + '\n'.join(items) + '\n</ul>'


def convert_ordered_list_block(lines: list[str], start: int) -> str:
    """Convert an ordered list block to HTML."""
    items = []
    i = start
    while i < len(lines):
        line = lines[i]
        match = re.match(r'^(\s*)\d+\.\s+(.*)', line)
        if not match:
            break
        text = process_inline(match.group(2))
        items.append(f'<li>{text}</li>')
        i += 1

    return '<ol>\n' + '\n'.join(items) + '\n</ol>'

# --------------------------------------------------------------------------- #
#  Main Markdown -> HTML converter
# --------------------------------------------------------------------------- #


def convert_markdown_to_html(md_text: str) -> str:
    """Convert a Markdown document to an HTML fragment."""
    md_text = strip_glossary_links(md_text)

    lines = md_text.split('\n')
    html_parts = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip empty lines
        if not line.strip():
            i += 1
            continue

        # Horizontal rule
        if re.match(r'^---\s*$', line):
            html_parts.append('<hr />')
            i += 1
            continue

        # <details>/<summary> blocks
        if line.strip() == '<details>':
            i += 1
            summary_text = ''
            if i < len(lines) and '<summary>' in lines[i]:
                summary_match = re.search(r'<summary>(.*?)</summary>', lines[i])
                if summary_match:
                    summary_text = summary_match.group(1)
                i += 1
            inner_lines = []
            while i < len(lines) and lines[i].strip() != '</details>':
                inner_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1  # skip </details>
            inner_html = convert_markdown_to_html('\n'.join(inner_lines))
            if summary_text:
                html_parts.append(f'<p><strong>{process_inline(summary_text)}</strong></p>')
            html_parts.append(inner_html.rstrip())
            continue

        # Mermaid code blocks
        if line.strip().startswith('```mermaid'):
            mermaid_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                mermaid_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            mermaid_code = '\n'.join(mermaid_lines)

            img_html = None
            if _current_img_dir is not None:
                img_html = render_mermaid_png(mermaid_code, _current_img_dir, _current_img_rel)

            if img_html:
                html_parts.append(
                    f'<div style="margin: 12px 0;">\n'
                    f'{img_html}\n'
                    f'</div>'
                )
            else:
                mermaid_content = escape_html(mermaid_code)
                html_parts.append(
                    f'<div style="border-left: 4px solid #0052CC; background: #f4f5f7; padding: 12px; margin: 12px 0;">\n'
                    f'<strong>Diagram (Mermaid)</strong>\n'
                    f'<pre><code>{mermaid_content}</code></pre>\n'
                    f'</div>'
                )
            continue

        # Code blocks
        if line.strip().startswith('```'):
            lang_match = re.match(r'^```(\w*)', line.strip())
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            code_content = escape_html('\n'.join(code_lines))
            html_parts.append(f'<pre><code>{code_content}</code></pre>')
            continue

        # Callouts: > [!type] optional title  (any Obsidian callout type;
        # trailing +/- fold marker and an inline title are both supported)
        callout_match = re.match(r'^>\s*\[!(\w+)\][+-]?\s*(.*)$', line)
        if callout_match:
            callout_type = callout_match.group(1)
            inline_title = callout_match.group(2).strip()
            callout_lines = []
            i += 1
            while i < len(lines) and lines[i].startswith('>'):
                # Keep blank ('>') lines: they are paragraph breaks inside the callout.
                callout_lines.append(lines[i].lstrip('>').strip())
                i += 1

            # Use the author's inline title if given, else the capitalized type.
            if inline_title:
                header = f'<p><strong>{process_inline(inline_title)}</strong></p>\n'
            else:
                header = f'<p><strong>{callout_type.capitalize()}:</strong></p>\n'
            callout_html = _render_blockquote_split(
                callout_lines,
                f'<blockquote>\n{header}',
                '</blockquote>'
            )
            html_parts.append(callout_html)
            continue

        # Blockquotes (non-callout)
        if line.startswith('>'):
            bq_lines = []
            while i < len(lines) and lines[i].startswith('>'):
                content = lines[i].lstrip('>').strip()
                bq_lines.append(content)
                i += 1
            bq_html = _render_blockquote_split(bq_lines, '<blockquote>\n', '</blockquote>')
            html_parts.append(bq_html)
            continue

        # Headings
        heading_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if heading_match:
            level = len(heading_match.group(1))
            text = process_inline(heading_match.group(2))
            html_parts.append(f'<h{level}>{text}</h{level}>')
            i += 1
            continue

        # Tables
        if '|' in line and i + 1 < len(lines) and re.match(r'^[\s|:-]+$', lines[i + 1]):
            table_lines = []
            while i < len(lines) and '|' in lines[i]:
                table_lines.append(lines[i])
                i += 1
            html_parts.append(convert_table(table_lines))
            continue

        # Checkbox lists — must precede the unordered-list test below, since
        # "- [ ] item" also matches the generic "^[-*]\s" list pattern.
        if re.match(r'^- \[[ xX]\]\s', line):
            items = []
            while i < len(lines) and re.match(r'^- \[[ xX]\]\s', lines[i]):
                checked = lines[i][3] in ('x', 'X')
                text = process_inline(lines[i][6:])
                marker = '&#x2611;' if checked else '&#x2610;'
                items.append(f'<li>{marker} {text}</li>')
                i += 1
            html_parts.append('<ul>\n' + '\n'.join(items) + '\n</ul>')
            continue

        # Unordered lists
        if re.match(r'^(\s*)[-*]\s', line):
            html_parts.append(convert_list_block(lines, i))
            while i < len(lines) and (re.match(r'^(\s*)[-*]\s', lines[i]) or (lines[i].strip() and lines[i].startswith('  '))):
                i += 1
            continue

        # Ordered lists
        if re.match(r'^(\s*)\d+\.\s', line):
            html_parts.append(convert_ordered_list_block(lines, i))
            while i < len(lines) and (re.match(r'^(\s*)\d+\.\s', lines[i]) or (lines[i].strip() and lines[i].startswith('  '))):
                i += 1
            continue


        # Paragraph (default)
        para_lines = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith('#') and not lines[i].startswith('```') and not lines[i].startswith('>') and not re.match(r'^---\s*$', lines[i]) and not re.match(r'^[-*]\s', lines[i]) and not re.match(r'^\d+\.\s', lines[i]) and not ('|' in lines[i] and i + 1 < len(lines) and re.match(r'^[\s|:-]+$', lines[i + 1])):
            para_lines.append(lines[i])
            i += 1
        if para_lines:
            text = process_inline(' '.join(para_lines))
            html_parts.append(f'<p>{text}</p>')
        continue

    return '\n\n'.join(html_parts) + '\n'
