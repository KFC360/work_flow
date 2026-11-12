# 页脚贴底、仓库配置防溢出、Issue 手动对账与 GitHub type/labels（v0007 / Issue #14）

- 迭代：`v0007`，对应 GitHub Issue `#14`
- 文档路径：`docs/v0007-14/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：**布局修复 + Issue 只读同步补偿 + 数据模型增量**。不改写文档 / 生成代码状态机，不改 Webhook 验签与 Inbox 退避机制，不改 Job 入队条件与 PR 创建流程。

## 1. 背景

控制台已切到 daisyUI 5，但近期仍有四处体验与数据缺口：

1. **页脚不贴底**：`app/templates/base.html` 的 `body` 目前只是 `min-h-dvh` 的普通块级容器，`main` 没有伸展。内容少的页面（空 Issue 列表、设置页、404）页脚会停在内容之后、视口中间，而不是视口底部。
2. **仓库本地配置输入溢出**：`/repos/{id}` 右侧「本地配置」卡片位于 `lg:grid-cols-3` 的 `lg:col-span-1` 栏。卡片、`card-body`、`fieldset` 都是默认的 `min-width: auto`，而 `input` 又使用 `w-full`；长路径、等宽字体和 `fieldset` 的 `min-inline-size: min-content` 叠加后，输入框会把右栏撑破，甚至横向溢出到左侧「GitHub 资料」卡片。
3. **Issue 列表缺少手动对账入口**：`/repos/{id}/issues` 主要依赖 Webhook 被动更新。操作员在 GitHub 上批量改开闭、标签或标题后，若 Webhook 丢失、未配置或处理失败，列表只能等下一次事件，无法一键拉齐。现有 `POST /issues/{id}/refresh` 只刷新单条 Issue，且明确不软删除、不刷新 PR 状态。
4. **GitHub type 未入库，labels 展示不足**：GitHub Issue 已有独立的 **type**（与 labels、与本地 `kind` 都不同）。当前 `issue` 表只有 `label_names`，没有 type 列；列表和详情只把 labels 用于 `功能迭代` / `人工介入` 的 `kind` 分流，没有展示标签，也没有展示 type。

补充基线现状：

| 位置 | 现状 |
| --- | --- |
| `app/templates/base.html` | `body`、`main`、`footer` 依次排列；`footer` 无粘底布局 |
| `app/templates/repo.html` | 右栏 `section.card` / `card-body` / `fieldset` 未约束 `min-w-0`；两处 `input` 为 `w-full font-mono text-sm` |
| `app/templates/issues.html` | 页头只有结果条数；筛选为 `kind` / `status` / `pr_state` / `github_state`；表格列为编号、标题、类型、状态、更新、操作 |
| `app/api/v1/issues.py` | 已有单条 `POST /issues/{issue_id}/refresh`，未做全仓分页对账 |
| `app/services/ingest.py` | Webhook 与单条刷新共用 `apply_issue_action` / `refresh_issue_from_github` 的字段映射 |
| `app/crud/issue.py` | `upsert_from_webhook` 每次写入后立即 `commit`，便于单条事件，不适合全仓批量事务 |
| `app/services/pr_sync.py` | 已有 `pr_state` 的 open / merged / closed 派生规则与时间戳守卫 |
| `app/models/issue.py` | 有 `label_names`、`pr_number`、`pr_state`、`pr_url`、`deleted_at`，无 Issue type 列 |

因此本迭代的重点是：**用标准 flex 修页脚、用布局约束修输入溢出、增加一个同步补偿入口，并把 GitHub type 与 labels 作为只读展示数据补齐**。

## 2. 目标

### 2.1 短页 footer 贴视口底部

- 已登录壳（`base.html`）在内容不足一屏时，`footer` 贴在视口底部；内容超过一屏时，`footer` 仍在文档流末尾，随页面滚动。
- 使用标准 flex 粘底：外壳 `min-h-dvh` + `flex flex-col`，`main` 伸展占满剩余高度，`footer` 不 `position: fixed`。
- 不遮挡主内容、按钮、确认弹窗或页面内滚动区域。
- 404 页继承 `base.html`，一并生效；登录页没有页脚，检查其整屏居中不被改坏。

### 2.2 `/repos/{id}` 本地配置输入不溢出

- 「服务器项目路径」「文档目录」两个输入框宽度限制在卡片内容区内，不撑破 `card` / `card-body`，不横向溢出到邻栏。
- 桌面窄右栏（`lg:col-span-1`）与小屏单列均验收；长路径仍可通过输入框内部横向滚动查看，并保留 `font-mono`。
- 继续使用 daisyUI `card` / `fieldset` / `label` / `input`，只补布局与 `min-w-0`，不自研输入组件。
- 长路径可读性优先：输入框不截断值，浏览器原生内部滚动即可；可加 `title` 属性显示完整值。

### 2.3 Issue 列表增加「手动更新 Issues 状态」

- 在 `/repos/{id}/issues` 页头增加按钮「手动更新 Issues 状态」。
- 行为固定为**对该仓库做全量分页对账**，范围包含 GitHub 上 open 与 closed 的 Issue。
- 按 GitHub 分页拉完后再进入写阶段；任何一页失败都不写业务数据，避免用不完整集合做软删除。
- 写回至少包括：`github_state`、标题、正文、链接、作者、`github_updated_at`、`label_names`、GitHub type。
- 对已有 `pr_number` 的 Issue 一并刷新 PR 状态（`pr_state`、`pr_merged_at`、`pr_state_updated_at`、`pr_url`）。
- 远端已删除、本地仍在：只填 `deleted_at`，不改 `status`、`kind`、`github_state` 等流程字段；列表默认不显示。
- 交互：`POST` + CSRF；提交后按钮禁用并显示 loading；结束后 303 回列表并 flash 摘要（新增 / 更新 / 软删 / PR 刷新 / 失败原因）。
- 手动同步是 Webhook 的补偿通道，不替代 Webhook，也不改变排队 / 执行中的 Job 语义。

### 2.4 支持 GitHub Issue type 与 labels

**Labels**

- Webhook、单条刷新、本次全仓手动同步继续写入 `labels[].name`。
- 列表与详情使用 daisyUI `badge` 展示标签；列表可折叠为前 3 个 + `+N`，详情展示全部。
- 本迭代**不提供按 label 筛选**。
- `kind` 分流仍只按基石标签规则（`功能迭代` / `人工介入`）；标签与本地 `kind` 不一致时的 warning 保留。

**Type**

- `issue` 表增加可空列保存 GitHub Issue type 的名称；迁移可空、无回填。
- Webhook（含 `typed` / `untyped` 动作）、单条刷新、全仓手动同步都写入 type。
- 列表、详情**展示** type；type 仅展示，不映射、不覆盖 `kind`，不参与任何流程状态判断。
- 本迭代**不提供按 type 筛选**。
- 实现 PR 同步更新基石 `docs/architecture/design.md` 的 `issue` 表说明、Webhook 动作表、payload 字段白名单与页面说明。

## 3. 非目标

- 不在本系统创建 / 修改 GitHub 的 type 或 labels；全部只读同步。
- 不做公司级「全部 Issue」入口；手动同步只针对 `/repos/{id}/issues` 的单个仓库。
- 不按 type / labels 做筛选器、排序或统计。
- 不合并 PR、不跑 CI、不改写文档 / 生成代码主状态机、不改 `codegen_phase`。
- 不把手动同步做成替代 Webhook 的实时通道；Webhook 仍是主路径。
- 不在本迭代做全站其它页大改版；页脚和仓库输入溢出属于布局修复。
- 不重新设计 Issue 正文 Markdown 渲染、详情轮询、日志卡片或 PR 创建流程。
- 不改变 `kind` 的标签规则，不把 GitHub type 名称当作 `功能迭代` / `人工介入` 的替代。
- 不因为手动同步而清除已有 `design_doc_*`、SHA、`failed_action`、`last_error` 或 Job 历史。

## 4. 方案

### 4.1 现有实现与改动边界

| 位置 | 本迭代处理 |
| --- | --- |
| `app/templates/base.html` | `body` 改纵向 flex + `min-h-dvh`；`main` 加 `flex-1`；`footer` 保持文档流 |
| `app/templates/login.html` | 不套 `base.html`，保持独立整屏居中；只验证无页脚错位 |
| `app/templates/404.html` | 继承 `base.html`，随页脚修复生效 |
| `app/templates/repo.html` | 右栏卡片、`card-body`、`form`、`fieldset`、`input` 补 `min-w-0` / `max-w-full` |
| `app/templates/issues.html` | 页头增加同步 POST 表单；标题单元格展示 labels；新增 GitHub Type 列 |
| `app/templates/issue_detail.html` | 摘要区增加 GitHub Type 与 labels 展示 |
| `app/templates/macros/ui.html` | 新增 `github_type_badge` / `label_badges` 宏 |
| `app/templates/partials/app_scripts.html` | 提交态支持 `data-gw-busy-label`，用于「同步中…」文案 |
| `app/api/v1/issues.py` | 新增 `POST /repos/{repo_id}/issues/sync`；列表 / 详情上下文补齐展示字段 |
| `app/services/issue_sync.py`（新增） | 全仓分页对账、软删、PR 刷新与计数 |
| `app/services/ingest.py` | 解析 `issue.type`、`typed` / `untyped`；单条刷新写入 type |
| `app/services/github_api.py` | 增加列表 Issue 与读取单个 PR 的方法 |
| `app/crud/issue.py` | `upsert_from_webhook` 支持 `commit=False` 与 type；新增含软删行的仓库查询 |
| `app/services/pr_sync.py` | 抽出 PR 快照写入函数，复用手动同步 |
| `app/models/issue.py` + Alembic | 新增可空 `github_issue_type` |
| `deploy/nginx/api.kfc360.xyz.conf` | 为该同步路径放宽读超时，避免长请求被 504 截断 |
| `docs/architecture/design.md` | 实现 PR 同步数据模型、Webhook 白名单 / 动作与页面说明 |

不改 Worker、Inbox 循环、`job` 表、状态机箭头和入队前置条件。

### 4.2 页脚贴底

目标结构：

```html
<body class="flex min-h-dvh flex-col bg-base-200 text-base-content antialiased">
  <header class="sticky top-0 z-30 shrink-0 ...">...</header>

  <main id="main" class="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8">
    ...
  </main>

  <footer class="footer footer-center shrink-0 border-t border-base-300 bg-base-100 p-4 text-xs text-base-content/60">
    <p>GitHub 工作流 · 内部运维台</p>
  </footer>
