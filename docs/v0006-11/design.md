# Issue 详情：主栏 6:4、设计文档 Markdown 渲染、页头刷新（v0006 / Issue #11）

- 迭代：`v0006`，对应 GitHub Issue `#11`
- 文档路径：`docs/v0006-11/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：Issue 详情页的 **版面 + 渲染 + 只读同步入口** 增量。不改文档 / 代码生成状态机，不改 Webhook Inbox，不改 Job 入队条件。

## 1. 背景

`/issues/{id}` 当前有三个具体问题：

1. **主栏比例偏窄**：桌面 `xl` 下使用 `grid-cols-3`，左栏 `col-span-2`、右栏 `col-span-1`，实际约 2:1。Issue 正文和设计文档较长时，左栏阅读宽度尚可，但右侧「任务与 Worker / 最新任务日志」被压到约三分之一，日志和任务信息过早换行。
2. **设计文档不可读**：设计文档卡片仍把 `design_doc_text` 直接放进 `<pre>`，标题、列表、代码块、引用和表格都只能看源文。基石当前对设计文档也明确写着「Markdown 源文用等宽 `<pre>` 展示，本期不做 GFM 渲染」，本迭代要求改变这个结论。
3. **缺少立即对齐 GitHub 的入口**：页头操作区只有「在 GitHub 打开」。操作员在 GitHub 改了标题、正文、标签或开闭状态后，只能等 Webhook，或手动刷新整页再看本地是否已同步。

补充基线现状：

- Issue 正文已经由 `app/services/markdown_render.py` 在服务端用 `Python-Markdown + nh3` 渲染并消毒，模板使用 `issue_body_html`，不是裸 `|safe`。
- 设计文档仍是 `design_doc_text` 源文的 `<pre>`。
- 详情页右栏已包含「任务与 Worker」和「最新任务日志」两张卡，并由 `data-gw-region="issue-side"` 标识。

因此本迭代的重点是：**确认 6:4 版面、把设计文档接入同一套安全 Markdown 管线、增加一个 POST + CSRF 的刷新按钮**。Issue 正文渲染不在本迭代重复实现。

## 2. 目标

### 2.1 主栏宽度改为 6:4

桌面断点使用现有 `xl`（Tailwind 默认 1280px），主内容双栏为 6:4：

| 左栏（约 6） | 右栏（约 4） |
| --- | --- |
| Issue 正文卡片 | 任务与 Worker |
| 设计文档卡片（若有） | 最新任务日志 |

要求：

- 使用 10 列栅格：`xl:grid-cols-10` + 左栏 `xl:col-span-6` + 右栏 `xl:col-span-4`，不再保留 `xl:grid-cols-3` 的 2:1 写法。
- 小于 `xl` 时保持单列，DOM 顺序为：Issue 正文 → 设计文档（若有）→ 任务与 Worker → 最新任务日志。这样小屏不会横向挤压正文，任务卡仍在正文之后。
- 页顶告警、流程操作卡、摘要条的位置和内容保持不变。
- 轮询使用的 DOM id 与结构不变：`#issue-live-status`、`#issue-log`、`#issue-log-live`、`#issue-log-jump`、`#issue-log-updated`、`data-done`、`data-gw-region="issue-side"`。
- 最新任务日志本迭代**留在右栏**，不改为全宽底栏；右栏从 1/3 变为 2/5 后，日志可用宽度已增加。此项仍列入「待确认」。

### 2.2 设计文档支持 Markdown

- 将 `design_doc_text` 从纯 `<pre>` 源文改为**服务端 Markdown → HTML，经 HTML 白名单消毒后输出**。
- 不允许把未消毒内容标记为 `Markup`，模板中不得新增裸 `|safe`。
- 至少覆盖：标题、段落、列表、链接、行内代码、围栏代码块、引用、表格。
- 链接只允许 `http` / `https`，外链带 `rel="noopener noreferrer"`；相对链接、`javascript:`、`data:` 等不保留 `href`。
- 原始 HTML、`script`、`style`、`iframe`、`svg`、`form`、事件属性、`style` 属性、`id` / `class` 属性均被消毒掉。
- 长文档保持可滚动，沿用约 `max-h-[32rem]` 量级；代码块内部横向滚动，表格内部横向滚动，不撑破卡片。
- 卡片头继续展示 `design_doc_path` 和迭代号；可读性优先于「源码感」。
- 无设计文档时不出现空卡片。

