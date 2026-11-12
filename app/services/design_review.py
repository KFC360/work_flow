from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crud import design_feedback as feedback_crud
from app.models.design_feedback import DesignFeedback
from app.models.issue import Issue
from app.models.job import Job

MAX_PENDING_ITEMS = 50
MAX_ITEM_TITLE = 200
MAX_HISTORY = 100

FEEDBACK_KIND_LABELS = {
    feedback_crud.HUMAN_COMMENT: "人工意见",
    feedback_crud.REVISE_REQUEST: "修订请求",
    feedback_crud.PENDING_CONFIRM: "已确认",
    feedback_crud.PENDING_REJECT: "已驳回",
    feedback_crud.HUMAN_EDIT: "人工编辑",
    feedback_crud.APPROVE: "批准",
    feedback_crud.UNAPPROVE: "取消批准",
}

PENDING_STATUS_LABELS = {
    feedback_crud.PENDING_CONFIRM: "已确认",
    feedback_crud.PENDING_REJECT: "已驳回",
}

REASON_LABELS = {
    "section_missing": "文档没有「待确认」小节",
    "section_empty": "「待确认」小节没有可解析的标题或列表",
    "too_many": "「待确认」项超过 50 条",
    "parse_error": "「待确认」解析失败",
    "ok": "",
}

_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})[ \t]+(?P<text>.*?)[ \t]*#*[ \t]*$")
_LIST_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>[-*+]|\d+[.)、])[ \t]+(?P<text>.*)$"
)
_SECTION_NUMBER_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)+|\d+)\s*[.、)]?\s*")
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


@dataclass(frozen=True)
class PendingItem:
    key: str
    title: str
    index: int


@dataclass(frozen=True)
class ParseResult:
    section_found: bool
    structured: bool
    items: tuple[PendingItem, ...] = field(default_factory=tuple)
    reason: str = "ok"

    @property
    def reason_label(self) -> str:
        return REASON_LABELS.get(self.reason, self.reason)

    @property
    def needs_read_confirmation(self) -> bool:
        return not self.structured or not self.items


@dataclass(frozen=True)
class PendingApprovalCheck:
    allowed: bool
    message: str
    parse: ParseResult
    remaining: int


def doc_sha256(text: str | None) -> str:
    """Stable hash of the exact UTF-8 document text."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _clean_inline(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = text.replace("*", "")
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _clean_heading(text: str) -> str:
    text = _SECTION_NUMBER_RE.sub("", text or "")
    text = _clean_inline(text)
    return text.rstrip(" \t:：。.").strip()


def _clean_item_title(text: str) -> str:
    text = _clean_inline(text)
    if len(text) > MAX_ITEM_TITLE:
        return text[:MAX_ITEM_TITLE].rstrip() + "…"
    return text


def _heading_line(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line)
    if not match:
        return None
    level = len(match.group("hashes"))
    return level, _clean_heading(match.group("text"))


def _fence_toggle(line: str, fence_char: str | None) -> str | None:
    stripped = line.lstrip()
    if not stripped.startswith(("```", "~~~")):
        return fence_char
    char = stripped[0]
    if fence_char is None:
        return char
    if char == fence_char:
        return None
    return fence_char


def _item_key(doc_hash: str, index: int, title: str) -> str:
    raw = f"{doc_hash}\n{index}\n{title}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def _parse_uncached(text: str) -> ParseResult:
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    doc_hash = doc_sha256(text)

    headings: list[tuple[int, int, str]] = []
    fence_char: str | None = None
    for line_no, line in enumerate(lines):
        next_fence = _fence_toggle(line, fence_char)
        if next_fence != fence_char or line.lstrip().startswith(("```", "~~~")):
            fence_char = next_fence
            continue
        if fence_char is not None:
            continue
        parsed = _heading_line(line)
        if parsed is not None and parsed[1]:
            headings.append((line_no, parsed[0], parsed[1]))

    target: tuple[int, int, str] | None = None
    for heading in headings:
        if heading[2] == "待确认":
            target = heading
            break
    if target is None:
        return ParseResult(False, False, reason="section_missing")

    target_line, target_level, _ = target
    section_end = len(lines)
    for line_no, level, _text in headings:
        if line_no > target_line and level <= target_level:
            section_end = line_no
            break

    deeper = [
        (line_no, level, title)
        for line_no, level, title in headings
        if target_line < line_no < section_end and level > target_level
    ]
    raw_titles: list[str] = []
    if deeper:
        min_level = min(level for _line, level, _title in deeper)
        raw_titles = [
            title for _line, level, title in deeper if level == min_level
        ]
    else:
        fence_char = None
        outer_indent: int | None = None
        list_lines: list[tuple[int, str]] = []
        for line in lines[target_line + 1 : section_end]:
            next_fence = _fence_toggle(line, fence_char)
            if next_fence != fence_char or line.lstrip().startswith(("```", "~~~")):
                fence_char = next_fence
                continue
            if fence_char is not None:
                continue
            match = _LIST_RE.match(line)
            if not match:
                continue
            indent = len(match.group("indent").expandtabs(4))
            if outer_indent is None or indent < outer_indent:
                outer_indent = indent
                list_lines = [(indent, match.group("text"))]
            elif indent == outer_indent:
                list_lines.append((indent, match.group("text")))
        raw_titles = [title for _indent, title in list_lines]

    items: list[PendingItem] = []
    for index, raw_title in enumerate(raw_titles, start=1):
        title = _clean_item_title(raw_title)
        if not title:
            continue
        items.append(
            PendingItem(
                key=_item_key(doc_hash, index, title),
                title=title,
                index=index,
            )
        )

    if not items:
        return ParseResult(True, False, reason="section_empty")
    if len(items) > MAX_PENDING_ITEMS:
        return ParseResult(True, False, reason="too_many")
    return ParseResult(True, True, tuple(items), "ok")


def parse_pending_items(text: str | None) -> ParseResult:
    """Parse the design doc's 待确认 section with plain text rules only."""
    try:
        return _parse_uncached(text or "")
    except Exception as exc:  # noqa: BLE001 - parsing must degrade, never block review
        logger.warning(f"design pending-items parse failed: {exc}")
        return ParseResult(False, False, reason="parse_error")


