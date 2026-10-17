"""Minimal, safe Markdown → HTML for the research document.

Covers what research notes use: headings, paragraphs, bold/italic, inline code,
links and bare URLs, bullet/numbered lists, pipe tables and fenced code blocks.
All text is HTML-escaped first; only the tags generated here are emitted.
"""
from __future__ import annotations

import html
import re
import unicodedata
from typing import List, Tuple

_FENCE = re.compile(r"^```\s*([\w+-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED = re.compile(r"^\s*\d+[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_URL = re.compile(r"(?<![\"'=>])(https?://[^\s<)\]]+[^\s<)\].,;:])")
_ESCAPES = {"\\*": "\x01", "\\_": "\x02", "\\|": "\x03", "\\[": "\x04", "\\]": "\x05", "\\`": "\x06"}
_RESTORE = {"\x01": "*", "\x02": "_", "\x03": "|", "\x04": "[", "\x05": "]", "\x06": "`"}


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.replace("ı", "i")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "bolum"


def _protect(text: str) -> str:
    for k, v in _ESCAPES.items():
        text = text.replace(k, v)
    return text


def _restore(text: str) -> str:
    for k, v in _RESTORE.items():
        text = text.replace(k, v)
    return text


def inline(text: str) -> str:
    """Inline markup on already-protected (escape-substituted) text."""
    codes: List[str] = []

    def stash(m):
        codes.append("<code>%s</code>" % html.escape(_restore(m.group(1)), quote=False))
        return "\x00%d\x00" % (len(codes) - 1)

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    links: List[str] = []

    def add_link(url: str, label: str) -> str:
        href = html.escape(html.unescape(url), quote=True)
        links.append('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (href, label))
        return "\x07%d\x07" % (len(links) - 1)

    text = _LINK.sub(lambda m: add_link(m.group(2), m.group(1)), text)
    text = _URL.sub(lambda m: add_link(m.group(1), m.group(1)), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"\x07(\d+)\x07", lambda m: links[int(m.group(1))], text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)
    return _restore(text)


def _cells(line: str) -> List[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def render(markdown: str) -> Tuple[str, List[Tuple[int, str, str]]]:
    """Return (html, toc) where toc is [(level, anchor, title)] for h2/h3."""
    lines = _protect(markdown.replace("\r\n", "\n")).split("\n")
    out: List[str] = []
    toc: List[Tuple[int, str, str]] = []
    used = set()
    para: List[str] = []
    i = 0

    def flush_para():
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para)))
            para.clear()

    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            flush_para()
            lang = fence.group(1)
            body = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                body.append(_restore(lines[i]))
                i += 1
            i += 1
            out.append('<pre class="code" data-lang="%s"><code>%s</code></pre>'
                       % (html.escape(lang), html.escape("\n".join(body), quote=False)))
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_para()
            level = len(heading.group(1))
            title = heading.group(2)
            anchor = slugify(_restore(title))
            while anchor in used:
                anchor += "-2"
            used.add(anchor)
            plain = re.sub(r"\*\*|`", "", _restore(title))
            if level in (2, 3):
                toc.append((level, anchor, plain))
            out.append('<h%d id="%s">%s</h%d>' % (level, anchor, inline(title), level))
            i += 1
            continue
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush_para()
            head = _cells(line)
            i += 2
            rows = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_cells(lines[i]))
                i += 1
            out.append('<div class="table-wrap"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
                "".join("<th>%s</th>" % inline(c) for c in head),
                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r) for r in rows)))
            continue
        bullet, ordered = _BULLET.match(line), _ORDERED.match(line)
        if bullet or ordered:
            flush_para()
            tag = "ul" if bullet else "ol"
            pattern = _BULLET if bullet else _ORDERED
            items = []
            while i < len(lines) and pattern.match(lines[i]):
                items.append(pattern.match(lines[i]).group(1))
                i += 1
                while i < len(lines) and lines[i].startswith("  ") and lines[i].strip() and not _BULLET.match(lines[i]):
                    items[-1] += " " + lines[i].strip()
                    i += 1
            out.append("<%s>%s</%s>" % (tag, "".join("<li>%s</li>" % inline(x) for x in items), tag))
            continue
        if not line.strip():
            flush_para()
        else:
            para.append(line.strip())
        i += 1
    flush_para()
    return "\n".join(out), toc