### 2.3 「在 GitHub 打开」右侧增加刷新按钮

- 位置：页头 `page_header` 操作区，紧挨「在 GitHub 打开」右侧。
- 样式：`btn btn-sm`；外链继续 `btn-outline`，刷新使用 `btn-ghost` 以区分主次；图标使用现有 `refresh`，文案「刷新」，并提供明确的 `aria-label`。
- 行为固定为：**从 GitHub 拉取并更新本 Issue 的元数据**（标题、正文、标签、`github_state`、链接、作者、GitHub 更新时间等），成功后 303 回本详情页并 flash 提示；失败停留本页并显示错误。
- 刷新只同步元数据，不写文档、不生成代码、不入队、不取消任务。
- 有排队中 / 执行中的任务时仍允许刷新；若将来要禁用，必须另写理由，本迭代不禁用。
- 实现走 `POST /issues/{issue_id}/refresh` + CSRF，不使用有副作用的 GET。

### 2.4 文档与测试

- 本迭代设计写入本文件。
- 实现 PR 更新 `docs/architecture/design.md` 的 Issue 详情与界面契约表述：设计文档改为安全 Markdown 渲染，页头增加刷新入口。
- UI / Markdown / 刷新相关 pytest 同步更新并通过。

## 3. 非目标

- 不改写文档 / 生成代码的状态机、`codegen_phase`、入队条件和失败重试语义。
- 不改 Webhook Inbox、验签、投递重试或 GitHub Webhook 事件处理。
- 不在本迭代做 PR 状态同步、全站 daisyUI 5 升级；若并行 Issue 已完成组件化，本页只跟随既有 `card` / `btn` / `badge` 约定。
- 不把设计文档改成可编辑；仍为只读渲染。
- 不新增评论、指派、标签写回等 GitHub 写操作；刷新只读同步本 Issue。
- 不因刷新而软删除本地 Issue，也不新增数据库迁移。
- 不改变分页、筛选、列表页和其它页面。
- 不把 Issue 正文改成新的渲染器；它已经使用同一套安全 Markdown 管线。

## 4. 方案

### 4.1 现有实现与改动边界

相关代码：

| 位置 | 现状 | 本迭代处理 |
| --- | --- | --- |
| `app/templates/issue_detail.html` | `xl:grid-cols-3`；设计文档 `<pre>`；页头只有外链 | 改 10 列栅格、Markdown 容器、刷新表单 |
| `app/api/v1/issues.py` | GET 详情；状态片段；分类 / 入队 POST | 详情上下文增加设计文档 HTML；新增刷新 POST |
| `app/services/markdown_render.py` | Issue 正文的 Markdown + nh3 管线 | 抽出可复用渲染函数，新增设计文档入口 |
| `app/services/github_api.py` | 有仓库 / 组织 / 用户 / PR 方法 | 增加 `get_issue` |
| `app/services/ingest.py` | Webhook 同步与仓库 resync 共用 | 增加刷新 Issue 的服务函数，复用现有 upsert |
| `app/templates/partials/head_assets.html` | 已有 `.md-content` 排版 | 原则上不改；若设计文档需要独立滚动容器，只加布局工具类 |

不新增数据库字段，不需要 Alembic 迁移。

### 4.2 6:4 栅格

目标结构：

```html
<div class="grid gap-4 xl:grid-cols-10 xl:items-start">
  <div class="min-w-0 space-y-4 xl:col-span-6">
    <!-- Issue 正文卡 -->
    <!-- 设计文档卡（若有） -->
  </div>

  <div class="min-w-0 space-y-4 xl:col-span-4" data-gw-region="issue-side">
    <!-- 任务与 Worker -->
    <!-- 最新任务日志 -->
  </div>
</div>
```

约定：

- `xl:grid-cols-10` 的 6 / 4 轨道宽度比例就是 6:4。不要用 `grid-cols-3` + `col-span-2` 模拟。
- 保留 `min-w-0`，防止长链接、长代码行和 `pre` 撑破栅格。
- 保留 `space-y-4` 和 `gap-4`，不改变卡片间距。
- 小屏不设置列跨度，自然按 DOM 顺序单列堆叠：左栏两张卡在前，右栏两张卡在后。
- 页顶的 `foundation_missing` / `stale_doc` / `label_mismatch` / `last_error` 告警、流程操作卡和摘要条仍在栅格之外，位置不变。
- 不调整右栏内部顺序：任务与 Worker 在前，最新任务日志在后。

