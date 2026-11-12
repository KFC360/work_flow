# Issue 详情双栏布局与正文 Markdown 安全渲染（v0003 / Issue #5）

- 迭代：`v0003`，对应 GitHub Issue `#5`
- 文档路径：`docs/v0003-5/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：相对基石的 **Issue 详情展示增量**，不替代基石，不改 Webhook / Job / 写文档·生成代码状态机 / 数据模型

## 1. 背景

`/issues/{id}` 当前的信息顺序是：页头与告警、流程操作、摘要条、主内容两栏、全宽日志。主内容两栏中，左栏 `xl:col-span-2` 放 Issue 正文和设计文档，右栏 `xl:col-span-1` 只有「任务与 Worker」；「最新任务日志」在网格下方单独占满整行。

这带来两个直接问题：

1. **阅读与任务信息脱节**：正文在左、任务在右，日志却在页面最底部。长正文或长设计文档需要向下滚很远才能看到日志；执行中的日志更新也不在视线范围内。
2. **正文不可读**：当前正文用 `<pre class="whitespace-pre-wrap ...">{{ issue.body }}</pre>` 纯文本展示。GitHub Issue 中常见的标题、列表、引用、行内代码、围栏代码块、表格和链接都失去结构，长正文尤其难读。

基石旧稿曾以 XSS 和构建依赖为由写明「Issue 正文不做完整 Markdown 渲染」。本迭代明确放开正文 Markdown，但前提是**服务端渲染后必须消毒**；不把未经消毒的 HTML 直接交给模板或前端 `innerHTML`。

本迭代的版面工作使用 `ui-ux-pro-max` 的布局与无障碍原则，继续沿用现有浅色运维台、`gw-card`、`icon()`、DaisyUI 徽章和 `max-w-7xl` 主内容区，不引入新的视觉体系。

## 2. 目标

### 2.1 桌面双栏

在 `xl`（`>=1280px`）下形成：

| 左栏（约 2/3） | 右栏（约 1/3） |
| --- | --- |
| Issue 正文卡片 | 任务与 Worker 卡片（上） |
| 设计文档卡片（有则显示，仍在正文下方） | 最新任务日志卡片（下，紧挨任务卡片） |

要求：

- 左栏保留 `xl:col-span-2`；右栏 `xl:col-span-1`。
- 右栏内部用纵向间距把任务卡片和日志卡片紧挨着排列；日志不再放在网格下方全宽展示。
- 页顶告警、流程操作、摘要条、页头位置保持不变。
- 正文过长时继续由左栏自然增高，不压缩右栏卡片宽度。
- 桌面两栏顶部对齐；右栏不被拉伸成与左栏等高。

### 2.2 小屏单列

- 小于 `xl` 时退回单列，不出现横向挤压或整页横向滚动。
- 顺序为：**Issue 正文 →（若有设计文档）→ 任务与 Worker → 最新任务日志**。
- 没有设计文档时，即验收要求的「正文 → 任务 → 日志」。
- 正文、代码块、表格、日志各自在内部滚动，不撑破视口。

### 2.3 正文 Markdown 安全渲染

- 将 `issue.body` 按常见 Markdown 子集渲染为 HTML：标题、段落、有序 / 无序列表、引用、行内代码、围栏代码块、链接、粗体、斜体、分隔线、表格。
- 采用「Markdown → HTML → HTML sanitize」管线，只把消毒后的结果交给模板。
- 禁止未消毒的 `|safe` 输出；禁止把正文 HTML 直接拼进前端 `innerHTML`。
- 链接只允许 `http` / `https`，并加 `rel="noopener noreferrer"`。
- 原始 HTML 中的脚本、事件属性、`style`、`iframe`、`svg`、表单控件等一律剥除。
- 无正文时仍显示「该 Issue 没有正文。」。
- 正文渲染样式与运维台一致：可读行高、等宽代码块、表格可横向滚动、长链接 / 长单词不撑破卡片。

### 2.4 保持轮询与现有交互

- `#issue-live-status`、`#issue-log`、`#issue-log-live`、`#issue-log-jump`、`#issue-live-indicator`、`#issue-session-error` 等 id 和脚本行为保持可用。
- 编写中 / 生成中仍每 5 秒刷新状态和日志。
- 日志默认滚到底；用户上滚后保持位置并显示「有新日志，回到底部」。
- 收到 401 / 登录页响应时停止轮询并提示重新登录。
- `data-done="0|1"` 片段契约不变。