</body>
```

约定：

- 只用 `min-h-dvh` + `flex flex-col` + `main.flex-1`，不加 `position: fixed` / `sticky` 到页脚，避免遮挡内容。
- `header` 继续 `sticky`；加 `shrink-0` 防止极端 flex 压缩。
- 内容少时 `main` 被拉伸，页脚落到视口底部；内容多时 `main` 按内容增长，页脚自然排在文档流末尾。
- 404 页继承同一壳，短内容也贴底。
- 登录页 `login.html` 是独立文档，`main` 已 `min-h-dvh` 居中且没有页脚；本迭代不改其结构，只确认窄高度下不产生半屏页脚或双滚动条。
- 不使用 `h-screen` / `overflow-hidden` 锁死页面；长表格、长日志仍由各自容器滚动。

验收时可静态断言：`base.html` 的 `body` 含 `flex`、`min-h-dvh`、`flex-col`，`main` 含 `flex-1`，`footer` 不含 `fixed`。

### 4.3 仓库本地配置输入防溢出

问题根因是栅格 / flex 子项的默认 `min-width: auto`，以及 `fieldset` 的 `min-inline-size: min-content`，不是 `input` 组件本身。修复方式：

```html
<div class="grid min-w-0 gap-6 lg:grid-cols-3">
  <section class="card card-border order-1 min-w-0 bg-base-100 shadow-sm lg:order-2 lg:col-span-1">
    <div class="card-body min-w-0 p-5">
      <h2 ...>本地配置</h2>
      <form method="post" action="/repos/{{ repo.id }}" class="w-full min-w-0 space-y-4">
        <fieldset class="fieldset w-full min-w-0">
          ...
          <input
            id="local_path"
            name="local_path"
            class="input w-full min-w-0 max-w-full font-mono text-sm ..."
            value="{{ local_path }}"
            title="{{ local_path }}"
            ...
          />
          ...
          <input
            id="doc_dir"
            name="doc_dir"
            class="input w-full min-w-0 max-w-full font-mono text-sm ..."
            value="{{ doc_dir }}"
            title="{{ doc_dir }}"
            ...
          />
        </fieldset>
      </form>
    </div>
  </section>
  ...