实现后静态测试应能确认：模板含 `xl:grid-cols-10`、`xl:col-span-6`、`xl:col-span-4`，且不再含 `xl:grid-cols-3` 和 `xl:col-span-2`。

### 4.3 设计文档 Markdown 渲染

#### 4.3.1 选型默认值

**默认复用现有管线：Python-Markdown（`markdown`）+ nh3 消毒。** 理由：

1. 仓库已经依赖 `markdown` 和 `nh3`，Issue 正文已经验证过这套组合。
2. 不引入新的前端 Markdown 库、Node 依赖或运行时脚本，也不把渲染放到浏览器。
3. 服务端渲染便于统一做白名单消毒、链接协议限制和测试。

最终库选型与白名单仍列入「待确认」；若评审选择其它库，也必须满足同样的服务端消毒与标签白名单要求。

#### 4.3.2 渲染函数

在 `app/services/markdown_render.py` 中保留 `render_issue_body` 的行为不变，并新增：

```python
def render_design_doc(raw: str | None) -> Markup | None:
    ...
```

实现方式：

- 抽出公共的 Markdown 转换 + `nh3.clean` + `_make_pre_focusable` 步骤，Issue 正文和设计文档共用，避免两套白名单漂移。
- 设计文档使用独立的标题映射，保留层级：
  - `h1` → `h3`
  - `h2` → `h4`
  - `h3` → `h5`
  - `h4` / `h5` / `h6` → `h6`
- 这样卡片标题本身是 `h2`，文档标题从 `h3` 开始，章节仍保持相对层级，不会把 `#` 和 `##` 压成同一级。
- Issue 正文继续保留现有标题映射，以免改变已有页面和测试。
- 输入为空或只有空白时返回 `None`。
- 渲染或消毒异常时返回 `None`，由模板回退到自动转义的 `<pre>` 源文；**异常路径绝不能返回未消毒的 `Markup`**。

#### 4.3.3 扩展与白名单

沿用现有扩展：`fenced_code`、`tables`、`sane_lists`。

沿用现有允许标签：

`p`、`br`、`h3`–`h6`、`blockquote`、`pre`、`ul`、`ol`、`li`、`hr`、`table`、`thead`、`tbody`、`tr`、`th`、`td`、`a`、`strong`、`em`、`code`。

沿用现有属性白名单：

- `a`：`href`、`title`；`rel` 由 nh3 统一写成 `noopener noreferrer`
- `pre`：`tabindex="0"`

消毒参数保持：`url_schemes={"http", "https"}`、`url_relative="deny"`、`clean_content_tags` 剔除脚本 / 样式 / iframe / object / embed / svg / math / form 及其内容。

明确不新增：

- 不保留 `class`，因此围栏代码块的语言类不会输出。
- 不保留 `id`、`style`、`on*` 事件属性。
- 不允许 `img`、`video`、`iframe`、`form`、`button` 等可主动加载或提交的元素。

如果后续评审要求 GFM 扩展（删除线、任务列表、自动链接等），需要新增扩展并同步扩大白名单和测试；本迭代默认不做。

#### 4.3.4 详情路由与模板

`app/api/v1/issues.py` 的 `issue_detail` 增加：

```python
design_doc_html = render_design_doc(issue.design_doc_text)
has_design_doc = bool(
    issue.design_doc_path
    and issue.design_doc_text
    and issue.design_doc_text.strip()
)
```

并传入模板。

模板逻辑：

```jinja
{% if has_design_doc %}
<section class="card card-border bg-base-100 shadow-sm" aria-labelledby="design-doc-title">
  <div class="card-body p-5">
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <h2 id="design-doc-title" class="card-title text-base">设计文档</h2>
      <code class="...">{{ issue.design_doc_path }}</code>
      {% if issue.iteration_no %}<span class="badge badge-sm badge-ghost font-mono">{{ issue.iteration_no | iteration_label }}</span>{% endif %}
    </div>

    {% if design_doc_html is not none %}
    <div class="md-content max-h-[32rem] overflow-auto rounded-lg border border-base-300 p-3 pr-2"
         tabindex="0" role="region" aria-label="设计文档正文">
      {{ design_doc_html }}
    </div>
    {% else %}
    <pre class="max-h-[32rem] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-base-300 bg-base-200 p-3 font-mono text-xs leading-relaxed text-base-content">{{ issue.design_doc_text }}</pre>
    {% endif %}
  </div>
</section>
{% endif %}
```

