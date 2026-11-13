# GitHub 工作流

内部工具：GitHub Issues Webhook → 公司/仓库浏览 → 编写设计文档 → 生成代码 → 创建 PR。

本仓库基石入口：`docs/README.md`；完整产品设计：`docs/architecture/design.md`。OpenSpec：`openspec/changes/github-workflow`、`docs-foundation-and-worker-observability`。

## 架构要点

- **Web**（FastAPI + Jinja2 + DaisyUI CDN）与 **Worker** 分进程，只通过 PostgreSQL 交接
- Webhook 验签后写入 **Inbox**（`webhook_delivery`）并立即 **202**；Worker 自行退避重试 GitHub 同步
- **v1 只运行一个 Worker**：Inbox 循环 + Pipeline 循环；Pipeline 全局同时只跑一条代理任务
- 代理在 `WORKTREE_ROOT` 下的隔离 git worktree 中运行，不直接污染仓库页登记的 `local_path`
- 全站代理与邮件发件（非密钥）写在项目根 `config.yaml`，设置页同一表单原子替换；SMTP 密码只走环境变量 `SMTP_PASSWORD`
- **文档驱动**：基石 `{doc_dir}/README.md` + 迭代 `{doc_dir}/v{n}-{issue}/design.md`；基石缺失时警告不阻断
- **可观测性**：Issue 详情轮询任务日志尾部（无需 SSH）；设置页展示 Worker 心跳（`logs/worker-heartbeat.json`）

## 运行形态

| 进程 | 生产 | 本地开发 / 试跑 |
| --- | --- | --- |
| PostgreSQL | **Docker Compose** 服务 `db`（数据卷持久化） | `docker compose up -d db`（映射 `127.0.0.1:55438`） |
| Web / Worker | **Docker Compose**（同一镜像，不同 command） | 终端里 `uv run` 前台跑即可 |
| Agent CLI | **宿主机** `opencode` / `claude`，同路径挂进 Worker | 本机 PATH |
| 反代 | Nginx → `127.0.0.1:8095` | 可直连本机 8095 |

生产 `DATABASE_URL` 示例（容器内）：

`postgresql+psycopg://github_workflow:密码@db:5432/github_workflow`

本机进程连 Compose 库：

`postgresql+psycopg://github_workflow:密码@127.0.0.1:55438/github_workflow`

## 快速开始（本机试跑，不是生产常驻方式）

```bash
cp .env.example .env
cp config.yaml.example config.yaml
# 填写 DATABASE_URL（本机连库用 127.0.0.1:55438）、JWT_SECRET_KEY、GITHUB_*、APP_ADMIN_PASSWORD、SMTP_PASSWORD

docker compose up -d db

# uv sync：自动创建 .venv 并安装依赖
uv sync --extra dev
uv run alembic upgrade head

# 前台试跑（关终端即停）；生产请用下面「生产部署」
uv run uvicorn main:app --host 127.0.0.1 --port 8095
uv run python -m app.tasks.worker
```

| 项 | 值 |
| --- | --- |
| 应用端口 | `8095`（生产由 Compose 绑 `127.0.0.1:8095`） |
| PostgreSQL（Compose） | 容器内 `db:5432`；宿主机排障口 `127.0.0.1:55438` |
| Webhook | `POST /api/v1/github-callback/` |
| 健康检查 | `GET /healthz` |
| 登录 | `GET/POST /login`，API `POST /token` |

## 邮件发件

`config.yaml` 的 `mail` 段只保存非密钥参数；真实密码只放环境变量 `SMTP_PASSWORD`，不写进 yaml、数据库、页面或日志。

```yaml
mail:
  enabled: false
  smtp_host: smtp.example.com
  smtp_port: 587
  security: starttls      # ssl | starttls | none
  username: ""            # 可为空（匿名中继）；密码仍要求 SMTP_PASSWORD 非空
  from_address: notify@example.com
  from_name: GitHub 工作流
  default_to: ""
```

- 设置页 `/settings` 同一表单保存代理与邮件配置；密码只显示「已配置 / 未配置」，不提供输入框。
- 修改 `.env` 里的 `SMTP_PASSWORD` 后需重启 Web / Worker 才生效。
- 页面「发送测试邮件」同步发送，最长约 10 秒；只使用已保存配置，留空收件人时用 `mail.default_to`。
- 业务代码复用 `app/services/mail.py` 的 `send_mail(to, subject, html_body, *, text_fallback=None)`；HTML 在发送入口按白名单消毒，失败抛 `MailError`。
- 未启用、缺主机 / 端口 / 发件人、缺 `SMTP_PASSWORD` 或收件人时返回明确短消息；SMTP 原始异常只写日志。
- 网易邮箱（163/126 等）请用 **465 + SSL**；发件人须与 SMTP 用户名同为完整邮箱，密码为授权码。
- 仓库页可配置多名「新 Issue 收件人」：Issue 经 Webhook 或全量同步**首次入库**时发一封通知（同一 Issue 只成功发一次）。邮件关闭或收件人为空则跳过，失败不阻断同步。建议先全量同步历史 Issue，再填写收件人，避免群发。可选 `APP_PUBLIC_BASE_URL` 在邮件中附带本系统深链。

## 生产部署

生产用 **Docker Compose** 跑 `db` + `web` + **唯一** `worker`。Agent CLI 仍装在宿主机，按相同绝对路径挂进 Worker。不要长期挂在 SSH 里的 `uv run`，也不要再装 Supervisor（旧 conf 仅作回滚参考）。

推荐布局：

