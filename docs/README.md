# GitHub 工作流 · 基石文档

本文档是本仓库的**基石入口**（`docs/README.md`）。功能迭代设计写在 `docs/v{迭代序号}-{Issue编号}/design.md`，描述相对本基石的增量，不替代本入口。

编写文档 / 生成代码时：**先读本入口，再读** [`docs/architecture/design.md`](architecture/design.md)（完整产品设计，已从历史稿迁入本仓）。

## 文档驱动约定

1. 改架构、模块边界、状态机或数据模型 → 先更新基石（本文件及 `docs/architecture/`）。
2. 单个功能 Issue → 走系统流水线写出迭代设计，再生成代码与 PR。
3. 代理写文档 / 写代码必须先读本入口与 `docs/architecture/design.md`；若缺失，迭代文档「待确认」须写明。

## 系统要点（摘要）

- 生产用 Docker Compose（`db` + `web` + 唯一 `worker`）；`opencode`/`claude` 仍在宿主机并同路径挂进 Worker。切换说明：`deploy/docker/CUTOVER.md`。
- Web（FastAPI）与唯一 Worker 分进程，经 PostgreSQL 交接。
- Webhook 验签后入 Inbox 并 202；Worker 同步 GitHub 并跑流水线。
- 编写文档 / 生成代码在 `WORKTREE_ROOT` 隔离 worktree 中执行，不污染登记的 `local_path`。
- 「待生成」的设计文档经人工批准（`issue.doc_approved_at`）后才可生成代码；修订、重写、人工编辑都会使批准失效。
- Issue 详情正文卡默认折叠（首行 + 省略 + 末两行），无 JS 时显示全文；生成代码前可在设计文档卡内人工编辑，保存会清空批准，进入生成阶段后返回 409 拒绝写库。
- 迭代文档路径：`docs/v{n}-{issue}/design.md`；基石入口：`docs/README.md`；完整设计：`docs/architecture/design.md`。
- Issue 详情可轮询任务日志尾部；Worker 心跳：`logs/worker-heartbeat.json`。
- Worker 内置 OpenCode skills：`agent_skills/`（`documentation`、`ui-ux-pro-max`、`karpathy-guidelines`），部署挂到 `~/.config/opencode/skills`，不写进目标仓。
- 设置页管理全站代理与邮件发件（非密钥）；SMTP 密码只走环境变量 `SMTP_PASSWORD`，页面只显示「已配置 / 未配置」，试发使用已保存配置。
- 仓库页可配多名新 Issue 收件人；Issue 首次入库时通知一次（Webhook / 全量同步共用）。全量同步历史数据前请先留空收件人。

## 文档索引

| 主题 | 位置 |
| --- | --- |
| 完整产品设计（目标、决策、数据模型、状态机、部署等） | [`docs/architecture/design.md`](architecture/design.md) |
| 本入口（发现路径与约定） | `docs/README.md` |
| 功能迭代增量 | `docs/v{n}-{issue}/design.md` |

后续若把 `architecture/design.md` 拆成多文件，仍由本入口索引；系统只强制读取本入口路径。