要点：

- 卡片只在「路径存在且正文去空白后非空」时出现，避免空卡片。
- Markdown 成功时用 `.md-content`，不保留外层等宽 `pre`；标题、列表、代码块、表格按正文排版。
- 渲染失败时回退到源文 `<pre>`，仍然自动转义，保证安全且不出现空白卡片。
- 滚动容器带 `tabindex="0"`、`role="region"` 和 `aria-label`，长文档可用键盘滚动；内部 `pre` / `table` 继续由 `.md-content` 规则提供横向滚动。
- 模板只输出 `design_doc_html`，不写 `|safe`；该值只能来自经过 nh3 消毒并包装为 `Markup` 的渲染函数。

### 4.4 页头刷新按钮

#### 4.4.1 模板

在 `page_header` 的 caller 中，外链之后增加 POST 表单：

```jinja
{% if issue.html_url %}
<a class="btn btn-sm btn-outline gap-1.5" href="{{ issue.html_url }}" target="_blank" rel="noopener">
  {{ icon('external-link') }}<span>在 GitHub 打开</span>
</a>
{% endif %}
<form method="post" action="/issues/{{ issue.id }}/refresh" class="inline-flex">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
  <button type="submit" class="btn btn-sm btn-ghost gap-1.5"
          aria-label="从 GitHub 刷新本 Issue 的标题、正文和标签"
          data-gw-submit>
    {{ icon('refresh') }}<span>刷新</span>
  </button>
</form>
```

- 刷新按钮独立于 `issue.html_url` 显示；即使外链缺失，也仍可通过 API 用仓库名和编号拉取。
- 不需要二次确认：刷新是只读同步，不触发写文档、生成代码或 PR 操作。
- 使用 `data-gw-submit` 复用现有提交态：提交后禁用按钮并显示 spinner，避免重复点击。
- 外链 `btn-outline`、刷新 `btn-ghost`，同一操作区仍有清晰主次。

#### 4.4.2 路由

新增：

```python
@router.post("/issues/{issue_id}/refresh")
def refresh_issue(
    issue_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(require_csrf)],
):
    ...
```

行为：

1. 按 `issue_id` 读取 Issue；不存在或已软删除时返回 404 页面（与详情 GET 一致）。
2. 读取所属 Repository；缺失时按现有异常路径处理。
3. 构造 `GitHubClient`，调用新增的 `get_issue`；无论成功失败都在 `finally` 中 `close()`。
4. 成功：303 到 `/issues/{issue_id}?flash=ok&msg=已刷新`。
5. `GitHubAPIError` 或网络异常：303 到 `/issues/{issue_id}?flash=error&msg=...`，不改变本地 Issue；停留本页显示错误。
6. 只接受 POST。GET `/issues/{id}/refresh` 应为 405，不产生副作用。
7. CSRF 由 `require_csrf` 校验；未登录走现有 `require_page_user` 的登录跳转，CSRF 不通过返回 403，与其它 POST 表单一致。

错误文案建议统一以「刷新失败」开头，并按状态码给出可操作提示：

| 情况 | 文案方向 |
| --- | --- |
| 404 / 410 | GitHub 上找不到该 Issue，可能已删除或无权访问 |
| 401 / 403 | GitHub 授权失败，请检查访问令牌 |
| 429 | GitHub 限流，请稍后再试 |
| 网络异常 / 5xx | 暂时无法连接 GitHub，请稍后重试 |
| 身份不匹配 | 拉取到的 Issue 与本地记录不一致，未更新 |

#### 4.4.3 GitHub API 客户端

在 `app/services/github_api.py` 增加：

```python
def get_issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
    return self._request("GET", f"/repos/{owner}/{repo}/issues/{number}")
```

使用 `repository.github_full_name` 拆出 `owner` / `repo`，使用本地 `issue.number` 拼路径。返回后校验：

- 响应是 `dict`；
- `id` 等于本地 `issue.github_issue_id`；
- `number` 等于本地 `issue.number`。

任一项不满足则按「身份不匹配」失败，不写库。这样可以防止仓库改名、编号错位或错误响应污染本地行。

#### 4.4.4 同步服务与字段语义