### 2.5 文档同步

- 本迭代结论取代「详情正文不做 Markdown」的旧表述。
- 由于本次任务只允许写 `docs/v0003-5/design.md`，基石正文和 `docs/architecture/design.md` 的同步更新列入第 7 节影响面和第 9 节待确认，由实现 PR 或后续人工补齐。

## 3. 非目标

- 不做完整 GitHub 风格体验：不实现 emoji 短代码、`@mention` 高亮、Issue / PR 自动链接、任务列表勾选框、脚注、目录、语法高亮。
- 不引入前端框架、npm 或构建链；继续服务端渲染。
- 不改 `issue.status`、`codegen_phase`、`job.status`、`github_state` 等状态机与入队条件。
- 不改 Webhook、Inbox、Worker、代理、git、PR 逻辑。
- 不改日志读取安全边界、日志文件位置、日志摘录长度或 401 鉴权规则。
- 不新增数据库列、不迁移、不做正文 HTML 缓存。
- 不把设计文档强制改为 Markdown 渲染；本期仍以等宽 `<pre>` 展示源文。
- 不做正文编辑、评论、回复或 Issue 新建。
- 不引入 CSP、Trusted Types 等额外前端安全机制；本期以服务端消毒为主控制，CSP 可作为后续加固。
- 不改变页头「在 GitHub 打开」、流程按钮、确认弹窗和 flash 约定。

## 4. 相对基石的增量声明

### 4.1 保持不变

| 维度 | 结论 |
| --- | --- |
| 数据模型 | `issue.body` 继续保存 GitHub 原文；不新增列、不迁移 |
| 状态机 | 所有状态、阶段、任务流转和失败重试规则不变 |
| 入队条件 | `actions_for` 与按钮条件不变 |
| 轮询端点 | `/issues/{id}/status-fragment` 的路径、鉴权、片段结构不变 |
| 鉴权 | JWT、cookie、CSRF、页面 / 片段鉴权不变 |
| 日志安全 | 仍只展示摘录；仍不把日志拼进 `innerHTML` |
| 设计文档 | 仍以源文 `<pre>` 展示，路径和迭代号展示不变 |
| 页面骨架 | 页头、面包屑、告警、操作条、摘要条位置不变 |
| 外链约定 | GitHub 外链仍新标签打开并带 `rel="noopener"` |

### 4.2 本迭代增量

| 增量 | 说明 |
| --- | --- |
| 详情页网格 | 右栏从「只有任务卡片」扩展为「任务卡片 + 日志卡片」；日志从全宽底栏移入右栏 |
| 正文渲染 | 新增 Markdown 渲染与 HTML 消毒模块，模板输出消毒后的 `Markup` |
| 渲染样式 | 新增 `.gw-markdown` 作用域样式，覆盖标题、列表、代码、引用、表格和链接 |
| 依赖 | 增加 Markdown 解析与 HTML sanitize 的 Python 依赖，更新锁文件 |
| 测试 | 增加布局结构、Markdown 输出、XSS 消毒和空状态测试 |
| 文档 | 实现 PR 同步修订 `docs/architecture/design.md` 的 Issue 详情条款 |

### 4.3 对旧结论的取代

- 取代 `docs/architecture/design.md` 中「正文（纯文本 / 简单换行保留，不做完整 Markdown 渲染 Issue 正文）」的表述。
- 取代 v0001 迭代文档中「不做完整 Markdown / GFM 渲染；Issue 正文和设计文档继续以安全源文 / `<pre>` 展示」的正文部分。
- 设计文档「不做 GFM 渲染」的结论本期继续保留；如果实现成本低并决定一并开放，见第 9 节待确认。
- 安全底线不变：任何进入模板的正文 HTML 必须先经过白名单消毒；「允许 Markdown」不等于「允许任意 HTML」。

## 5. 现状与差距

