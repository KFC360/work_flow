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

| 进程 | 生产 | 本地开发 / 试跑 |
| --- | --- | --- |
| PostgreSQL | **宿主机**系统服务，不用 Compose | 可选 `compose.yaml`（端口 `55438`） |
| Web / Worker | **Supervisor** 常驻（见下）；只绑 `127.0.0.1`，前面用 Nginx | 终端里 `uv run` 前台跑即可 |
| 反代 | Nginx → `127.0.0.1:8095` | 可直连本机 8095 |

`DATABASE_URL` 示例：

`postgresql+psycopg://github_workflow:密码@127.0.0.1:5432/github_workflow`

## 快速开始（本机试跑，不是生产常驻方式）

```bash
cp .env.example .env
cp config.yaml.example config.yaml
# 填写 DATABASE_URL、JWT_SECRET_KEY、GITHUB_*、APP_ADMIN_PASSWORD

# uv sync：自动创建 .venv 并安装依赖
uv sync --extra dev
uv run alembic upgrade head

# 前台试跑（关终端即停）；生产请用下面「生产部署」
uv run uvicorn main:app --host 127.0.0.1 --port 8095
uv run python -m app.tasks.worker
```

| 项 | 值 |
| --- | --- |
| 应用端口 | `8095`（仅本机） |
| PostgreSQL（生产） | 宿主机 `5432`（或你的实际端口） |
| Webhook | `POST /api/v1/github-callback/` |
| 健康检查 | `GET /healthz` |
| 登录 | `GET/POST /login`，API `POST /token` |

## 生产部署

仍是同一套 Python 应用，生产用 **Supervisor** 保活。不要长期挂在 SSH 里的 `uv run`。

推荐布局：

1. 宿主机 PostgreSQL：建用户 / 库 / schema
2. 项目目录放好 `.env`、`config.yaml`，`uv sync`，`uv run alembic upgrade head`
3. 建 `WORKTREE_ROOT`（如 `/var/lib/github-workflow/worktrees`），保证运行用户可写
4. **Supervisor**：Web + **唯一** Worker（示例 `deploy/supervisor/github-workflow.conf`）
5. Nginx 反代到 `127.0.0.1:8095`（`deploy/nginx/api.kfc360.xyz.conf`）

```bash
# 按机器改 conf 里的 directory / user / uv 路径后：
sudo cp deploy/supervisor/github-workflow.conf /etc/supervisor/conf.d/
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start github-workflow:*
sudo supervisorctl status
```

升级代码：

```bash
cd /path/to/github_workflow
git pull
uv sync --extra dev
uv run alembic upgrade head
sudo supervisorctl restart github-workflow-web github-workflow-worker
```

## 安全与运维

- 生产库在宿主机维护；Web / Worker 经 `127.0.0.1` 连库
- 部署前轮换 Webhook Secret，只放环境变量 / `.env`，勿进 git
- Nginx：`/docs`、`/redoc`、`/openapi.json` 用 `auth_basic`；Webhook **不要** Basic Auth
- 页面 JWT + CSRF；`WORKTREE_ROOT` 示例见上

## 测试

```bash
uv run pytest
```

## 目录

本目录即实现根。入口：`main:app`、`python -m app.tasks.worker`。
