from __future__ import annotations

import re

import nh3
from loguru import logger
from markdown import Markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor
from markupsafe import Markup

# Only these tags may reach the template. Everything else is stripped by nh3;
# script/style and other active-content containers lose their contents too.
ALLOWED_TAGS = {
    "p",
    "br",
    "h3",
    "h4",
    "h5",
    "h6",
    "blockquote",
    "pre",
    "ul",
    "ol",
    "li",
    "hr",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "a",
    "strong",
    "em",
    "code",
}

# del is deliberately absent: link_rel is managed by nh3, so "rel" is not
# listed here. Fenced code classes are stripped to keep the attribute surface
# small; pre gets tabindex so keyboard users can scroll long code lines.
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "pre": {"tabindex"},
}

ALLOWED_URL_SCHEMES = {"http", "https"}
LINK_REL = "noopener noreferrer"

CLEAN_CONTENT_TAGS = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "svg",
    "math",
    "form",
}

_TAG_MIN_LEVEL = 3
_TAG_MAX_LEVEL = 6
_PRE_TAG_RE = re.compile(r"<pre(\s[^>]*)?>")


class _NormalizeHeadings(Treeprocessor):
    """Shift Markdown headings so body content starts at h3 and never passes h6."""

    def run(self, root):
        for element in root.iter():
            tag = element.tag
            if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                level = int(tag[1])
                if level < _TAG_MIN_LEVEL:
                    level = _TAG_MIN_LEVEL
                else:
                    level = min(level + 1, _TAG_MAX_LEVEL)
                element.tag = f"h{level}"
            elif tag == "pre":
                element.set("tabindex", "0")
        return root


def _make_pre_focusable(html: str) -> str:
    """Add tabindex to fenced code blocks after sanitization.

    Python-Markdown inserts fenced-code placeholders after its treeprocessor
    pass, so the tree walker cannot see them. Adding one constant attribute to
    already-sanitized `<pre>` tags keeps the allowed attribute surface unchanged.
    """

    def add(match: re.Match[str]) -> str:
        attrs = match.group(1) or ""
        if "tabindex" in attrs:
            return match.group(0)
        return f'<pre tabindex="0"{attrs}>'

    return _PRE_TAG_RE.sub(add, html)


class _IssueBodyExtension(Extension):
    def extendMarkdown(self, md: Markdown) -> None:  # noqa: N802 (upstream API)
        md.treeprocessors.register(_NormalizeHeadings(md), "gw_issue_headings", 5)


def render_issue_body(raw: str | None) -> Markup | None:
    """Render an Issue body to sanitized HTML.

    Returns ``None`` for blank bodies or when the pipeline fails. Callers must
    fall back to auto-escaped plain text in the failure case; never mark an
    unsanitized string as ``Markup``.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        md = Markdown(
            extensions=["fenced_code", "tables", "sane_lists", _IssueBodyExtension()],
            output_format="html",
        )
        converted = md.convert(raw)
        cleaned = nh3.clean(
            converted,
            tags=ALLOWED_TAGS,
            attributes=ALLOWED_ATTRIBUTES,
            url_schemes=ALLOWED_URL_SCHEMES,
            url_relative="deny",
            link_rel=LINK_REL,
            clean_content_tags=CLEAN_CONTENT_TAGS,
        )
        return Markup(_make_pre_focusable(cleaned))
    except Exception as exc:  # noqa: BLE001 - failure must close, never leak raw HTML
        logger.warning(f"issue body markdown render failed: {exc}")
        return None
