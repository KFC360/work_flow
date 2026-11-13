# GitHub Workflow

[![CI](https://github.com/KFC360/work_flow/actions/workflows/ci.yml/badge.svg)](https://github.com/KFC360/work_flow/actions/workflows/ci.yml)
[![Deploy](https://github.com/KFC360/work_flow/actions/workflows/deploy.yml/badge.svg)](https://github.com/KFC360/work_flow/actions/workflows/deploy.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![uv](https://img.shields.io/badge/packaging-uv-DE5FE9.svg)](https://github.com/astral-sh/uv)

从 GitHub Issue 到设计文档、代码生成与 Pull Request 的**文档驱动**流水线。

Webhook 验签入库 → 按「公司 / 仓库 / Issue」浏览 → 操作员触发「编写文档」→ 人工批准 → 「生成代码」→ 系统建 PR。Web 与 Worker 分进程，经 PostgreSQL 交接；代理（OpenCode 或 Claude Code）在隔离 git worktree 中执行，不污染登记的仓库工作副本。

> **文档入口**：[docs/README.md](docs/README.md)（基石）· [docs/architecture/design.md](docs/architecture/design.md)（完整产品设计）

---

## 功能概览

| 能力 | 说明 |
| --- | --- |
| Webhook Inbox | `issues` / `pull_request` / `issue_comment` 验签后入队并 **202**；Worker 退避重试 |
| 公司 → 仓库 → Issue | 服务端渲染（FastAPI + Jinja2 + DaisyUI CDN），无前端构建 |
| 编写文档 / 生成代码 | 全站二选一代理；设计文档须人工批准后才可生成代码 |
| 讨论与动态 | 同步 GitHub 评论与关闭 / type / PR 合并等事件（评论不进入代理提示词） |
| 新 Issue 邮件 | 仓库可配置多名收件人；Issue **首次入库**通知一次 |
| 可观测性 | Issue 详情轮询任务日志尾部；Worker 心跳 `logs/worker-heartbeat.json` |
| 部署冒烟 | CD 成功后 Playwright 登录探测，结果邮件通知 |

---

## 架构

```mermaid
flowchart LR
  GH[GitHub] -->|Webhook| Web[Web FastAPI]
  Web -->|webhook_delivery| PG[(PostgreSQL)]
  Worker[Worker] --> PG
  Worker -->|REST / git| GH
  Worker -->|opencode / claude| Agent[Host Agent CLI]
  Agent --> WT[WORKTREE_ROOT worktree]
  User[Operator] -->|HTTPS| Nginx
  Nginx --> Web
```

| 进程 | 生产 | 本地开发 |
| --- | --- | --- |
| PostgreSQL | Compose 服务 `db`（卷持久化） | `docker compose up -d db` → `127.0.0.1:55438` |
| Web / Worker | Compose（同镜像、不同 command） | `uv run` 前台各起一个进程 |
| Agent CLI | 宿主机安装，**同绝对路径**挂进 Worker | 本机 `PATH` |
| 反代 | Nginx → `127.0.0.1:8095` | 可直连 `8095` |

**约束（请务必遵守）：**

- v1 **只跑一个 Worker**，不要 `docker compose up --scale worker=2`
- `local_path`、`WORKTREE_ROOT`、`REPOS_ROOT` 在容器内外路径一致（bind mount 同 path）
- SSH 远程仓库需挂载宿主机 `${HOST_HOME}/.ssh`（私钥 + `known_hosts`）

---

## 技术栈

| 层 | 选型 |
| --- | --- |
| 运行时 | Python ≥ 3.11，[uv](https://github.com/astral-sh/uv) |
| Web | FastAPI、Jinja2、DaisyUI / Tailwind（CDN） |
| 数据 | PostgreSQL、SQLAlchemy 2、Alembic |
| 安全 | JWT + CSRF、pwdlib (Argon2)、Webhook HMAC |
| 出站 | httpx（GitHub API）、subprocess（git / 代理） |
| 部署 | Docker Compose、Nginx；CD：GitHub Actions → SSH |

---

## 快速开始

### 前置条件

- Docker Engine + Compose 插件
- [uv](https://docs.astral.sh/uv/)
- （可选，跑流水线时）本机已安装 `opencode` 或 `claude`

### 本机试跑

```bash
git clone https://github.com/KFC360/work_flow.git
cd work_flow

cp .env.example .env
cp config.yaml.example config.yaml
# 编辑 .env：JWT_SECRET_KEY、APP_ADMIN_PASSWORD、GITHUB_*、SMTP_PASSWORD（可选）
# 本机连库请用：
# DATABASE_URL=postgresql+psycopg://github_workflow:github_workflow@127.0.0.1:55438/github_workflow

docker compose up -d db

uv sync --extra dev
uv run alembic upgrade head

# 终端 1 — Web
uv run uvicorn main:app --host 127.0.0.1 --port 8095

# 终端 2 — Worker
uv run python -m app.tasks.worker
```

打开 <http://127.0.0.1:8095/login>，使用 `.env` 中的 `APP_ADMIN_USER` / `APP_ADMIN_PASSWORD` 登录。

| 端点 | 说明 |
| --- | --- |
| `GET /healthz` | 健康检查 |
| `GET/POST /login` | 页面登录 |
| `POST /token` | API 令牌 |
| `POST /api/v1/github-callback/` | GitHub Webhook（勿加 Basic Auth） |

---

## 配置

### 环境变量（`.env`）

完整模板见 [`.env.example`](.env.example)。常用项：

| 变量 | 用途 |
| --- | --- |
| `DATABASE_URL` | 生产容器内用 `@db:5432`；本机试跑用 `127.0.0.1:55438` |
| `GITHUB_WEBHOOK_SECRET` / `GITHUB_TOKEN` | Webhook 验签与 API |
| `APP_ADMIN_USER` / `APP_ADMIN_PASSWORD` | 初始管理员 |
| `JWT_SECRET_KEY` | 会话签名 |
| `WORKTREE_ROOT` / `REPOS_ROOT` | 隔离 worktree 与仓库 clone 父目录 |
| `HOST_UID` / `HOST_GID` / `HOST_HOME` | Compose 挂载与进程身份 |
| `SMTP_PASSWORD` | 邮件密码（**只**放环境变量） |
| `SMOKE_NOTIFY_TO` / `SMOKE_BASE_URL` | 部署后登录冒烟通知 |

密钥与 `.env`、`config.yaml` **不要提交**到 git。

### 应用配置（`config.yaml`）

由 [`config.yaml.example`](config.yaml.example) 复制。设置页可改全站代理与邮件非密钥字段：

```yaml
agent: opencode   # 或 claude

mail:
  enabled: false
  smtp_host: smtp.example.com
  smtp_port: 587
  security: starttls   # ssl | starttls | none
  username: ""
  from_address: notify@example.com
  from_name: GitHub 工作流
  default_to: ""
```

- 密码仅环境变量 `SMTP_PASSWORD`；页面只显示「已配置 / 未配置」
- 网易系邮箱建议 **465 + SSL**，发件人与 SMTP 用户名为同一完整邮箱，密码用授权码
- 修改 `.env` 中的 `SMTP_PASSWORD` 后需重启 Web / Worker

### 新 Issue 邮件

仓库页配置「新 Issue 收件人」列表。Issue 经 Webhook 或全量同步**首次入库**时发送一次；失败不阻断同步。建议先同步历史 Issue、再填写收件人，避免群发。可选 `APP_PUBLIC_BASE_URL` 在邮件中附带本系统深链。

---

## 生产部署

生产使用 Compose 跑 **`db` + `web` + 唯一 `worker`**。Agent CLI 留在宿主机。

1. 部署用户可无 sudo 执行 `docker compose`
2. 准备 `.env`、`config.yaml`（`DATABASE_URL` 指向 `@db:5432`，并设置 `HOST_*` / `WORKTREE_ROOT` / `REPOS_ROOT`）
3. 创建并可写 `WORKTREE_ROOT`、`REPOS_ROOT`
4. 安装 `opencode` / `claude`，保证容器内 `PATH` 能 `exec` 到同路径二进制
5. 执行部署脚本并配置 Nginx 反代 `127.0.0.1:8095`

```bash
cd /path/to/work_flow          # 例如 ~/sites/work_flow
./scripts/docker_deploy.sh     # build → migrate → up → /healthz
docker compose ps
```

升级：

```bash
git pull --ff-only origin master
./scripts/docker_deploy.sh
```

从 Supervisor 迁移、Postgres dump/restore：见 [`deploy/docker/CUTOVER.md`](deploy/docker/CUTOVER.md)。  
Nginx 示例：[`deploy/nginx/api.kfc360.xyz.conf`](deploy/nginx/api.kfc360.xyz.conf)。

### GitHub Webhook

在目标组织/仓库配置回调：`https://<你的域名>/api/v1/github-callback/`

建议勾选事件：

- **Issues**
- **Pull requests**
- **Issue comments**（详情页「讨论与动态」增量同步需要）

Secret 与 `.env` 中 `GITHUB_WEBHOOK_SECRET` 一致。Webhook 路径**不要**挂 Nginx Basic Auth。

### OpenCode skills

内置 skills 在 [`agent_skills/`](agent_skills/)（`documentation`、`ui-ux-pro-max`、`karpathy-guidelines`）。生产同步到宿主机发现路径：

```bash
./scripts/sync_opencode_skills.sh
```

非交互 `opencode run` 须预授权检索，见 [`deploy/opencode/opencode.json.example`](deploy/opencode/opencode.json.example)。skills **不**写入目标仓 worktree。

### 目标仓基石文档

被流水线操作的仓库工作副本需包含基石文档（与本仓约定一致时 `git pull` 即可）：

```bash
test -f "$REPOS_ROOT/<repo>/docs/README.md" && \
test -f "$REPOS_ROOT/<repo>/docs/architecture/design.md" && echo ok
```

---

## CI / CD

| 工作流 | 触发 | 行为 |
| --- | --- | --- |
| [ci.yml](.github/workflows/ci.yml) | `pull_request`、`push` → `master` | `uv` + pytest（Compose Postgres 服务） |
| [deploy.yml](.github/workflows/deploy.yml) | `push` → `master`、手动 | SSH → `git pull` → `docker_deploy.sh` → 等待 30s → 登录冒烟 |

**Repository secrets（CD）：** `DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_SSH_KEY`、`DEPLOY_PATH`（可选 `DEPLOY_PORT`）。

**部署冒烟**（读服务器 `.env`，不额外占用 GitHub Secrets）：

1. 配置 `APP_ADMIN_*`、`SMTP_PASSWORD`、`SMOKE_NOTIFY_TO`（多个邮箱可用逗号 / 分号 / 空白分隔；留空则只测登录不发信）
2. 可选 `SMOKE_BASE_URL`（默认 `https://api.kfc360.xyz`）
3. 在官方镜像 `mcr.microsoft.com/playwright:v1.65.0-jammy`（`--network host`）中执行，无需在宿主机安装 Chromium 系统库
4. 登录或发信失败会使 CD 失败；截图目录：`logs/smoke/`

本仓库只负责开到 PR；**合并进 `master` 由人完成**，合并即触发 CD。

---

## 开发

```bash
uv sync --extra dev
uv run pytest -q
```

常用脚本：

| 脚本 | 作用 |
| --- | --- |
| [`scripts/docker_deploy.sh`](scripts/docker_deploy.sh) | 生产构建 / 迁移 / 启动 / 健康检查 |
| [`scripts/db_migrate.sh`](scripts/db_migrate.sh) | Alembic 升级 |
| [`scripts/sync_opencode_skills.sh`](scripts/sync_opencode_skills.sh) | 同步内置 skills |
| [`scripts/smoke_login_notify.sh`](scripts/smoke_login_notify.sh) | 部署后登录冒烟 + 邮件 |

生成代码任务可按需为代理创建临时库 `gw_job_{id}`（`AGENT_TEST_DB_ENABLED`，默认开启），任务结束删除。

---

## 目录结构

```text
.
├── app/                 # FastAPI 应用、Worker、模板、迁移
├── agent_skills/        # 内置 OpenCode skills（不写入目标仓）
├── deploy/              # Nginx、OpenCode 示例、Docker cutover、旧 Supervisor
├── docs/                # 基石与架构设计、功能迭代设计
├── scripts/             # 部署 / 迁移 / 冒烟 / skills 同步
├── tests/               # pytest
├── compose.yaml         # db + web + worker
├── Dockerfile
├── main.py              # ASGI 入口
├── config.yaml.example
└── .env.example
```

入口：`main:app`（Web）、`python -m app.tasks.worker`（Worker）。

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/README.md](docs/README.md) | 基石入口与约定 |
| [docs/architecture/design.md](docs/architecture/design.md) | 目标、决策、数据模型、状态机、部署 |
| [docs/vNNNN-N/design.md](docs/) | 单 Issue 迭代增量设计 |
| [deploy/docker/CUTOVER.md](deploy/docker/CUTOVER.md) | Supervisor → Compose 切换 |

约定：改架构 / 模块边界 / 状态机 / 数据模型 → 先更新基石；单功能 Issue → 先写迭代设计再实现。

---

## 安全提示

- Webhook Secret、GitHub Token、JWT、SMTP 密码、管理员口令仅放环境变量 / 服务器 `.env`
- 生产库经 Compose 卷 `github_workflow_pg`；Web / Worker 用服务名 `db` 连接
- Nginx 可对 `/docs`、`/redoc`、`/openapi.json` 使用 Basic Auth；**Webhook 路径除外**
- 页面操作为 JWT Cookie + CSRF；日志避免打印密钥与 `Authorization` 头

---

## 贡献

1. Fork / 建分支，保持变更聚焦
2. `uv sync --extra dev && uv run pytest -q`
3. 涉及行为或数据模型时，同步更新 `docs/` 中对应设计
4. 开 PR；合并进 `master` 后由 CD 部署

问题与需求请优先用 GitHub Issues（功能迭代请打相应 type / 标签，便于本系统流水线识别）。

---

## 许可证

本仓库暂未放置 `LICENSE` 文件。若对外开源，请在根目录补充许可证并在此节更新说明。