在 `app/services/ingest.py` 增加 `refresh_issue_from_github(db, client, issue, repo)`，复用现有 Webhook 的字段映射和 upsert：

```python
issue_crud.upsert_from_webhook(
    db,
    repository_id=repo.id,
    github_issue_id=payload["id"],
    number=payload["number"],
    title=payload.get("title") or "",
    body=payload.get("body") or "",
    html_url=payload.get("html_url") or "",
    author_login=(payload.get("user") or {}).get("login") or "",
    github_state=payload.get("state") or "open",
    label_names=label_names,
    github_updated_at=_parse_dt(payload.get("updated_at")),
    action="edited",
)
```

同步语义与 Webhook 保持一致：

| 字段 | 刷新行为 |
| --- | --- |
| `github_issue_id`、`number` | 先校验一致；不一致失败，不写 |
| `title`、`body`、`html_url`、`author_login` | 按远端覆盖 |
| `label_names` | 按远端覆盖 |
| `github_state` | 按远端 `open` / `closed` 覆盖 |
| `github_updated_at`、`github_state_updated_at` | 按远端 `updated_at` 更新 |
| `kind` / `status` | 仅当本地仍在早期状态（`pending_classify` / `recorded` / `support_open`）且未被锁定时，按标签重新分类；已进入编写 / 生成 / PR 等状态时保持本地流程状态 |
| `design_doc_path`、`design_doc_text`、`iteration_no` | 不动 |
| `design_source_updated_at` | 不动；若远端 `github_updated_at` 变新，详情页会自然出现「文档完成后有更新」告警 |
| PR 字段 | 不动 |
| `last_error` | 不动；刷新不是任务重试 |
| Job | 不入队、不取消、不改状态 |

沿用 `upsert_from_webhook` 的时间戳守卫：远端 `updated_at` 不早于本地记录时才覆盖，避免手动刷新与刚刚到达的 Webhook 乱序回退。若远端时间戳更旧，接口仍返回成功提示，但页面内容可能不变；这是有意的并发保护。

补充约定：

- 远端 Issue 已删除（404 / 410）时**不软删除**本地行，只报错。软删除仍由 Webhook 的 `deleted` 事件负责，避免一次读请求造成不可逆状态变化。
- 刷新遇到远端 `closed` 时不主动取消排队任务。Worker 开始执行时会按现有前置检查跳过非 open Issue；运行中的任务不受影响。这与「刷新只同步元数据」的边界一致。
- 刷新不调用 `sync_owner_and_repo`，不重新拉取公司 / 仓库资料；本迭代只同步当前 Issue。仓库资料仍由仓库页的「重新同步」负责。

### 4.5 与 daisyUI 组件约定的关系

当前模板已经使用 `card`、`card-body`、`card-title`、`btn`、`badge` 等 daisyUI 结构。本迭代：

- 不新增自研卡片 / 按钮壳。
- 版面只使用 Tailwind 栅格与尺寸工具类，属于 daisyUI 无对应组件的布局补齐。
- 若全站 daisyUI 5 组件化尚未合并，沿用当前 `card` / `btn` 过渡结构；若已合并，也不改变本设计的结构与类名语义。

### 4.6 测试与验证

#### Markdown 单元测试

更新 `tests/test_markdown_render.py`，新增 `render_design_doc` 用例：

1. 标题映射：`#` → `h3`、`##` → `h4`、`###` → `h5`、`####` 及更深 → `h6`。
2. 常用语法：段落、粗体、斜体、行内代码、列表、引用、水平线、围栏代码块、表格。
3. 链接：`https` / `http` 保留并带 `rel="noopener noreferrer"`；相对链接、锚点、`javascript:`、`data:`、`mailto:` 不保留 `href`。
4. XSS：`script`、`style`、`iframe`、`svg`、`form`、`img onerror`、`onclick`、`style`、`id`、`class` 均被清除或剥离。
5. 空白输入返回 `None`；消毒异常返回 `None`，不返回 `Markup`。

#### UI 测试

更新 `tests/test_ui.py` 的 `test_issue_detail_two_column_layout_and_markdown`：