def item_status(decision: DesignFeedback | None) -> str:
    if decision is None:
        return "待确认"
    return PENDING_STATUS_LABELS.get(decision.kind, "待确认")


def item_tone(decision: DesignFeedback | None) -> str:
    if decision is None:
        return "warning"
    if decision.kind == feedback_crud.PENDING_CONFIRM:
        return "success"
    if decision.kind == feedback_crud.PENDING_REJECT:
        return "danger"
    return "warning"


def pending_items_view(
    parse: ParseResult, decisions: dict[str, DesignFeedback]
) -> list[dict]:
    view: list[dict] = []
    for item in parse.items:
        decision = decisions.get(item.key)
        view.append(
            {
                "key": item.key,
                "title": item.title,
                "decision": decision,
                "status": item_status(decision),
                "tone": item_tone(decision),
                "body": decision.body if decision else "",
            }
        )
    return view


def pending_remaining(parse: ParseResult, decisions: dict[str, DesignFeedback]) -> int:
    if not parse.structured or not parse.items:
        return 0
    return sum(1 for item in parse.items if item.key not in decisions)


def check_pending_approval(
    db: Session,
    issue: Issue,
    *,
    doc_hash: str,
    read_confirmed: bool = False,
) -> PendingApprovalCheck:
    parse = parse_pending_items(issue.design_doc_text)
    decisions = feedback_crud.latest_decisions(db, issue.id, doc_hash)
    remaining = pending_remaining(parse, decisions)
    if parse.structured and parse.items:
        if remaining:
            return PendingApprovalCheck(
                False,
                f"还有 {remaining} 条待确认未处理",
                parse,
                remaining,
            )
        return PendingApprovalCheck(True, "", parse, 0)
    if not read_confirmed:
        return PendingApprovalCheck(
            False,
            "请先通读待确认并勾选确认",
            parse,
            0,
        )
    return PendingApprovalCheck(True, "", parse, 0)


def feedback_views(
    db: Session, issue: Issue, *, limit: int = MAX_HISTORY
) -> list[dict]:
    rows = feedback_crud.list_history(db, issue.id, limit=limit)
    job_ids = {row.job_id for row in rows if row.job_id is not None}
    jobs: dict[int, Job] = {}
    if job_ids:
        jobs = {
            job.id: job
            for job in db.scalars(select(Job).where(Job.id.in_(job_ids)))
        }
    current_hash = doc_sha256(issue.design_doc_text)
    view: list[dict] = []
    for row in rows:
        view.append(
            {
                "row": row,
                "kind_label": FEEDBACK_KIND_LABELS.get(row.kind, row.kind),
                "job": jobs.get(row.job_id) if row.job_id is not None else None,
                "is_current_doc": (row.doc_sha256 or "") == current_hash,
                "resolved": row.resolved_at is not None,
            }
        )
    return view