</div>
```

要点：

- 给网格直接子项 `section` 加 `min-w-0`，阻止长内容反向撑宽 `lg:col-span-1` 轨道。
- `card-body`、`form`、`fieldset` 逐层 `min-w-0` + `w-full`，尤其是 `fieldset` 要覆盖 UA 的 `min-inline-size`。
- 两个 `input` 使用 `w-full min-w-0 max-w-full`；不设固定 `min-w-[...]`，不在输入框内塞按钮。
- 长路径由输入框自身横向滚动查看；`title` 提供完整值提示。帮助文本里的 `<code>` 长串加 `break-all`，避免辅助文本再次撑宽卡片。
- 不使用 `overflow-hidden` 裁掉焦点环；优先用布局约束，而不是靠裁切掩盖问题。
- 桌面窄右栏、`lg` 单列切换、375px 小屏三种宽度都要检查卡片 `scrollWidth <= clientWidth`。

### 4.4 手动全量对账

#### 4.4.1 入口与路由

按钮放在 `/repos/{id}/issues` 页头的 `page_header` 操作区，与结果条数并列：

```html
<form method="post" action="/repos/{{ repo.id }}/issues/sync" class="inline-flex" data-gw-sync-form>
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
  <input type="hidden" name="next" value="{{ request.url.path }}{% if request.url.query %}?{{ request.url.query }}{% endif %}" />
  <button type="submit" class="btn btn-sm btn-outline gap-1.5"
          data-gw-submit data-gw-busy-label="同步中…"
          aria-label="从 GitHub 全量更新本仓库 Issue 状态">
    {{ icon('refresh') }}<span>手动更新 Issues 状态</span>
  </button>
</form>
```

- 新路由：`POST /repos/{repo_id}/issues/sync`，使用现有 `require_csrf`，同时完成登录校验。
- `next` 用于保留当前筛选（`kind` / `status` / `pr_state` / `github_state` / `page`）。服务端只接受以 `/repos/{repo_id}/issues` 开头的值，并去掉旧的 `flash` / `msg`，防止开放重定向和重复提示。
- 成功 / 失败都用 303 回列表，带 `flash` 与 `msg`；不使用有副作用的 GET。
- 按钮提交后由 `data-gw-submit` 禁用并加 spinner；若按钮带 `data-gw-busy-label`，同一段脚本把可见文案改为「同步中…」。服务端再加仓库级互斥，防止多标签页重复提交。
- 本迭代不加二次确认弹窗：这是只读拉取 + 幂等写回，不是入队或 PR 操作；软删除只针对 GitHub 已不存在的行，与基石删除语义一致。

#### 4.4.2 分页读取

新增 `GitHubClient.list_repository_issues(owner, repo, *, state="all", page=1, per_page=100, sort="created", direction="asc")`，调用：

```text
GET /repos/{owner}/{repo}/issues
  ?state=all&per_page=100&sort=created&direction=asc&page={page}
