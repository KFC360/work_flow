# GitHub 工作流

内部工具：GitHub Issues Webhook → 公司/仓库浏览 → 编写设计文档 → 生成代码 → 创建 PR。

产品设计见仓库根目录 `docs/github_workflow/design.md`。OpenSpec 变更：`openspec/changes/github-workflow`。

## 架构要点

- **Web**（FastAPI + Jinja2 + DaisyUI CDN）与 **Worker** 分进程，只通过 PostgreSQL 交接
- Webhook 验签后写入 **Inbox**（`webhook_delivery`）并立即 **202**；Worker 自行退避重试 GitHub 同步
- **v1 只运行一个 Worker**：Inbox 循环 + Pipeline 循环；Pipeline 全局同时只跑一条代理任务
- 代理在 `WORKTREE_ROOT` 下的隔离 git worktree 中运行，不直接污染仓库页登记的 `local_path`
- 全站代理写在项目根 `config.yaml`（`opencode` | `claude`），设置页原子替换

## 运行形态

| 进程 | 生产 | 本地开发 |
| --- | --- | --- |
| PostgreSQL | **跑在宿主机**（系统服务 / 本机安装），不用 Compose | 可用 `compose.yaml` 起临时库，端口 `55438` |
| Web / Worker | 宿主机进程（需可见 `git`、代理命令与仓库副本） | 同左，`uv run` 启动 |

`DATABASE_URL` 指向本机可达的库即可，例如：

`postgresql+psycopg://github_workflow:github_workflow@127.0.0.1:5432/github_workflow`

（开发若用 Compose，主机端口为 `55438`。）

## 快速开始

```bash
cp .env.example .env
cp config.yaml.example config.yaml
# 填写 DATABASE_URL、JWT_SECRET_KEY（建议 openssl rand -hex 32）、GITHUB_*、APP_ADMIN_PASSWORD

# 仅本地可选：docker compose up -d   # 起开发用 PostgreSQL
# 生产：使用宿主机已安装的 PostgreSQL，不要依赖 compose 起库

uv sync --extra dev
uv run alembic upgrade head
uv run uvicorn main:app --host 127.0.0.1 --port 8095
uv run python -m app.tasks.worker
```

| 项 | 值 |
| --- | --- |
| 应用端口 | `8095` |
| PostgreSQL（生产） | 宿主机；`DATABASE_URL` 连本机 |
| PostgreSQL（Compose 开发） | 映射主机 `55438` |
| Webhook | `POST /api/v1/github-callback/` |
| 健康检查 | `GET /healthz` |
| 登录 | `GET/POST /login`，API 令牌 `POST /token` |

## 安全与部署

- 生产库在宿主机维护（备份、账号、库名 `github_workflow` / schema `github_workflow`）；Web 与 Worker 同样跑在该机，经 `127.0.0.1` 访问数据库
- 部署前在 GitHub **轮换** Webhook Secret，只通过环境变量 `GITHUB_WEBHOOK_SECRET` 注入，勿写入文档或 git
- Nginx 示例：`deploy/nginx/api.kfc360.xyz.conf`
  - `/docs`、`/redoc`、`/openapi.json`：`auth_basic`，口令文件 `/etc/nginx/htpasswd/github_workflow_docs`（`htpasswd` 生成，不进 git）
  - 其余路径反代到 `127.0.0.1:8095`；Webhook **不要** Basic Auth
- 页面 JWT 放在 HttpOnly cookie；POST 校验由 JWT `jti` 派生的 CSRF
- `WORKTREE_ROOT` 示例：`/var/lib/github-workflow/worktrees`

## 测试

```bash
uv run pytest
```

代理与 git 在测试中可替换。本机核对 Claude / OpenCode 无界面参数见设计稿「待确认」；可用 `CLAUDE_ARGS` / `OPENCODE_ARGS` 整段替换。

## 目录

实现目录即本目录 `github_workflow/`。入口：`main:app`、`python -m app.tasks.worker`。