| 方面 | 现状 | 目标 |
| --- | --- | --- |
| 桌面主内容 | 左正文 + 设计文档，右任务；日志全宽在下方 | 左正文 + 设计文档，右任务 + 日志 |
| 阅读动线 | 正文与日志相距远，长文需长距离滚动 | 正文与任务 / 日志同屏，右栏紧邻 |
| 小屏顺序 | 左栏后接右栏，日志在最后 | 正文 →（设计文档）→ 任务 → 日志 |
| 正文 | `<pre>` 纯文本 | 消毒后的 Markdown HTML |
| XSS | 纯文本自动转义，无 HTML 注入面 | Markdown 后必须白名单消毒；禁止未消毒 `|safe` |
| 链接 | 纯文本不可点 | 仅 `http(s)`，带 `rel="noopener noreferrer"` |
| 代码块 | 无结构 | 等宽浅底块，内部横向滚动 |
| 表格 | 纯文本 | 渲染为表格，窄屏内部横向滚动 |
| 轮询 | 已有 5 秒轮询、滚底、401 停刷 | 全部保留，仅移动日志卡片位置 |
| 文档口径 | 基石旧稿说正文不做 Markdown | 本迭代改为「允许 Markdown + 强制消毒」 |

## 6. 方案

### 6.1 页面结构

```text
页头 / 面包屑                         （不变）
会话失效告警                          （不变）
基石缺失 / 文档过期 / 标签不一致告警    （不变）
last_error 告警                       （不变）
流程操作条                            （不变）
Issue 摘要条                          （不变）

<div class="grid gap-4 xl:grid-cols-3 xl:items-start">
  <div class="space-y-4 xl:col-span-2">        左栏
    [Issue 正文卡片]                            Markdown 渲染
    [设计文档卡片（可选）]                      源文 <pre>
  </div>

  <div class="space-y-4 xl:col-span-1"          右栏
       data-gw-region="issue-side">
    [任务与 Worker 卡片]                        （内容不变）
    [最新任务日志卡片]                          （从底栏移入）
  </div>
</div>
```

实现要点：

- 删除模板末尾原来全宽的日志 `<section>`，把整段日志卡片移入右栏 wrapper。不得保留两份日志 DOM，避免重复 id。
- 右栏 wrapper 使用 `space-y-4`，让日志卡片紧贴任务卡片。
- 网格使用 `xl:items-start`，避免右栏被拉长到左栏高度；左栏正文自然增长。
- `xl` 以下不使用两栏；DOM 顺序即阅读顺序。左栏 wrapper 在右栏 wrapper 之前，因此移动端为正文 →（设计文档）→ 任务 → 日志。
- 设计文档在本期仍留在左栏正文下方；如果团队要求移动端严格把设计文档放到日志之后，需要额外的 DOM 重排方案，见第 9 节待确认。
- 日志卡片继续使用现有标题、`job #id`、动作中文、`job_badge`、轮询指示器、`#issue-log`、`#issue-log-jump`、`#issue-log-updated` 结构。
- 日志容器继续使用 `max-h-96 overflow-auto whitespace-pre-wrap break-words`。右栏变窄后仍依靠 `break-words` 和内部滚动，不扩大到撑破网格。
- 不强制右栏 sticky。若实现时右栏高度可控，可增加 `xl:sticky xl:top-20 xl:self-start` 以在长正文滚动时保持任务 / 日志可见；该增强见第 9 节待确认。
- 轮询脚本不改：它按 id 查找 `#issue-live-status`、`#issue-log`、`#issue-log-live`、`#issue-log-jump`，移动 DOM 位置不影响查找。

### 6.2 正文渲染管线

数据流：

```text
issue.body（数据库原文，仍是 Markdown 源文）
  → 空值判断
  → Markdown 解析（受限扩展）
  → 标题层级规整
  → HTML sanitize（白名单标签 / 属性 / URL scheme）
  → Markup（仅在消毒成功后）
  → issue_detail.html 正文卡片
```

建议实现位置：新增独立模块，例如 `app/services/markdown_render.py`，暴露一个纯函数：

```python
def render_issue_body(raw: str) -> Markup | None:
    ...
```

约定：

