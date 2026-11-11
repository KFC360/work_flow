from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.crud import job as job_crud
from app.models.issue import Issue
from app.models.repository import Repository
from app.services.config_agent import read_agent


@dataclass
class Action:
    kind: str  # button | link | text
    label: str
    href: str | None = None
    form_action: str | None = None
    confirm: str | None = None
    disabled: bool = False
    variant: str = "secondary"  # primary | secondary | warning | ghost
    icon: str | None = None


STATUS_LABELS = {
    "pending_classify": "待分类",
    "recorded": "已收录",
    "drafting": "编写中",
    "pending_codegen": "待生成",
    "generating": "生成中",
    "generated": "已生成",
    "pr_opened": "已建PR",
    "failed": "失败",
    "support_open": "待处理",
}

KIND_LABELS = {
    "feature": "功能迭代",
    "support": "人工介入",
    "pending": "待分类",
}


def path_ok(repo: Repository) -> bool:
    return bool(repo.local_path)


def actions_for(db: Session, issue: Issue, repo: Repository) -> list[Action]:
    agent = read_agent()
    queued = job_crud.has_active_for_issue(db, issue.id)
    out: list[Action] = []

    if issue.github_state == "closed":
        if issue.pr_url:
            out.append(
                Action("link", "查看 PR", href=issue.pr_url, variant="primary", icon="pr")
            )
        return out

    if issue.kind == "support":
        return out

    if issue.status == "pending_classify":
        out.append(
            Action(
                "button",
                "标为功能迭代",
                form_action=f"/issues/{issue.id}/classify/feature",
                icon="check",
            )
        )
        out.append(
            Action(
                "button",
                "标为人工介入",
                form_action=f"/issues/{issue.id}/classify/support",
                icon="life-buoy",
            )
        )
        return out

    if queued and issue.status not in {"drafting", "generating"}:
        out.append(Action("text", "排队中", disabled=True, icon="clock"))
        return out

    if issue.status in {"drafting", "generating"}:
        out.append(
            Action(
                "link",
                "查看进度",
                href=f"/issues/{issue.id}",
                variant="primary",
                icon="loader",
            )
        )
        return out

    def need_path_or_agent(
        label: str,
        form: str,
        confirm: str,
        *,
        variant: str = "primary",
        icon: str = "file-plus",
    ) -> None:
        if not path_ok(repo):
            out.append(
                Action(
                    "link",
                    "填写项目路径",
                    href=f"/repos/{repo.id}",
                    variant="secondary",
                    icon="repo",
                )
            )
        elif not agent:
            out.append(
                Action(
                    "link",
                    "配置代理",
                    href="/settings",
                    variant="secondary",
                    icon="settings",
                )
            )
        else:
            out.append(
                Action(
                    "button",
                    label,
                    form_action=form,
                    confirm=confirm,
                    variant=variant,
                    icon=icon,
                )
            )

    if issue.kind == "feature" and issue.status == "recorded":
        need_path_or_agent(
            "编写文档",
            f"/issues/{issue.id}/enqueue/write_doc",
            "将调用全站配置的代理编写设计文档并写入库内；不会提交或推送。",
            variant="primary",
            icon="file-plus",
        )
    elif issue.kind == "feature" and issue.status == "pending_codegen":
        need_path_or_agent(
            "生成代码",
            f"/issues/{issue.id}/enqueue/generate_code",
            "将调用代理生成代码，随后由系统提交、推送并创建 Pull Request。",
            variant="primary",
            icon="code",
        )
        out.append(
            Action(
                "button",
                "重新编写文档",
                form_action=f"/issues/{issue.id}/enqueue/write_doc",
                confirm="将调用代理重写，并覆盖库内文档正文；迭代号和路径不变。",
                icon="refresh",
            )
        )
    elif issue.kind == "feature" and issue.status == "generated":
        out.append(
            Action(
                "button",
                "重试创建 PR",
                form_action=f"/issues/{issue.id}/enqueue/create_pr",
                confirm="将调用 GitHub API 重新创建 PR，不重新生成代码。",
                variant="warning",
                icon="rotate",
            )
        )
    elif issue.kind == "feature" and issue.status == "failed":
        if issue.failed_action == "create_pr":
            out.append(
                Action(
                    "button",
                    "重试",
                    form_action=f"/issues/{issue.id}/enqueue/create_pr",
                    confirm="将调用 GitHub API 重新创建 PR，不重新生成代码。",
                    variant="warning",
                    icon="rotate",
                )
            )
        else:
            action = issue.failed_action or "generate_code"
            need_path_or_agent(
                "重试",
                f"/issues/{issue.id}/enqueue/{action}",
                "将重试失败步骤，可能重置系统隔离工作区；不会改动登记的本地仓库。",
                variant="warning",
                icon="rotate",
            )
    elif issue.kind == "feature" and issue.status == "pr_opened" and issue.pr_url:
        out.append(
            Action("link", "查看 PR", href=issue.pr_url, variant="primary", icon="pr")
        )

    return out