1. 安装 Docker Engine + Compose 插件；部署用户可无 sudo 执行 `docker compose`
2. 项目目录放好 `.env`、`config.yaml`（见 `.env.example`：`DATABASE_URL` 用 `@db:5432`，并设 `HOST_UID` / `HOST_GID` / `HOST_HOME` / `WORKTREE_ROOT` / `REPOS_ROOT`）
3. 建 `WORKTREE_ROOT` 与 `REPOS_ROOT`（如 `/var/lib/github-workflow/worktrees`、`/home/linuxuser/repos`），保证部署用户可写
4. 宿主机安装并配置 `opencode` / `claude`（`PATH` 含 `${HOST_HOME}/.opencode/bin` 与 `${HOST_HOME}/.local/bin`）
5. `./scripts/docker_deploy.sh`（build、migrate、`up -d`、打 `/healthz`）
6. Nginx 反代到 `127.0.0.1:8095`（`deploy/nginx/api.kfc360.xyz.conf`）

从 Supervisor 切过来：见 [`deploy/docker/CUTOVER.md`](deploy/docker/CUTOVER.md)（含宿主机 Postgres dump/restore）。

```bash
cd /path/to/github_workflow   # 应用目录，如 ~/sites/work_flow
./scripts/docker_deploy.sh
docker compose ps
```

升级代码（CD 同样走这条路径）：

```bash
cd /path/to/github_workflow
git pull --ff-only origin master
./scripts/docker_deploy.sh
```

内置 skills 在 `agent_skills/`（`documentation`、`ui-ux-pro-max`、`karpathy-guidelines`）。权威在应用仓；生产挂到 **宿主机** OpenCode 全局发现路径（`./scripts/sync_opencode_skills.sh`），再随 `HOST_HOME` 挂进 Worker，**不**写入目标仓 worktree。Worker 跑 `opencode run` 时是非交互的：须在运行用户的 `~/.config/opencode/opencode.json` **预授权**检索（合并 `deploy/opencode/opencode.json.example`）：

- V1：`"permission": { "websearch": "allow", "webfetch": "allow", "question": "deny" }`
- V2：`"permissions": [{ "action": "websearch", "resource": "*", "effect": "allow" }, …]`
- 示例文件两种都写了，可整段合并进现有 provider 配置
- **不要** `"websearch": false`（会去掉工具）
- 非 OpenCode 官方 provider 时，Worker 已默认注入 `OPENCODE_ENABLE_EXA=1`（及 Parallel）；若仍无检索工具，确认 OpenCode 版本与文档

写文档任务：若代理退出码非 0 但目标 `design.md` 已写好且校验通过，系统仍记成功（避免「写完后又搜一次被取消」整单失败）。

生成代码时 Worker 可为代理创建临时库 `gw_job_{job_id}`（`AGENT_TEST_DB_ENABLED`，默认开），只把该库的 URL 注入代理环境；任务结束删除。Compose 里的 `db` 用户默认具备建库权限。

目标仓（独立 clone，如 `/home/linuxuser/repos/work_flow`）也需含基石文档（与应用仓同一远程时 `git pull` 即可）：

```bash
test -f /home/linuxuser/repos/work_flow/docs/README.md && \
test -f /home/linuxuser/repos/work_flow/docs/architecture/design.md && echo ok
```

约束：

- Worker **必须**能 `exec` 到宿主机同路径的 `opencode`/`claude`；升级 CLI 仍在宿主机做
- `local_path`、`WORKTREE_ROOT` 在容器内外路径必须一致（bind mount 同 path）
- 若仓库 `origin` 是 `git@github.com:...`，镜像需含 `openssh-client`，并把宿主机 `${HOST_HOME}/.ssh` 挂进 Worker（含可用私钥与 `known_hosts`）
- GitHub Webhook 除 `issues` / `pull_request` 外，请勾选 **Issue comments**，详情页才能增量同步讨论
- **不要** `docker compose up --scale worker=2`
- 改 `.env` / `config.yaml` 后：`docker compose up -d`（或 `./scripts/docker_deploy.sh`）重启对应服务

## 安全与运维

- 生产库在 Compose 卷 `github_workflow_pg`；Web / Worker 经服务名 `db` 连库
- 部署前轮换 Webhook Secret，只放环境变量 / `.env`，勿进 git
- Nginx：`/docs`、`/redoc`、`/openapi.json` 用 `auth_basic`；Webhook **不要** Basic Auth
- 页面 JWT + CSRF；`WORKTREE_ROOT` 示例见上
- 任务日志：`logs/jobs/{id}.log`（挂载进容器）；网页 Issue 详情可看尾部；Worker 心跳：`logs/worker-heartbeat.json`

## 测试

```bash
uv run pytest
```

CI：`.github/workflows/ci.yml` — `pull_request` / `master` push 时跑 pytest。  
CD：`.github/workflows/deploy.yml` — **PR 合并进 `master` 后** SSH 到服务器 `git pull` 并执行 `./scripts/docker_deploy.sh`。本系统只负责开到 PR；合并由人在 GitHub 完成，合并即触发 CD。

CD 需在仓库 **Settings → Secrets and variables → Actions**（Repository secrets，不要只放在 Environment）配置：`DEPLOY_HOST`、`DEPLOY_USER`、`DEPLOY_SSH_KEY`、`DEPLOY_PATH`（可选 `DEPLOY_PORT`）。服务器账号需能对该目录 `git pull`，并免交互执行 `docker compose`。

## 目录

本目录即实现根。入口：`main:app`、`python -m app.tasks.worker`。镜像：`Dockerfile`；编排：`compose.yaml`。
