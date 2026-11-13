# v0014-28 Issue 详情同步后续评论与时间线事件

> 迭代：v0014 · Issue #28。相对基石 [`docs/README.md`](../README.md) 与 [`docs/architecture/design.md`](../architecture/design.md) 的增量。

## 1. 背景

本地只持久化并展示 `issue.body`。GitHub 上后续评论、type 变更、关闭/重开、关联 PR 合并等不会出现在本站详情页。Webhook 当前仅接收 `issues` / `pull_request`。

## 2. 目标

1. 同步并展示 Issue **评论**（创建 / 编辑更新原文 / 删除软删）。
2. 同步并展示选定**事件**：`closed` / `reopened` / `typed` / `untyped` / `pr_merged` / `pr_closed`。
3. 详情页「Issue 正文」下增加「讨论与动态」卡片，按时间升序。
4. Webhook 增量 + 仓库同步 Issues / 单 Issue 刷新时回填评论；失败不阻断 Issue/PR 状态同步。
5. 编写文档 / 生成代码**仍只用 Issue 正文**，评论不进代理提示词。

## 3. 非目标

- 本站不回复 GitHub；不做完整 Timeline（reactions、rename 等）。
- 不对历史 type/close 做 Timeline API 全量考古（仅评论 API 回填 + 事件从 Webhook/PR 同步起增量）。

## 4. 已锁定决策（对应 Issue「待确认」）

| # | 决定 |
| --- | --- |
| 1 | 评论 + 选定事件（上表） |
| 2 | 编辑更新正文；删除设 `deleted_at`，UI 显示「已删除」 |
| 3 | 评论**不**进入代理上下文 |
| 4 | 仓库同步 Issues 时对每条 Issue 拉评论；单 Issue 刷新 / 打开详情时 best-effort 补拉 |
| 5 | 独立「讨论与动态」卡片 |

## 5. 方案摘要

- 表 `issue_message`：`source_kind`=`comment`|`event`，评论用 `github_comment_id` 唯一；事件用 `event_key`（如 `pr_merged:123`）唯一。
- `GET /repos/{o}/{r}/issues/{n}/comments` 分页回填；Webhook 增加 `issue_comment`；`issues` 的 closed/reopened/typed/untyped 写事件行；PR merged/closed 写事件行。
- UI：Markdown 渲染评论正文（复用 `render_issue_body`）；事件行用短文案。

## 6. 验收

- 有评论的 Issue 同步后详情可见评论。
- 新评论经 Webhook 或同步出现；编辑/删除语义正确。
- 关闭 / type / PR 合并至少各有一类事件可展示。
- 评论 API 失败时 Issue 同步仍成功。
- 编写文档提示词不含评论。