1. **空正文**：`raw` 为空或仅空白时返回 `None`；模板走现有空状态「该 Issue 没有正文。」。
2. **先 Markdown 后消毒**：不能先消毒再 Markdown，因为 Markdown 解析器可能在之后生成新的标签。
3. **受限扩展**：只启用明确需要的扩展，例如 `fenced_code`、`tables`、`sane_lists`；不整体启用 `extra`，避免 `attr_list`、脚注等额外语法扩大输出面。
4. **原始 HTML**：Python-Markdown 默认会透传原始 HTML，这是预期行为；安全边界放在后面的 sanitizer，不依赖解析器「关闭 HTML」。
5. **标题层级规整**：正文卡片标题是 `h2`，页面标题是 `h1`。正文里的 `h1` / `h2` 统一降级为 `h3` 起的层级，最高到 `h6`，避免一页出现多个 `h1` 或跳级。可用 Markdown `Treeprocessor` 在序列化前调整，或在消毒前做受控的标签重命名；不要用正则整体清洗 HTML。
6. **围栏代码块**：输出 `<pre><code>...</code></pre>`。本期不做语法高亮，不保留 `language-*` class，减少样式冲突和属性注入面。
7. **表格**：启用 `tables` 扩展，输出标准 `table / thead / tbody / tr / th / td`。Markdown 的对齐样式不保留，统一左对齐；窄屏由容器内部横向滚动。
8. **单换行**：默认遵循 Markdown / GitHub 语义，单换行折叠为空格，不额外开启 `nl2br`。需要硬换行时使用空行、行尾两个空格或 `<br>`（`<br>` 在允许标签内）。是否兼容旧纯文本的「单换行即换行」见第 9 节待确认。
9. **失败关闭**：Markdown 或 sanitize 抛异常时，不回退到未消毒 HTML，也不返回 500；模板回退为自动转义的纯文本 `<pre>`，并记录服务端警告。安全优先于排版。
10. **不缓存**：正文渲染只发生在详情页 GET；Issue 正文长度有限，Markdown + sanitize 成本可接受。不做数据库缓存，避免正文更新后缓存不一致。
11. **轮询不渲染正文**：`status-fragment` 只更新状态和日志，不重新渲染正文；正文变化仍以整页刷新为准，和现状一致。

### 6.3 HTML 白名单

推荐使用 Python-Markdown 做解析，`nh3`（Rust ammonia 绑定）做消毒；若依赖审计要求使用 `bleach`，保持同一套白名单和测试契约。最终库选择见第 9 节待确认。

建议白名单：

| 类别 | 允许 |
| --- | --- |
| 块级标签 | `p`、`br`、`h3`、`h4`、`h5`、`h6`、`blockquote`、`pre`、`ul`、`ol`、`li`、`hr`、`table`、`thead`、`tbody`、`tr`、`th`、`td` |
| 行内标签 | `a`、`strong`、`em`、`code` |
| `a` 属性 | `href`、`title`、`rel` |
| `pre` / `code` 属性 | 本期不保留 `class`；如为键盘滚动给 `pre` 加 `tabindex="0"`，只允许该属性 |
| URL scheme | 仅 `http`、`https` |
| 链接 rel | 统一追加 `noopener noreferrer` |
| 注释 | 剥除 HTML 注释 |
| 禁止标签 | `script`、`style`、`iframe`、`object`、`embed`、`svg`、`math`、`form`、`input`、`button`、`textarea`、`select`、`img`、`video`、`audio`、`link`、`meta`、`base`、`h1`、`h2` |
| 禁止属性 | 所有 `on*` 事件属性、`style`、`id`、`class`（`pre` 的 `tabindex` 例外）、`src`、`srcset`、`formaction`、`xlink:href` |

URL 约束：

- `javascript:`、`data:`、`file:`、`vbscript:` 等一律剥除。
- 仅保留绝对 `http://` 或 `https://`；相对链接、协议相对链接（`//host/...`）和页内锚点本期不作为正文链接输出。若 sanitizer 对相对 URL 的默认行为不够严格，在消毒后增加受控的 `a[href]` 校验，或使用属性过滤回调固定该行为；校验失败时移除 `href` 或整段链接。
- 链接统一加 `rel="noopener noreferrer"`。本期默认同标签打开，不主动加 `target="_blank"`；是否新标签打开见第 9 节待确认。
- 链接的 `title` 文本允许，由 sanitizer 负责转义。

模板约束：