- 断言 `xl:grid-cols-10`、`xl:col-span-6`、`xl:col-span-4`，并断言不存在 `xl:grid-cols-3` / `xl:col-span-2`。
- 断言 `data-gw-region="issue-side"` 内仍有 `task-title`、`log-title`、`issue-live-status`、`issue-log`、`issue-log-jump`，且顺序不变。
- 设计文档断言从「`<pre>` 源文」改为「`.md-content` 中有 `<h3>…</h3>` / `<h4>…</h4>`、列表、代码块、表格」，并断言卡片中不再出现 `># 设计源文</pre>`。
- 新增无设计文档 / 空正文时不出现 `id="design-doc-title"` 的断言。
- 新增页头刷新按钮断言：存在 `action="/issues/{id}/refresh"`、`method="post"`、CSRF 隐藏字段、`aria-label` 和「刷新」文案；外链仍在刷新左侧。
- 保留 `#issue-log` 唯一、轮询 id、`aria-live`、状态片段等现有断言。

#### 刷新路由测试

新增 `tests/test_issue_refresh.py`（或并入 `tests/test_issues.py`），用 fake `GitHubClient` 覆盖：

1. 成功刷新：远端标题 / 正文 / 标签 / `github_state` / 链接 / 作者 / `updated_at` 更新到本地，303 回详情并带 `flash=ok`。
2. 早期状态按新标签重新分类；锁定状态不被刷新改回。
3. `GitHubAPIError` / 网络异常：303 回详情并带 `flash=error`，本地行保持原值。
4. 返回的 `id` 或 `number` 与本地不一致：失败且不写库。
5. 有 queued / running Job 时刷新：元数据更新，Job 状态不变，也不新增 Job。
6. 缺 CSRF 或错误 CSRF：403；未登录：与现有页面一致跳登录。
7. GET `/issues/{id}/refresh`：405。

#### 静态检查

```bash
# 旧 2:1 写法应为 0 命中
grep -RIn "xl:grid-cols-3\|xl:col-span-2" app/templates

# 模板不应新增裸 safe 输出
grep -RIn "|safe" app/templates

# Markdown / UI / 全量测试
uv run pytest -q
```

人工检查：

- 1440px 下开发者工具确认左右栅格宽度约为 6:4。
- 375px 下正文 / 设计文档在上，任务卡和日志卡在下。
- 设计文档的标题、列表、代码块、链接、表格可读；长文档在卡片内滚动；代码块和表格可横向滚动。
- 含恶意 HTML 的设计文档不执行脚本、不加载外部资源。
- 页头刷新在桌面和移动端都紧邻外链；点击后成功 / 失败均有 flash。
- 有任务时点击刷新不改变任务卡状态，轮询与「有新日志，回到底部」仍工作。

### 4.7 风险与回滚

| 风险 | 说明 | 处理 |
| --- | --- | --- |
| Markdown XSS | 设计文档由代理生成，可能包含原始 HTML 或恶意链接 | 服务端 Markdown + nh3 白名单；链接只允许 http/https；异常时回退转义 `<pre>`；不新增 `|safe` |
| 渲染器行为漂移 | 设计文档与 Issue 正文共用管线后，改一处影响两处 | 保留 `render_issue_body` 现有行为，共用消毒与代码块处理，仅标题映射分开；补两套测试 |
| 刷新与 Webhook 乱序 | 手动刷新可能拿到比本地更旧的快照 | 沿用 `upsert_from_webhook` 的时间戳守卫；旧快照不覆盖新数据 |
| GitHub 限流 / 网络故障 | 刷新按钮可能失败 | 错误 flash，不写库；提示检查令牌或稍后重试 |
| 6:4 后右栏日志变宽但页面更长 | 右栏宽度增加，日志行数变化 | 保持日志卡内部滚动和「回到底部」；不改变轮询逻辑 |
| 回滚 | 模板、路由、服务、测试一起改动 | 回滚整个 PR；无数据库迁移、无 Job / Webhook 数据回滚 |

## 5. 影响面

