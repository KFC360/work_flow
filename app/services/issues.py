from __future__ import annotations

FEATURE_LABEL = "功能迭代"
SUPPORT_LABEL = "人工介入"

KIND_PENDING = "pending"
KIND_FEATURE = "feature"
KIND_SUPPORT = "support"

STATUS_PENDING_CLASSIFY = "pending_classify"
STATUS_RECORDED = "recorded"
STATUS_SUPPORT_OPEN = "support_open"

LOCKED_STATUSES = {
    "drafting",
    "pending_codegen",
    "generating",
    "generated",
    "pr_opened",
    "failed",
}


def classify_labels(label_names: list[str]) -> tuple[str, str]:
    names = set(label_names)
    has_feature = FEATURE_LABEL in names
    has_support = SUPPORT_LABEL in names
    if has_feature and not has_support:
        return KIND_FEATURE, STATUS_RECORDED
    if has_support and not has_feature:
        return KIND_SUPPORT, STATUS_SUPPORT_OPEN
    return KIND_PENDING, STATUS_PENDING_CLASSIFY


def kind_locked(status: str) -> bool:
    return status in LOCKED_STATUSES


def design_doc_relpath(doc_dir: str, iteration_no: int, issue_number: int) -> str:
    return f"{doc_dir.rstrip('/')}/v{iteration_no:04d}-{issue_number}/design.md"


def codegen_branch_name(issue_number: int) -> str:
    """Feature branch for generate_code / PR head. Never the default branch."""
    return f"dev_{int(issue_number)}"


def is_legacy_codegen_branch(branch_name: str | None, issue_number: int) -> bool:
    if not branch_name:
        return False
    return branch_name in {f"issue/{issue_number}", f"issue-{issue_number}"}