- 正文输出形如 `{{ issue_body_html }}`，其中 `issue_body_html` 必须是消毒成功后的 `markupsafe.Markup`。
- 不得在模板写 `{{ issue.body | safe }}`，也不得把未消毒字符串标记为 `Markup`。
- 回退纯文本时使用独立的 `<pre>{{ issue.body }}</pre>` 分支，让 Jinja 自动转义。
- 其它字段（设计文档、`last_error`、`sync_error`、日志摘录）继续自动转义，不因为本次改动放宽。

### 6.4 正文样式

在 `head_assets.html` 的全局 `<style>` 中新增 `.gw-markdown` 作用域样式，或放到独立 CSS 片段；不引入 Tailwind Typography 插件或新构建链。

建议：

| 元素 | 样式方向 |
| --- | --- |
| 容器 | `text-sm leading-7 text-slate-800`，`overflow-wrap:anywhere`，段落间距约 `0.75rem` |
| 标题 | `h3` 约 `text-base font-semibold`；`h4`–`h6` 逐级减小；颜色 `slate-900`；标题上间距大于下间距 |
| 列表 | 标准缩进，`ul` 圆点 / `ol` 数字；嵌套列表保留缩进；列表项间距约 `0.25rem` |
| 行内代码 | `bg-slate-100`、圆角、`font-mono`、约 `0.85em`，允许断行 |
| 围栏代码 | 浅色底 `bg-slate-50`、`border-slate-200`、圆角、内边距；`overflow-x:auto`；`font-mono text-xs leading-relaxed`；长行横向滚动 |
| 引用 | 左侧边框 `border-l-4 border-slate-200`，内缩进，文字 `text-slate-600` |
| 链接 | `text-sky-700 underline underline-offset-2`，hover 加深；沿用全局 focus ring |
| 表格 | 全宽或自适应，表头浅灰底，单元格边框，`font-size` 略小；容器或表格内部横向滚动，不撑破卡片 |
| 分隔线 | `border-slate-200`，上下留白 |
| 图片 | 本期不输出 `img`；如后续允许，见第 9 节待确认 |

可读性要求：

- 正文行高不小于 `1.6`；正文卡片内边距与现有 `gw-card p-5` 一致。
- 桌面正文宽度约为主内容 2/3，避免长行过宽；长 URL、长单词、代码块和表格必须内部断行或滚动。
- 代码块和表格不得造成整页横向滚动。
- 代码块若可横向滚动，建议加 `tabindex="0"`，让键盘用户能聚焦并滚动；视觉上保留焦点环。
- 不做暗色正文区；代码块使用浅色等宽块，和浅色运维台一致。日志仍保留现有深色终端块。

### 6.5 轮询与日志

本次只移动日志卡片的 DOM 位置，不改轮询协议和脚本逻辑：

- 轮询端点仍为 `GET /issues/{issue_id}/status-fragment`，仍要求登录，未登录仍 401。
- 片段仍包含 `#issue-live-status`、隐藏的 `#issue-log-live` 和 `data-done`。
- 页面脚本仍按 id 更新状态区、用 `textContent` 更新日志、按滚动位置决定是否显示「有新日志，回到底部」。
- 401 / 3xx / 登录页响应仍停止定时器并显示 `#issue-session-error`。
- 页面初始加载仍把日志滚到底。
- 任务结束后 `data-done="1"` 停止轮询，保留最终状态和日志。
- 日志卡片头部里的 job 信息不属于 `#issue-live-status`，轮询期间仍只在整页刷新时更新；这是现有行为，本次不扩大片段契约。
- 移动端日志卡片在任务卡片下方，宽度为整列；滚动和按钮定位沿用现有实现。

### 6.6 无障碍

- 标题层级：页面 `h1`、卡片标题 `h2`、正文标题从 `h3` 起；不出现多个 `h1`。
- 正文 Markdown 是静态内容，不使用 `aria-live`；只有 `#issue-live-status` 保留 `aria-live="polite"`。
- 日志容器仍 `aria-label="任务日志"`，不设置 `aria-live`，避免每次轮询朗读整段日志。
- 正文链接、代码块、表格滚动区保留可见 focus ring；键盘 Tab 顺序与视觉顺序一致。
- 状态、警告仍同时使用文字和颜色，不只靠颜色。
- 继续尊重 `prefers-reduced-motion`；轮询 spinner 在 reduced motion 下不旋转。
- 移动端正文不小于现有 `text-sm`，行高足够；不禁止浏览器缩放。
- 表格和代码块的横向滚动不劫持页面纵向滚动。