| 区域 | 影响 |
| --- | --- |
| `app/templates/issue_detail.html` | 主栅格改 10 列 6:4；设计文档卡改 `.md-content` + 安全回退；页头增加刷新 POST 表单 |
| `app/api/v1/issues.py` | 详情上下文增加 `design_doc_html`、`has_design_doc`；新增 `POST /issues/{issue_id}/refresh` |
| `app/services/markdown_render.py` | 抽出公共渲染步骤，新增 `render_design_doc`；Issue 正文行为不变 |
| `app/services/github_api.py` | 新增 `get_issue(owner, repo, number)` |
| `app/services/ingest.py` | 新增 `refresh_issue_from_github`，复用 `issue_crud.upsert_from_webhook` |
| `tests/test_markdown_render.py` | 新增设计文档渲染、标题映射、XSS 用例 |
| `tests/test_ui.py` | 更新设计文档渲染断言；新增 6:4 栅格、空文档、刷新按钮断言 |
| `tests/test_issue_refresh.py`（新增）或 `tests/test_issues.py` | 刷新成功 / 失败 / CSRF / 任务并存 / 身份校验 |
| `docs/architecture/design.md` | 实现 PR 同步 Issue 详情与界面契约：设计文档安全 Markdown、6:4 布局、刷新入口 |
| 数据库 / 迁移 / 部署 | 无变化；无新表、无新字段、无环境变量 |
| Webhook / Worker / Job / 状态机 | 无变化；刷新不入队、不取消、不改任务状态 |

## 6. 验收

- [ ] 桌面 `xl` 下左:右可视宽度约为 6:4，使用 `xl:grid-cols-10` + `xl:col-span-6` / `xl:col-span-4`，不再是 2:1。
- [ ] 小屏为上下堆叠，正文 / 设计文档在任务卡与日志卡之上。
- [ ] 设计文档中的标题、段落、列表、链接、行内代码、代码块、引用、表格正确渲染。
- [ ] 设计文档中的恶意 HTML / 脚本 / 事件属性 / 危险协议链接被消毒，不执行、不加载。
- [ ] 无设计文档或正文为空时，不出现空的「设计文档」卡片；有文档时路径与迭代号仍可见。
- [ ] 「在 GitHub 打开」右侧有「刷新」；点击后从 GitHub 同步标题、正文、标签、`github_state`、链接、作者与更新时间，并反馈成功 / 失败。
- [ ] 刷新走 POST + CSRF；未登录 / 会话失效行为与现有页面一致；GET 不产生写副作用。
- [ ] 有排队中 / 执行中任务时刷新仍可用，且不改变 Job 状态、不新增入队。
- [ ] 轮询与任务日志不因布局改动失效，`#issue-live-status`、`#issue-log` 等 DOM id 仍存在。
- [ ] 设计文档渲染异常时回退到自动转义的源文，不出现未消毒 HTML。
- [ ] UI / Markdown / 刷新相关 pytest 更新并通过。
- [ ] 实现 PR 更新 `docs/architecture/design.md` 的 Issue 详情与界面契约表述（Markdown 与刷新）。
- [ ] 实现走 `dev_11` 并开 PR。

## 7. 待确认

以下规则 Issue 未给出唯一结论，本文按默认方案推进；最终以评审或实现 PR 确认为准。

1. **Markdown 库与白名单**：默认复用现有 `Python-Markdown + nh3`，沿用现有标签 / 属性白名单，仅新增设计文档的标题映射。是否改用其它库，或把白名单扩展到 GFM 的删除线、任务列表、自动链接等，需要评审确认；若扩展，必须同步补 XSS 与语法测试。
2. **最新任务日志位置**：默认保持现状，留在右栏「任务与 Worker」下方，不改为全宽底栏。若评审希望日志占满底部，需要再确认轮询脚本、`scrollTop` 和「回到底部」在小屏 / 桌面下的表现。
3. **Issue 正文是否一并调整**：当前实现已经使用服务端 Markdown + nh3 渲染 Issue 正文，本迭代不再重复实现，也不扩展其语法。若实际分支与基线不一致，或评审希望正文与设计文档完全共用同一标题映射，需要另开改动；默认保持现有 `render_issue_body` 行为。
4. **刷新遇到 404 / 410 是否软删除本地 Issue**：默认不删除，只报错，避免一次读操作产生不可逆状态；软删除仍由 Webhook 的 `deleted` 事件负责。若希望刷新即软删除，需要单独确认。
5. **刷新是否应顺带取消排队任务**：默认不取消。刷新只同步元数据；远端变为 closed 时，Worker 的现有前置检查会跳过排队任务。若要求刷新也立即取消 queued Job，需要明确这是新的业务规则。
6. **刷新按钮在无 `html_url` 时是否显示**：默认仍显示，因为刷新只需要仓库全名和 Issue 编号；外链缺失不影响 API 拉取。若评审希望与「在 GitHub 打开」同时隐藏，需要确认。