```

规则：

- 一次使用 `state=all` 覆盖 open 与 closed，不分别请求两遍。
- `per_page=100`，从 `page=1` 递增；某页返回数量小于 100 时停止。若返回空数组也停止。
- `sort=created&direction=asc` 让已存在页的顺序稳定，减少同步期间新建 Issue 造成的翻页漂移。
- GitHub 的 Issues 端点会同时返回 Pull Request。凡响应项含 `pull_request` 键，一律**不写入 Issue 表**；但其 `number` 记入「已见编号」，避免本地同号行被误判为远端已删除。
- 每一项必须能解析出整数 `id` 与 `number`；缺字段、类型异常时记为失败项并跳过该条，不中断整页。
- 响应必须是数组；否则按失败处理。
- 全部页读取完成后才进入写阶段。任何一页出现网络异常、401/403、429、5xx、超时，都直接中止，**不写任何业务数据**。

#### 4.4.3 写回与字段语义

写阶段加载该仓库全部本地 Issue（包含 `deleted_at` 非空的行），按 `number` 建索引，然后在一个事务中处理：

| 远端 / 本地情况 | 行为 |
| --- | --- |
| 远端存在，本地不存在 | 按 `opened` 语义新建：标题、正文、链接、作者、`github_state`、`label_names`、type、`github_updated_at`、`github_state_updated_at`；`kind` / `status` 按标签规则初始化 |
| 远端存在，本地存在 | 按 `edited` 语义覆盖元数据；`kind` / `status` 仅在本地仍处于 `pending_classify` / `recorded` / `support_open` 且未锁定时按标签重算，其他状态保持本地流程状态 |
| 远端存在，本地已软删 | 不复活、不改任何字段；计入「跳过已软删」 |
| 本地同号但 `github_issue_id` 与远端不一致 | 不覆盖、不软删，记为失败项，等待人工处理 |
| 远端不存在，本地存在且未软删 | 只写 `deleted_at = 本次同步开始时间`；不改 `status`、`kind`、`github_state`、PR 字段、Job |
| 远端不存在，本地已软删 | 忽略 |

字段来源与单条刷新保持一致：

| 字段 | 来源 |
| --- | --- |
| `github_issue_id`、`number` | `issue.id`、`issue.number`，先做身份一致性校验 |
| `title`、`body`、`html_url` | 远端覆盖；`body` 为 null 时存空串 |
| `author_login` | `issue.user.login` |
| `github_state` | `issue.state`（open / closed） |
| `github_updated_at` | `issue.updated_at` |
| `github_state_updated_at` | 同一远端时间；仅在状态事件写入时按现有守卫更新 |
| `label_names` | `issue.labels[].name`；兼容字符串项，去空、去重、保留首次顺序 |
| `github_issue_type` | `issue.type.name`；type 为 null 时写 null |
| `deleted_at` | 只在远端缺失时填当前时间 |
| `design_doc_*`、`iteration_no`、`branch_name`、SHA、`codegen_phase`、`failed_action`、`last_error` | 不动 |
| `pr_number`、`pr_url`、`pr_state`、`pr_merged_at`、`pr_state_updated_at` | 只由 PR 刷新步骤更新，Issue 元数据写入不碰 |

其他规则：

- 沿用 `upsert_from_webhook` 的时间戳守卫：远端 `updated_at` 不早于本地 `github_updated_at` 时才覆盖，避免手动同步与刚到达的 Webhook 乱序回退。若远端快照更旧，接口仍成功，但该条可能不变化。
- 若某条 Issue 从非 closed 变为 closed，在同一事务内调用现有 `job_crud.cancel_queued_for_issue`，与 Webhook `closed` 行为一致；running Job 不杀，Worker 会按现有规则自行完成。手动同步自身不新建、不取消其他 Job。
- 软删除不取消 queued Job：这与 Webhook `deleted` 的现有语义一致，Worker 领取时会重新校验。
- 不对公司 / 仓库元数据做同步；仓库改名或无权限时请先用仓库页的「重新同步」处理 `full_name`，再回来同步 Issue。
- 所有写操作只提交一次；数据库异常整体回滚。

#### 4.4.4 软删除的安全条件

只有同时满足以下条件才填 `deleted_at`：

1. 分页已完整读完，没有中止；
2. 本地行 `deleted_at IS NULL`；
3. 本地行的 `number` 不在本次「已见编号」集合（包含被跳过的 PR 编号）；
4. 本地行 `github_updated_at` 为空，或不晚于本次同步开始时间。

第 4 条用于避免把同步期间由 Webhook 新建 / 更新的 Issue 误删：本次快照没有它，不代表远端真的没有。若其 `github_updated_at` 晚于同步开始时间，跳过软删并在摘要中体现。

#### 4.4.5 刷新已有 PR 状态

写阶段收集本地 `pr_number` 非空、且未被软删的 Issue；按 PR 编号去重后逐条调用：

```text
GET /repos/{owner}/{repo}/pulls/{pr_number}
```

新增 `GitHubClient.get_pull_request(owner, repo, number)`。写入复用 `pr_sync.py` 的规则：

| PR 快照 | `pr_state` |
| --- | --- |
| `state = open` 且未合并 | `open` |
| `merged = true` 或 `merged_at` 非空 | `merged`，同时保存 `pr_merged_at` |
| `state = closed` 且未合并 | `closed` |
| 其它 / 字段缺失 | 保守保持现有状态，或按现有 `initial_state` 规则处理 |

- 校验返回的 `number` 与本地 `pr_number` 一致；不一致记为失败，不写。
- 成功时更新 `pr_url`（若响应有 `html_url`）、`pr_state_updated_at`（取自 PR `updated_at`），并沿用 `pr_state_updated_at` 的时间戳守卫，旧快照不覆盖新状态。
- 404 / 410：PR 已删除或无权访问；保留原状态，记失败原因，不中断其它 Issue。
- 429：停止剩余 PR 刷新，避免继续打 GitHub；已读取的 Issue 元数据仍提交，摘要注明「PR 刷新被限流中止」。
- 401 / 403：停止 PR 刷新，记失败原因；Issue 元数据仍提交。
- PR 刷新失败不影响 Issue 元数据写入，也不改变 Job 状态。

#### 4.4.6 并发、限流与超时

- **仓库级互斥**：路由在读取仓库后，对 `hashtext('github_workflow:issue-sync:{repo_id}')` 尝试 `pg_try_advisory_xact_lock`。拿不到锁时 303 回列表并 flash「该仓库正在同步，请稍后再试」，不读取 GitHub、不写库。锁随事务结束自动释放，可跨 Web 进程生效。
- **整体时间预算**：模块常量默认 180 秒，覆盖分页读取与 PR 刷新。超时中止；若在 Issue 分页阶段，则不写任何数据；若已进入 PR 阶段，则提交已完成的 Issue 写回，并把未完成的 PR 记为失败 / 跳过。
- **单请求超时**：沿用 `GitHubClient` 的 30 秒 connect/read timeout，不在请求内无限重试。
- **限流**：429 直接中止当前阶段并提示；不在 Web 请求内 sleep 等待 `Retry-After`，避免占用连接和浏览器请求。
- **Nginx**：在 `deploy/nginx/api.kfc360.xyz.conf` 为该同步路径（或统一代理位置）设置 `proxy_read_timeout 300s`，保证应用侧 180 秒预算先于反向代理生效；否则长仓库会被 504 截断。
- **进度反馈**：v1 只有提交中的 spinner +「同步中…」文案 + 禁用重复提交；不引入 SSE / WebSocket / 轮询进度条。若仓库规模超过时间预算，需要改为后台任务，见「待确认」。

#### 4.4.7 结果摘要与错误文案

成功时 303 回列表，`flash=ok`，摘要示例：

```text
同步完成：检查 120 条（open 98 / closed 22），新增 2 条，更新 9 条，软删 1 条，PR 刷新 4 条。
```

有失败项时使用 `flash=error`，但仍保留已成功的计数：

```text
同步完成，但有 2 项失败：PR #42 已不存在；PR 刷新因限流中止。检查 120 条，新增 2 条，更新 9 条，软删 1 条。
```

错误映射：

| 情况 | 文案方向 |
| --- | --- |
| 仓库不存在 | 404 页面 |
| `github_full_name` 无效 | 同步失败：仓库完整名无效，请先重新同步仓库 |
| 401 / 403 | 同步失败：GitHub 授权失败，请检查访问令牌 |
| 404 / 410 | 同步失败：GitHub 上找不到该仓库，可能已改名或无权限；请先重新同步仓库 |
| 429 | 同步失败：GitHub 限流，请稍后重试；未写入任何变更 |
| 超时 | 同步失败：超过 180 秒未完成，已中止；未写入任何变更 |
| 网络异常 / 5xx | 同步失败：无法连接 GitHub，未写入任何变更 |
| 数据库异常 | 同步失败：写入数据库失败，已回滚 |
| 仓库正在同步 | 该仓库正在同步，请稍后再试 |

不在 flash 或日志中输出 Token、请求头或完整响应体。

### 4.5 GitHub Issue type

#### 4.5.1 数据模型

`issue` 表增加一个可空列：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `github_issue_type` | `String(128)`，可空 | GitHub Issue type 的 `name`。无 type 时为 `NULL` |

本期只存名称，不存 type id、颜色、描述：

- 页面只展示名称，不按 type 筛选、不映射 `kind`、不写回 GitHub。
- type 改名时由下一次 Webhook / 手动同步覆盖名称即可。
- 若以后要按 type 做稳定关联或筛选，再另开迁移增加 id 与索引；不预埋无用途列。

迁移：新增 `app/alembic/versions/20261112_0004_issue_github_issue_type.py`，`upgrade` 只 `add_column`，`downgrade` 只 `drop_column`；无回填、无索引、无数据转换。已有行在首次同步前显示「—」。

#### 4.5.2 解析与写入

在 `app/services/ingest.py` 增加防御性解析：

```python
def _issue_type_name(value):
    if isinstance(value, dict):
        return _text(value.get("name"))
    if isinstance(value, str):
        return _text(value)
    return None