## 7. 影响面

| 区域 | 影响 |
| --- | --- |
| 模板 `app/templates/issue_detail.html` | 调整主网格结构；把日志卡片移入右栏；正文改为输出消毒后的 Markdown HTML；保留所有既有 id |
| 模板 `app/templates/partials/head_assets.html` | 新增 `.gw-markdown` 样式；不引入新字体或构建链 |
| 路由 `app/api/v1/issues.py` | 详情 GET 的模板上下文增加 `issue_body_html`；轮询路由不变 |
| 新模块 `app/services/markdown_render.py` | Markdown 解析、标题规整、sanitize、失败回退；集中维护白名单 |
| 轮询片段 `app/templates/partials/issue_live.html` | 不改；继续提供 `#issue-live-status`、`#issue-log-live`、`data-done` |
| 轮询脚本 | 不改；仅依赖 id，不依赖 DOM 位置 |
| 数据模型 | 无变化；`issue.body` 仍存原文；无 Alembic 迁移 |
| API / 鉴权 | 无新增端点；无权限变化 |
| 日志 | 无变化；仍只展示摘录，仍不写完整日志到页面 |
| 依赖 | 新增 Python Markdown 与 sanitize 依赖，更新 `pyproject.toml` / `uv.lock`；部署执行一次依赖同步 |
| 测试 | 新增渲染单测、XSS 消毒测试、布局结构测试；现有轮询测试保持通过 |
| 文档 | 实现 PR 应同步修订 `docs/architecture/design.md` 的 Issue 详情条款；本任务只写本文件 |
| 性能 | 每次详情 GET 多做一次 Markdown + sanitize；正文长度有限，预计开销可忽略；不增加数据库查询 |
| 安全 | 主要风险是 XSS 和恶意链接；通过白名单 sanitize、URL scheme 限制、失败关闭和测试覆盖控制 |
| 兼容性 | 纯文本正文仍能正常渲染为段落；旧 `<pre>` 行为被替换，属预期变更 |

实现时建议新增的测试：

- `tests/test_markdown_render.py`：标题、列表、引用、行内代码、围栏代码块、链接、粗斜体、表格、空正文。
- XSS 用例：
  - `<script>alert(1)</script>` 不出现 `script` 标签，脚本内容不执行。
  - `<img src=x onerror=alert(1)>` 不出现 `img` 和 `onerror`。
  - `<a href="javascript:alert(1)">x</a>` 不保留 `javascript:`。
  - `<a href="data:text/html,...">x</a>` 不保留 `data:`。
  - `<iframe src=...>`、`<svg onload=...>`、`<style>`、`<form>`、`<input>` 不出现。
  - `onclick`、`style`、`id`、`class` 等属性被剥除。
  - 合法 `https://` 链接保留并带 `rel="noopener noreferrer"`。
- `tests/test_ui.py`：
  - 详情页包含 `data-gw-region="issue-side"`，任务卡片和日志卡片都在右栏 wrapper 内。
  - 日志卡片位于任务卡片之后。
  - `#issue-log`、`#issue-log-jump`、`#issue-live-status` 仍存在。
  - 正文 Markdown 输出为 HTML，而不是转义后的 `<p>` 文本。
  - 无正文时显示空状态。
  - 设计文档仍以 `<pre>` 展示。
  - 轮询片段测试保持 `data-done="0"` / `"1"`、`#issue-log-live`、401 行为不变。

## 8. 验收

