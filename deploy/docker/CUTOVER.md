# 从 Supervisor 切到 Docker Compose（只做一次）

适用：这台机现在是 Supervisor 跑 Web/Worker，库在**宿主机 Postgres**；切完以后改成 Compose 跑 `db` + `web` + `worker`。Nginx 不用动，还是反代 `127.0.0.1:8095`。

下面路径按现网默认写。你的目录不一样就全局替换：

| 项 | 默认 |
| --- | --- |
| 应用目录 | `/home/linuxuser/sites/work_flow` |
| 部署用户 | `linuxuser` |
| 仓库副本目录 | `/home/linuxuser/repos` |
| worktree | `/var/lib/github-workflow/worktrees` |

---

## 0. 先具备这些

```bash
# 能免 sudo 跑 docker
docker compose version

# 应用目录里已有（不进 git）
ls /home/linuxuser/sites/work_flow/.env
ls /home/linuxuser/sites/work_flow/config.yaml

# 宿主机还能跑代理（切完也还靠它们）
which opencode || which claude
```

---

## 1. 改 `.env`

编辑 `/home/linuxuser/sites/work_flow/.env`：

同一变量只写一行；行尾不要跟 `# 注释`（部分工具会把注释吃进值里）。

```bash
# 容器里连库：主机名必须是 db，端口 5432（不要再写 127.0.0.1）
DATABASE_URL=postgresql+psycopg://github_workflow:你的密码@db:5432/github_workflow

# 下面两项先在 shell 里跑 id -u / id -g，把数字填进来
HOST_UID=1000
HOST_GID=1000
HOST_HOME=/home/linuxuser
WORKTREE_ROOT=/var/lib/github-workflow/worktrees
REPOS_ROOT=/home/linuxuser/repos
```

其它密钥（`JWT_SECRET_KEY`、`GITHUB_*`、`SMTP_PASSWORD` 等）保持原样，不要贴到聊天或 Issue 里。
---

## 2. 把宿主机库迁进 Compose 的 db

若生产库**已经**在本仓库 Compose 的 `db` 卷里，跳过本节。

若库还在宿主机 Postgres：

```bash
# 2.1 导出（在宿主机）
# 本机 socket 默认 peer：用 postgres 系统用户导出；重定向由当前 shell 写文件，避免 /tmp 属主权限问题。
sudo -u postgres pg_dump -Fc github_workflow > /tmp/gw.dump
# 或 TCP + 密码：
# pg_dump -h 127.0.0.1 -U github_workflow -Fc github_workflow > /tmp/gw.dump

# 2.2 只起 Compose 里的 Postgres
cd /home/linuxuser/sites/work_flow
git pull --ff-only origin master
docker compose up -d db

# 等健康
docker compose exec db pg_isready -U github_workflow -d github_workflow

# 2.3 灌进容器（自定义格式 dump 用下面这条）
docker compose exec -T db pg_restore \
  -U github_workflow -d github_workflow --clean --if-exists < /tmp/gw.dump
```

明文 SQL 导出则：

```bash
pg_dump -U github_workflow github_workflow -f /tmp/gw.sql
docker compose exec -T db psql -U github_workflow -d github_workflow < /tmp/gw.sql
```

灌完后用 Compose 映射口核对（**不是**宿主机 5432 socket）：

```bash
# compose.yaml 里默认库密码是 github_workflow（与宿主机旧密码可能不同）
# .env 的 DATABASE_URL 密码必须与此一致，否则 Web/Worker 连不上 db
docker compose exec db \
  psql -U github_workflow -d github_workflow -c '\dt'
docker compose exec db \
  psql -U github_workflow -d github_workflow -c 'SELECT count(*) FROM alembic_version;'
```

若 `.env` 里仍是宿主机旧密码（例如 `123456`），改成与 Compose 一致：

`DATABASE_URL=postgresql+psycopg://github_workflow:github_workflow@db:5432/github_workflow`

---

## 3. 停 Supervisor，空出 8095

```bash
sudo supervisorctl stop 'github-workflow:*'
sudo supervisorctl status 'github-workflow:*'
# 确认没有进程占 8095
ss -lntp | grep 8095 || echo '8095 free'
```

可选：删掉 `/etc/supervisor/conf.d/github-workflow.conf`，再 `sudo supervisorctl reread && sudo supervisorctl update`，避免开机又拉起来。

---

## 4. 起全栈

```bash
cd /home/linuxuser/sites/work_flow
chmod +x scripts/docker_deploy.sh
./scripts/docker_deploy.sh
```

脚本会：同步 OpenCode skills → build 镜像 → 起 db → `alembic upgrade` → `up -d` → 打 `http://127.0.0.1:8095/healthz`。

---

## 5. 验收

```bash
curl -fsS http://127.0.0.1:8095/healthz
docker compose ps
docker compose exec worker which opencode
# 或：docker compose exec worker which claude
```

浏览器：能登录、设置页有 Worker 心跳、试发一封邮件。

---

## 回滚（出问题再动）

```bash
cd /home/linuxuser/sites/work_flow
docker compose down

# 若还要回到「宿主机 Postgres + Supervisor」：
# 把 .env 的 DATABASE_URL 改回 127.0.0.1:5432（或你原来的端口），再：
sudo supervisorctl start 'github-workflow:*'
```

数据已迁进 Compose 卷时，回滚 Supervisor **不会**自动带回旧库；需要的话再 `pg_dump` 容器库灌回宿主机。