```

- REST 的 Issue 响应中 `type` 是对象（含 `id`、`name`、`description`、`color` 等），只取 `name`。
- Webhook payload 中的 `issue.type` 以实际投递为准；若为对象取 `name`，若为字符串直接使用。
- 用「字段是否存在」区分「无 type」与「payload 没带该字段」：
  - key 存在且值为 null：写入 `NULL`（对应 `untyped`）。
  - key 存在且有名称：写入名称。
  - key 不存在：保留本地原值，避免旧版 payload 把已有 type 误清空；手动全量同步和单条刷新会补齐。
- `upsert_from_webhook` 增加 `github_issue_type` 与 `github_issue_type_set` 参数；只在内容动作且 set 为真时写入。新建行始终按传入值初始化。
- `refresh_issue_from_github` 传 `github_issue_type_set=("type" in payload)`，与 Webhook 共用同一映射。

#### 4.5.3 Webhook 动作

GitHub `issues` 事件包含 `typed` / `untyped` 动作。当前 `SUPPORTED_ISSUE_ACTIONS` 未包含它们，type 变化会被当成不支持动作。本迭代：

- 在 `SUPPORTED_ISSUE_ACTIONS` 加入 `typed`、`untyped`。
- 在 `CONTENT_ACTIONS` 与 `STATE_ACTIONS` 加入 `typed`、`untyped`，让完整 Issue payload 的标题、正文、标签、状态与 type 一起刷新。
- 不在 `deleted` 分支写 type；软删除行保持隐藏。
- `typed` / `untyped` 同样只按标签重算早期 `kind` / `status`，type 本身不参与分类。
- 基石动作表补充这两行，payload 白名单加入 `issue.type.name`。

#### 4.5.4 展示

- 列表新增「GitHub Type」列，使用 `badge badge-sm badge-outline`；无 type 显示 `—`。
- 详情摘要区增加「GitHub Type」项；无 type 显示 `—`。
- 不提供任何 `select` / 筛选参数 / URL 查询参数用于 type。
- type 的名称按原样展示，不做大小写归一化，不映射成本地中文类型。

### 4.6 labels 展示

- 列表标题单元格内、作者下方展示标签：前 3 个 `badge badge-xs badge-ghost`，超出显示 `+N`，`+N` 的 `title` 放完整标签列表。
- 详情摘要区增加横跨整行的「标签」项，展示全部标签；无标签显示 `—`。
- 单个标签过长时用 `max-w-[14rem] truncate` + `title`，不撑破单元格。
- 标签只展示，不改变 `kind` / `status`，不新增筛选控件。
- 保留现有「GitHub 标签与本地类型不一致」warning；判断逻辑不变。
- 不改 `label_names` 的存储类型和排序语义；解析时去空、去重，避免重复 badge。

### 4.7 与 daisyUI / 无障碍约定的关系

- 页脚、卡片、输入、按钮、badge 全部沿用现有 daisyUI 组件；布局补齐只用 Tailwind 工具类。
- 同步按钮有可见文案与 `aria-label`；提交中 `aria-busy` 由现有脚本设置。
- 页脚不是可交互区域，不抢焦点；不使用 `fixed`，不产生遮挡。
- 输入框继续有可见 `<label>`；错误文本仍放在字段下方。
- 标签 / type badge 同时用文字表达，不只靠颜色；不引入 GitHub 任意色值的内联样式。
- 列表表格继续放在 `overflow-x-auto` 内，新增列后小屏可横向滚动。

### 4.8 测试

#### 页脚与布局

`tests/test_ui.py` 增加静态断言：

- `base.html` 的 `body` 含 `min-h-dvh`、`flex`、`flex-col`；`main` 含 `flex-1`；`footer` 不含 `fixed`。
- `repo.html` 的两处输入含 `min-w-0` 与 `max-w-full`；右栏 `section` / `card-body` / `fieldset` 含 `min-w-0`。
- 404 页仍渲染 `<footer`。

#### Webhook type 与 labels

更新 `tests/test_sync.py`：

1. `issue.type = {"id": 1, "name": "Bug"}` 时写入 `github_issue_type`。
2. `typed` / `untyped` 动作被接受；`untyped` 把列写为 `NULL`。
3. payload 缺少 `type` 键时保留已有 type，不清空。
4. type 变化不改变 `kind` / `status`（除既有早期标签重算外）。
5. labels 含字符串项、对象项、空串、重复项时，`label_names` 去空去重且顺序稳定。

#### 全仓手动同步

新增 `tests/test_issue_sync.py`，用 fake `GitHubClient` 或 `httpx.MockTransport` 覆盖：

1. 两页 `state=all` 数据（含 open、closed、PR 项）能完整读取；PR 项不写入 Issue，但计入已见编号。
2. 远端缺失的本地行只写 `deleted_at`，`status` / `kind` / `github_state` 不变；默认列表不再显示。
3. 第一页成功、第二页 429 / 超时：不写任何业务数据，不软删。
4. 远端存在、本地缺失：新建并正确分类；已有行更新标题、正文、链接、作者、`github_state`、labels、type。
5. 本地已软删的行即使远端仍存在也不复活。
6. 本地锁定状态（如 `pending_codegen`）不被标签重算改回。
7. 远端变为 closed 时取消 queued Job，running Job 不变；手动同步自身不新建 Job。
8. 有 `pr_number` 时刷新为 open / merged / closed；`pr_merged_at`、`pr_url` 更新；旧快照不覆盖新状态。
9. PR 404 记失败但不阻断 Issue 写回；PR 429 停止剩余 PR 请求并记失败。
10. 仓库级互斥：锁被占用时返回 flash 错误，不调用 GitHub。
11. 缺 CSRF：403；未登录：跳登录；`GET /repos/{id}/issues/sync`：405。
12. 成功 / 部分失败都 303 回原筛选 URL，摘要含新增 / 更新 / 软删 / PR / 失败计数。

#### 单条刷新与展示

- `tests/test_issue_refresh.py` 增加：单条刷新写入 / 清空 type；labels 同步。
- `tests/test_ui.py` 增加：
  - Issue 列表存在 `action="/repos/{id}/issues/sync"`、`method="post"`、CSRF 隐藏字段、「手动更新 Issues 状态」文案。
  - 列表存在 GitHub Type 列与标签 badge；详情存在 GitHub Type 与标签。
  - 列表与详情都不存在按 type / label 筛选的 `select` 或 URL 参数控件。
  - 无 type / 无标签时显示 `—`，不出现空 badge。
  - 同步按钮提交后禁用（依赖现有 `data-gw-submit` 测试或静态断言）。

#### 检查命令

```bash
uv run alembic upgrade head
uv run pytest -q
```

人工检查：

- 1440px / 1024px / 375px 下空列表、设置页、404 页脚贴底；长页面页脚在内容末尾。
- `/repos/{id}` 右栏与小屏输入框不溢出，长路径可用内部滚动查看。
- 手动同步一个含 open / closed / PR 的测试仓库，核对抽样 Issue 与 GitHub 一致；核对软删行默认不可见。
- 同步期间重复点击 / 多标签页提交，只执行一次；结束后摘要可读。
- type 与 labels 在列表、详情显示，且没有新增筛选控件。

### 4.9 风险与回滚

| 风险 | 说明 | 处理 |
| --- | --- | --- |
| 分页期间远端变化 | 新建 / 更新导致偏移，或本地新行被误删 | `sort=created&direction=asc`；完整读取后才写；软删增加「不晚于同步开始时间」守卫 |
| 不完整集合导致误软删 | 某页失败但仍进入写阶段 | 任一分页失败立即中止，不写业务数据 |
| 与 Webhook 乱序 | 手动快照旧于已处理的 Webhook | 沿用 `upsert_from_webhook` 与 `pr_sync` 的时间戳守卫 |
| 长仓库请求超时 | 同步超过 Nginx / 浏览器等待 | 应用 180 秒预算；Nginx 300 秒；超时不写或只提交已完成阶段；大规模改后台任务列入待确认 |
| GitHub 限流 | 分页或 PR 刷新 429 | 中止并提示；不在请求内长时间 sleep |
| 重复提交 | 多标签页或双击 | 按钮禁用 + PostgreSQL advisory lock |
| type 被误当成本地类型 | 展示或规则混用 | 字段独立命名 `github_issue_type`；不读写 `kind`；不在筛选器出现 |
| Webhook 不提供 type | 旧 payload / 文档差异 | 字段不存在时保留原值；手动同步与单条刷新补齐；列入待确认 |
| 回滚 | 迁移、服务、路由、模板一起变更 | 回滚整个 PR；迁移 `downgrade` 删除列；软删数据需按备份恢复，不自动复活 |

## 5. 影响面

| 区域 | 影响 |
| --- | --- |
| `app/models/issue.py` | 新增 `github_issue_type` 可空列 |
| `app/alembic/versions/` | 新增 `0004_issue_github_issue_type` 迁移 |
| `app/crud/issue.py` | `upsert_from_webhook` 支持 type 与 `commit=False`；新增含软删行的仓库查询 |
| `app/services/ingest.py` | 解析 labels / type；支持 `typed` / `untyped`；单条刷新写 type |
| `app/services/issue_sync.py`（新增） | 全仓分页对账、软删、PR 刷新、计数与错误汇总 |
| `app/services/github_api.py` | 新增 `list_repository_issues`、`get_pull_request` |
| `app/services/pr_sync.py` | 新增 PR 快照写入函数，复用手动同步 |
| `app/api/v1/issues.py` | 新增 `POST /repos/{repo_id}/issues/sync`；列表 / 详情上下文补字段 |
| `app/templates/base.html` | 纵向 flex + `main.flex-1`，页脚贴底 |
| `app/templates/repo.html` | 本地配置卡片与输入补 `min-w-0` / `max-w-full` |
| `app/templates/issues.html` | 同步按钮、GitHub Type 列、标签 badge |
| `app/templates/issue_detail.html` | GitHub Type 与标签展示 |
| `app/templates/macros/ui.html` | type / label badge 宏 |
| `app/templates/partials/app_scripts.html` | 提交态支持 `data-gw-busy-label` |
| `deploy/nginx/api.kfc360.xyz.conf` | 同步路由放宽 `proxy_read_timeout` |
| `tests/test_sync.py`、`tests/test_issue_refresh.py`、`tests/test_ui.py`、`tests/test_issue_sync.py` | 覆盖 type / labels / 同步 / 布局 |
| `docs/architecture/design.md` | 实现 PR 更新 `issue` 表、Webhook 动作与白名单、页面说明 |
| 数据库 | 一个新可空列；无回填、无索引 |
| Worker / Inbox / Job / 状态机 | 不改；手动同步只做 Web 侧只读拉取与批量写回 |
| 部署 / 环境变量 | 无新环境变量；Nginx 读超时调整 |

## 6. 验收

- [ ] 短页（空列表、设置、404）footer 贴视口底部；长页 footer 在内容之后，不遮挡主操作。
- [ ] 页脚未使用 `position: fixed`；`base.html` 使用 `min-h-dvh` + 纵向 flex + `main.flex-1`。
- [ ] `/repos/{id}` 的「服务器项目路径」「文档目录」输入在桌面右栏与 375px 小屏均不溢出卡片。
- [ ] `/repos/{id}/issues` 页头有「手动更新 Issues 状态」；点击后对该仓库 open + closed 全量分页对账并写回。
- [ ] 同步后 `github_state`、标题、正文、链接、作者、`github_updated_at`、labels、type 与 GitHub 抽样一致。
- [ ] 已有 `pr_number` 的 Issue 的 `pr_state` 已刷新；merged / closed 未合并 / open 映射正确。
- [ ] GitHub 上已删除的 Issue，本地仅 `deleted_at` 有值，`status` / `kind` / `github_state` 不变，默认列表不可见。
- [ ] 任意一页读取失败时不写入业务数据，不执行软删除。
- [ ] type、labels 在列表与详情可见；列表标签折叠为前 3 个 + `+N`，详情展示全部；无 type / label 筛选控件。
- [ ] type 不改变 `kind`；`typed` / `untyped` 与手动同步、单条刷新行为一致、可重复执行。
- [ ] 手动同步走 POST + CSRF；提交中禁用并显示 loading；结束 flash 摘要包含新增 / 更新 / 软删 / PR / 失败原因。
- [ ] 仓库级互斥生效，多标签页重复提交不会并发写库。
- [ ] daisyUI 组件优先；`uv run pytest -q` 通过；`uv run alembic upgrade head` 成功。
- [ ] 实现 PR 更新 `docs/architecture/design.md` 的 `issue` 表、Webhook 动作 / payload 白名单、Issue 列表与详情页面说明、页脚与反馈约定。
- [ ] 实现走 `dev_14` 并开 PR。

## 7. 待确认

以下规则 Issue 未给出唯一结论，本文按默认方案推进；最终以评审或实现 PR 确认为准。

1. **Webhook 中 type 的实际字段形态**：官方 REST 文档的 Issue 对象含 `type` 对象（`id` / `name` / `description` / `color` 等），但 Issues Webhook 的 payload 说明未在示例中明确列出该字段。本文按「`issue.type` 对象取 `name`，字符串也可接受，字段缺失则保留原值」实现；开工前用一次真实 `typed` / `untyped` 投递核对。若 Webhook 不带 type，是否需要额外调用 GitHub API 补齐，需评审决定。
2. **对账是否补建本地缺失的远端 Issue**：本文默认补建（否则 Webhook 丢失期间的 `opened` 永远补不回来）。若评审只希望更新 / 软删已有行，需要明确改为忽略远端缺失于本地的条目。
3. **本地已软删、远端仍存在的行**：本文默认不复活。若要支持「GitHub 重新出现后恢复」，需要定义 `deleted_at` 的撤销规则，并确认是否影响 `status` / Job。
4. **大仓库的超时与异步化**：本文默认同步请求内完成，应用预算 180 秒、Nginx 300 秒；不提供逐页进度条。若目标仓库 Issue 量导致经常超时，需要改为后台 Job / 独立同步记录，并提供轮询进度；这会引入新的任务类型和页面状态，超出本迭代默认范围。
5. **GitHub 次级限流**：当前 `GitHubClient` 把 403 统一视为授权失败。GitHub 的 secondary rate limit 可能返回 403 + `Retry-After`，是否需要与真正的权限 403 区分，并在手动同步中单独提示，需确认；本文只保证 429 的明确处理。
6. **type 是否只存名称**：本文不存 type id / 颜色 / 描述，理由是本期只展示、不筛选、不映射。若以后要按 type 做稳定关联或统计，需要另开迁移加 id 与索引。
7. **手动同步是否要二次确认**：本文不加 modal，只做提交中禁用与仓库级互斥。若评审认为软删除风险需要显式确认，可复用现有 `data-gw-confirm-form`，但会增加一次点击。
8. **PR 刷新策略**：本文只对本地已有 `pr_number` 的 Issue 逐条拉取 PR，避免全量 PR 列表。若仓库 PR 数量远大于本地关联数，或需要发现「本地未记录但已存在的 PR」，需要改成 PR 列表分页对账；这属于新的数据补全范围。
9. **同步是否更新仓库统计**：本文不更新 `repository.open_issues_count` 等 GitHub 元数据，仓库资料仍由「重新同步」负责。若希望一次操作同时刷新仓库统计，需要明确两项操作的边界与失败处理。