- [ ] 桌面 `xl`：左栏为 Issue 正文（其下为设计文档，若有），右栏上方为「任务与 Worker」，下方为「最新任务日志」；日志不再全宽出现在网格下方。
- [ ] 桌面右栏两张卡片紧邻，左栏正文过长时自然增高，不出现栏高错位或横向滚动。
- [ ] 小于 `xl`：单列可读，顺序为正文 →（设计文档）→ 任务 → 日志；375px 宽度下无整页横向滚动。
- [ ] 页顶告警、流程操作、摘要条位置保持不变；`#issue-session-error` 仍可在 401 时显示。
- [ ] 编写中 / 生成中时日志仍每 5 秒轮询更新；默认滚到底；上滚后显示「有新日志，回到底部」；401 时停刷并提示重新登录；任务结束后停止。
- [ ] `#issue-live-status`、`#issue-log`、`#issue-log-live`、`#issue-log-jump`、`#issue-live-indicator`、`data-done` 契约保持可用。
- [ ] 含标题、段落、列表、引用、行内代码、围栏代码块、链接、粗斜体、表格的 Issue 正文正确排版。
- [ ] 代码块浅底等宽、可横向滚动；表格窄屏可横向滚动；长链接 / 长单词不撑破卡片。
- [ ] 含恶意 HTML / 脚本属性的正文被消毒：不出现 `script`、事件属性、`style`、`iframe`、`svg`、表单控件；`javascript:` / `data:` 链接不保留；输出中不执行脚本。
- [ ] 合法 `http(s)` 链接可点击，并带 `rel="noopener noreferrer"`。
- [ ] 无正文时显示「该 Issue 没有正文。」，不出现空白卡片。
- [ ] 设计文档仍以源文 `<pre>` 展示，路径和迭代号不变。
- [ ] 现有轮询、鉴权、任务、状态机测试全部通过；新增 Markdown / XSS / 布局测试通过；CI 绿灯。
- [ ] 实现 PR 同步更新 `docs/architecture/design.md` 的 Issue 详情条款，删除「正文不做 Markdown」的旧表述。
- [ ] 设计文档路径为 `docs/v0003-5/design.md`；分支为 `dev_5`；PR 由实现阶段创建。

## 9. 待确认

以下事项 Issue 未给出唯一结论，本文先给出默认处理，最终以评审或实现 PR 确认为准：

1. **Markdown 解析器与 sanitizer 的最终库**：建议 `markdown` + `nh3`；若团队依赖策略要求使用 `bleach`，白名单、URL 规则、`rel` 和测试契约保持不变。需在 `pyproject.toml` 固定版本并更新 `uv.lock`。
2. **设计文档是否也做 Markdown 渲染**：本期默认不做，继续用源文 `<pre>`，以控制范围和 XSS 面。若实现成本低且评审同意，可复用同一渲染模块，但必须单独加消毒测试，并确保设计文档里的代码块、表格不撑破左栏。
3. **正文图片**：本期默认不输出 `img`，避免外链追踪、混合内容和图片尺寸撑破布局。若后续要支持，需只允许 `https` 图片、限制属性、考虑 `referrerpolicy` 和加载失败回退。
4. **单换行语义**：默认遵循 GitHub Markdown，单换行折叠为空格，不启用 `nl2br`。若操作员更习惯旧纯文本的「单换行即换行」，可开启 `nl2br`，但会与 GitHub 预览不一致。
5. **正文链接打开方式**：默认同标签打开并加 `rel="noopener noreferrer"`。若希望不离开详情页，可改 `target="_blank"`；需要在链接属性和测试中同步。
6. **移动端设计文档位置**：默认仍在正文下方，因此有设计文档时移动端顺序为正文 → 设计文档 → 任务 → 日志；没有设计文档时严格为正文 → 任务 → 日志。若要求设计文档也排到日志之后，需要额外的 DOM 重排或折叠方案。
7. **右栏是否 sticky**：默认不做，按 Issue 要求完成两栏即可。若长正文滚动时仍希望任务 / 日志常驻，可加 `xl:sticky xl:top-20 xl:self-start`，但需确认右栏总高度和视口高度，避免日志被截断。
8. **GitHub 风格扩展**：emoji、`@mention`、Issue / PR 自动链接、任务列表、脚注、语法高亮均列为后续，不在本期。若评审要求其中某项，需要单独评估解析扩展和消毒规则。
9. **历史文档处理**：实现 PR 应更新 `docs/architecture/design.md`；v0001-2 等历史迭代文档建议保留历史结论，不逐条改写，只以基石最新条款为准。若团队要求历史文档也加勘误注记，需明确注记格式和范围。
10. **CSP 等额外加固**：本期不做。若后续引入 CSP，需要同时评估 DaisyUI / Tailwind CDN、内联轮询脚本和样式，不能只改正文渲染。
