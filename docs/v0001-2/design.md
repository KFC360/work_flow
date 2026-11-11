# 全站控制台 UI 改版设计（v0001 / Issue #2）

- 迭代：`v0001`，对应 GitHub Issue `#2`
- 文档路径：`docs/v0001-2/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：相对基石的**界面与布局增量**，不替代基石，不重写业务状态机

## 1. 背景

当前 Web 控制台（FastAPI + Jinja2 + DaisyUI `corporate` + Tailwind CDN）的业务链路已经打通：登录、公司 / 仓库 / Issue 浏览、编写文档、生成代码、创建 PR、Webhook 投递、Worker 心跳均可使用。但页面仍停留在“功能可用”的 demo 级形态：

- 顶栏只有品牌名、三个文字导航和退出，缺少当前上下文与页面层级。
- 列表基本是裸表，主次信息不分，状态只有默认徽章，空状态和筛选结果没有区分。
- 仓库列表的“路径未填写”、开放 Issue 数、同步操作不够醒目。
- Issue 详情把元数据、正文、设计文档和日志平铺，任务状态容易淹没主操作；日志区缺少“跟随最新”的体验。
- 投递列表直接展示原始状态码和仓库数字 id，错误摘要容易撑破表格。
- 设置页的代理选择和 Worker 心跳只是文字，不能一眼判断 Worker 是否活着。
- 贵重操作仍使用浏览器原生 `confirm()`，不符合基石[界面契约](../architecture/design.md#界面契约)中的 DaisyUI modal 要求。

基石已经写明“浅色专业运维台”的界面契约和逐页字段要求，实现尚未达到契约中的信息密度与反馈质量。Worker 已内置 OpenCode skills：本文档编写使用 `documentation`，涉及 UI 的实现应加载 `ui-ux-pro-max`。本迭代只补齐视觉、布局、组件和反馈，不改变业务规则。

## 2. 目标

在不改变业务状态机、Webhook、Job / Worker 模型、路由语义与按钮入队条件的前提下，对所有已登录业务页和登录页完成一次改版，达到：

1. **一眼可辨**：导航、面包屑、当前公司 / 仓库 / Issue、流程状态、错误与排队态都能立即识别。
2. **列表可扫**：表格有明确的主列 / 次要列；状态使用“文字 + 颜色 + 图标”徽章；空列表和“筛选无结果”分别有引导。
3. **详情可操作**：Issue 详情按“操作 → 摘要 → 正文 / 设计文档 → 任务日志”分层；主 CTA 不被 Worker / 任务信息淹没；日志等宽、可滚动、默认跟随最新。
4. **反馈完整**：flash、表单字段错误、贵重操作二次确认 modal、提交中禁用与 loading，全部符合现有界面契约。
5. **观感统一**：浅色运维台，产品名“GitHub 工作流”在壳层清晰；图标使用 Heroicons / Lucide 风格的内联 SVG，不用 emoji 当导航或状态。
6. **桌面优先、小屏不破版**：主内容 `max-w-7xl` 居中；宽表格在窄屏横向滚动；不新增移动端原生 App。

成功标准以第 13 节验收清单为准。

## 3. 非目标

- 不新做暗色主题、多主题切换或完整设计系统站点。
- 不修改 API 契约、数据库 schema、Inbox / Pipeline 逻辑、状态机字段和流转条件。
- 不新增、删除或改变任何页面路由、查询参数语义、按钮入队条件和 CSRF / JWT 行为。
- 不做完整 Markdown / GFM 渲染；Issue 正文和设计文档继续以安全源文 / `<pre>` 展示，避免 XSS。
- 不引入重前端框架（Vue / React / Alpine 等）；保持服务端模板 + 现有轮询脚本 + 少量原生 JS。
- 不替换 DaisyUI / Tailwind 技术栈；不引入 npm、前端构建或组件库打包。
- 不做移动端原生 App；不做图表统计大屏、表格列排序、筛选预设保存等新功能。
- 不修改基石入口或 `docs/architecture/design.md`；若实现中出现新的业务规则，应先更新基石，而不是写进本迭代。

## 4. 相对基石的增量声明

本迭代已阅读 [`docs/README.md`](../README.md) 与 [`docs/architecture/design.md`](../architecture/design.md)，基线结论如下。

### 4.1 保持不变

| 维度 | 结论 |
| --- | --- |
| 业务状态机 | `issue.status`、`codegen_phase`、`job.status`、`webhook_delivery.status`、`github_state` 全部不变 |
| 数据模型 | 不新增表、列、索引、迁移；不修改 Alembic |
| Webhook / Inbox | 验签、202、重试、failed 人工重试逻辑不变 |
| Worker / Pipeline | 单 Worker、双循环、worktree、代理调用、PR 创建逻辑不变 |
| 鉴权 | JWT、cookie、CSRF、`require_page_user` / `require_fragment_user` 不变 |
| 路由与查询参数 | URL、方法、参数名、默认值不变；`page`、`kind`、`status`、`github_state` 语义不变 |
| 按钮条件 | `actions_for` 的启用 / 禁用 / 链接条件不变；仅补展示字段 |
| 轮询接口 | `GET /issues/{id}/status-fragment` 的路径与鉴权不变；仅调整片段内容与前端消费方式 |
| 文案底线 | 错误、409、空状态、关闭 Issue 后无流程按钮等现有行为不回退 |

### 4.2 本迭代增量

| 增量 | 说明 |
| --- | --- |
| 视觉 token 与壳层 | 浅色运维台表面、字体、间距、焦点环、页脚、页头、面包屑、导航高亮 |
| 组件化 | 新增图标、徽章、空状态、分页、页头、动作按钮、确认 modal 等 Jinja 宏 / partial |
| 页面布局 | 第 9 节逐页改版；只调整信息层级与呈现，不改变字段来源和操作条件 |
| 只读上下文 | 为展示补少量只读数据：列表总数 / 分页、Worker 状态、投递仓库 `owner/repo` |
| 轮询体验 | 5 秒轮询、状态与日志分区更新、日志跟随最新、401 停止并提示 |
| 测试 | 新增 UI 冒烟测试与人工视觉 / 键盘检查；不改变现有业务测试断言 |

### 4.3 基石冲突处理

若实现过程中发现视觉需求与基石字段、按钮条件或反馈约定冲突，以基石为准；需要新增业务规则时，先更新 `docs/README.md` 或 `docs/architecture/design.md`，再继续本迭代。

## 5. 现状与差距

| 页面 | 现状 | 主要差距 |
| --- | --- | --- |
| 登录 `/login` | 单张卡片，字段和错误提示可用 | 缺少品牌感、流程说明、口令显示切换；错误态不够醒目 |
| 壳层 `base` | 顶栏 + 面包屑 + flash，主区 `max-w-7xl` | 导航高亮弱、无用户区层次、无页脚、无跳转主内容链接、面包屑样式普通 |
| 公司列表 `/` | 裸表：名称、仓库数、未结束 Issue | 无页头说明；无头像 / 描述；个人账号徽章弱；无空状态外引导；无分页控件 |
| 仓库列表 `/companies/{id}` | 裸表，操作使用 `btn-xs` | 路径“未填写”不醒目；开放 Issue 数不可点；同步操作不突出；无页头统计 |
| 仓库详情 `/repos/{id}` | 两张卡片，字段错误只在页顶 | GitHub 资料与本地配置分组弱；同步状态不清晰；字段错误缺少锚点与焦点；`origin_mismatch` 警告位存在但 GET 恒为 `False` |
| Issue 列表 | 自由文本状态筛选，默认徽章，操作 `btn-xs` | 筛选不像运维台；类型 / 状态无颜色语义；操作主次不分；筛选无结果与真空列表不区分；无分页 |
| Issue 详情 | 元数据 / 正文两卡，日志一卡，3 秒轮询 | 主 CTA 与任务状态混在一起；摘要不清晰；日志无跟随最新体验；错误与警告和内容混排 |
| Webhook 投递 | 原始状态码、仓库数字 id、窄表格 | 状态筛选不直观；仓库名不可读；错误摘要易撑破；筛选无结果无引导 |
| 设置 | 文字心跳 + 普通单选 | 心跳状态无徽章；代理选项缺少说明；当前选择不突出 |
| 404 | 普通卡片 | 缺少明确的 404 视觉与回首页引导层级 |

## 6. 方案：设计方向与视觉规范

第 6–11 节构成本迭代方案：先定视觉与组件，再落到全局壳、逐页布局和跨页交互；第 12–13 节分别说明影响面与验收。

### 6.1 定位

内部运维台 / SaaS admin，而不是营销落地页：

- 干净、专业、扁平，靠边框、留白和轻阴影建立层次。
- 不使用紫霓虹、过量 glassmorphism、渐变光斑、装饰性大插画。
- 强调“扫一眼判断进度与风险”：状态、错误、阻塞项优先于装饰。
- 登录页可以有克制的品牌表达，业务页保持高信息密度。

### 6.2 色彩与表面

继续使用 DaisyUI `corporate` 浅色主题，并在壳层补充少量 CSS 变量，避免页面各自写死颜色。

| Token | 值 | 用途 |
| --- | --- | --- |
| `--gw-bg` | `#F8FAFC` | 页面背景 |
| `--gw-surface` | `#FFFFFF` | 卡片、表格、顶栏 |
| `--gw-ink` | `#0F172A` | 主文字 |
| `--gw-muted` | `#475569` | 次要文字（保证正文对比度） |
| `--gw-line` | `#E2E8F0` | 边框、分隔线 |
| `--gw-accent` | `#0369A1` | 主操作、链接、焦点 |
| `--gw-accent-soft` | `#E0F2FE` | 选中态、信息提示底 |
| `--gw-success` | `#059669` | 成功、已建 PR |
| `--gw-warning` | `#D97706` | 等待、待重试、无心跳 |
| `--gw-danger` | `#DC2626` | 失败、错误 |
| `--gw-info` | `#0284C7` | 进行中 |

约定：

- 状态徽章始终是“文字 + 颜色”，颜色只做辅助，不单独表达状态。
- 卡片使用 `bg-white border border-slate-200 rounded-xl shadow-sm`，不使用大面积重阴影。
- 页面背景与卡片表面要有轻微层次；表格不使用斑马纹，用行悬停和分隔线建立可扫性。
- 任务日志可以采用深色终端块（`slate-950` 背景），它只是日志组件，不构成暗色主题；最终取舍见第 15 节。
- 不引入新的颜色语义；警告 / 危险 / 成功 / 信息四类与基石一致。

### 6.3 字体与排版

| 用途 | 字体 |
| --- | --- |
| 界面正文 | `Source Sans 3`，回退 `system-ui, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif` |
| 路径、分支、SHA、日志、投递 id | `JetBrains Mono`，回退 `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` |

- 字体通过 `<link>` 引入，使用 `display=swap` 和 `preconnect`；不打包字体文件。
- 中文继续依赖系统黑体回退，不额外引入中文字体包。
- 页面标题 `text-2xl font-semibold tracking-tight`；页头说明 `text-sm text-slate-600`；正文 `text-sm leading-6`。
- 数字列使用 `tabular-nums text-right`；长路径、SHA、日志使用等宽并允许 `break-all` / `whitespace-pre-wrap`。
- 时间统一显示为 `YYYY-MM-DD HH:MM`，并标注 `UTC`；`title` 保留完整 ISO 时间。实现可用 Jinja 宏格式化，不引入新依赖。

### 6.4 密度、圆角与间距

- 主内容：`max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6`。
- 卡片内边距：`p-5`；列表工具条与页头间距 `mb-4` / `mb-6`。
- 表格行高舒适：单元格 `py-3`，操作列按钮 `btn-sm`，不再使用 `btn-xs`。
- 圆角：卡片 `rounded-xl`；徽章、按钮沿用 DaisyUI。
- 图标：默认 `h-4 w-4`；卡片标题 `h-5 w-5`；空状态 `h-6 w-6`。

### 6.5 图标

- 使用 Heroicons / Lucide 风格的 **内联 SVG**，通过 `macros/icons.html` 统一输出。
- 图标只做辅助：`aria-hidden="true"`；纯图标按钮必须有 `aria-label`。
- 禁止用 emoji 充当导航、状态或操作图标。
- 建议图标集：`building`（公司）、`repo`（仓库）、`issue`（Issue）、`webhook`（投递）、`settings`、`user`、`logout`、`external-link`、`chevron-right`、`check`、`alert-triangle`、`info`、`clock`、`refresh`、`loader`、`terminal`、`branch`、`pr`、`inbox`、`arrow-left`、`arrow-right`、`x`。

### 6.6 动效

- 按钮、告警、modal 进出 150–300ms；不做持续动画。
- 保留 `prefers-reduced-motion: reduce`：关闭 transition / animation，轮询替换不产生滚动动画。
- loading 使用 DaisyUI `loading loading-spinner`；在 reduced motion 下仍可显示静态状态文字，不依赖旋转。
- 轮询日志默认**瞬时**滚到底，不使用 smooth scroll。

## 7. 模板组织与可复用组件

### 7.1 文件结构

```text
app/templates/
├── base.html                    # 已登录壳层
├── login.html                   # 独立登录页
├── 404.html
├── companies.html
├── repos.html
├── repo.html
├── issues.html
├── issue_detail.html
├── deliveries.html
├── settings.html
├── partials/
│   ├── head_assets.html         # CDN、字体、Tailwind 配置、CSS 变量
│   ├── flash.html               # 成功 / 错误提示
│   └── issue_live.html          # 轮询片段（状态 + 日志尾部）
└── macros/
    ├── icons.html               # 内联 SVG
    └── ui.html                  # 徽章、页头、空状态、分页、动作按钮、modal
```

说明：

- 不重构各路由现有的 `Jinja2Templates` 实例；宏通过 `{% from "macros/ui.html" import ... %}` 引用即可。
- `base.html` 与 `login.html` 共用 `partials/head_assets.html`，避免 CDN / 字体 / CSS 变量重复。
- 不新增静态文件路由；`head_assets.html` 内联少量原生 CSS。**内联样式不使用 `@apply`**，因为 Tailwind Play CDN 不在构建期处理它。
- 不引入前端构建产物；所有 JS 保持为页面底部的小段原生脚本。

### 7.2 宏与 partial 清单

| 名称 | 位置 | 签名 / 用途 |
| --- | --- | --- |
| `icon` | `macros/icons.html` | `icon(name, class='h-4 w-4')`，输出内联 SVG |
| `page_header` | `macros/ui.html` | `{% call page_header(title, description='', eyebrow='') %}动作区{% endcall %}`；统一页头 |
| `badge` | `macros/ui.html` | `badge(tone, text, icon_name=None, outline=False)`；统一文字 + 颜色 + 图标 |
| `issue_status_badge` | `macros/ui.html` | 按 `issue.status` 输出中文状态徽章 |
| `kind_badge` | `macros/ui.html` | 按 `issue.kind` 输出类型徽章 |
| `github_state_badge` | `macros/ui.html` | 开放 / 已关闭 |
| `job_badge` / `delivery_badge` / `worker_badge` | `macros/ui.html` | 任务、投递、Worker 状态徽章 |
| `phase_label` | `macros/ui.html` | `codegen_phase` 中文文案 |
| `empty_state` | `macros/ui.html` | `empty_state(title, description, icon_name, href=None, link_label=None)`；空列表 / 筛选无结果 |
| `pagination` | `macros/ui.html` | `pagination(page, has_prev, has_next, prev_url, next_url)`；隐藏单页分页 |
| `issue_actions` | `macros/ui.html` | `issue_actions(actions, csrf_token)`；统一链接 / 文本 / POST 按钮、主次样式、确认 modal |
| `flash` | `partials/flash.html` | 渲染 `flash` 查询参数与 `msg`，成功自动隐藏、错误保留 |
| `issue_live` | `partials/issue_live.html` | 轮询片段，包含状态区、任务区、日志尾部与 `data-done` |

宏内部把展示色调映射到 DaisyUI 类：`neutral → badge-ghost`、`info → badge-info`、`success → badge-success`、`warning → badge-warning`、`danger → badge-error`；动作按钮的 `warning` variant 映射为 `btn-warning btn-outline`，`primary` 映射为 `btn-primary`，其余为 `btn-outline` / `btn-ghost`。

`issue_actions` 继续消费 `app/services/actions.py` 的 `Action` 列表，不重新判断按钮条件。为表达主次，`Action` 只补两个**纯展示字段**：

```python
@dataclass
class Action:
    kind: str          # button | link | text
    label: str
    href: str | None = None
    form_action: str | None = None
    confirm: str | None = None
    disabled: bool = False
    variant: str = "secondary"   # primary | secondary | warning | ghost
    icon: str | None = None
```

`actions_for` 中所有 `if / elif` 条件保持不变，只在已有分支上补 `variant` / `icon`。模板宏负责渲染；即使 `variant` 标了多个 `primary`，宏也只保留第一个为 `btn-primary`，其余降级为 `btn-outline`，保证“一行最多一个 primary”。

### 7.3 状态语义映射

#### Issue 流程状态

| 值 | 文案 | 色调 | 图标 |
| --- | --- | --- | --- |
| `pending_classify` | 待分类 | neutral | `help-circle` |
| `recorded` | 已收录 | info | `file-plus` |
| `drafting` | 编写中 | info | `loader` |
| `pending_codegen` | 待生成 | warning | `clock` |
| `generating` | 生成中 | info | `loader` |
| `generated` | 已生成 | success | `check-circle` |
| `pr_opened` | 已建PR | success | `pr` |
| `failed` | 失败 | danger | `alert-triangle` |
| `support_open` | 待处理 | neutral | `inbox` |

#### 类型、GitHub 状态、任务、投递、Worker

| 场景 | 值 | 文案 | 色调 | 图标 |
| --- | --- | --- | --- | --- |
| 类型 | `feature` | 功能迭代 | info | `code` |
| 类型 | `support` | 人工介入 | warning | `life-buoy` |
| 类型 | `pending` | 待分类 | neutral | `help-circle` |
| GitHub | `open` | 开放 | success | `circle-dot` |
| GitHub | `closed` | 已关闭 | neutral | `lock` |
| Job | `queued` | 排队中 | warning | `clock` |
| Job | `running` | 执行中 | info | `loader` |
| Job | `succeeded` | 成功 | success | `check` |
| Job | `failed` | 失败 | danger | `x` |
| Job | `cancelled` | 已取消 | neutral | `slash` |
| 投递 | `queued` | 排队中 | warning | `clock` |
| 投递 | `running` | 处理中 | info | `loader` |
| 投递 | `retry` | 待重试 | warning | `rotate` |
| 投递 | `succeeded` | 成功 | success | `check` |
| 投递 | `ignored` | 已忽略 | neutral | `minus` |
| 投递 | `failed` | 失败 | danger | `alert-triangle` |
| Worker | `idle` | Worker 空闲 | success | `pause` |
| Worker | `running` | 执行中 | info | `loader` |
| Worker | `stale` / `missing` | 无心跳 | warning | `alert-triangle` |

#### 代码生成阶段

| `codegen_phase` | 文案 |
| --- | --- |
| `none` | 未开始 |
| `worktree_ready` | 工作区就绪 |
| `doc_committed` | 文档已提交 |
| `agent_running` | 代理执行中 |
| `changes_validated` | 改动已校验 |
| `code_committed` | 代码已提交 |
| `pushed` | 已推送 |
| `pr_opened` | PR 已创建 |

阶段只作为任务卡片中的一行“阶段：代理执行中”，不做完整时间线 / 进度条，避免把内部字段包装成新的业务语义。

### 7.4 贵重操作确认 modal

所有贵重操作继续由 `Action.confirm` 触发确认，但不再使用 `window.confirm()`。统一使用一个 DaisyUI `modal`（原生 `<dialog>`）：

```html
<dialog id="gw-confirm" class="modal" aria-labelledby="gw-confirm-title">
  <div class="modal-box">
    <h3 id="gw-confirm-title" class="text-lg font-semibold"></h3>
    <p id="gw-confirm-body" class="py-3 text-sm text-slate-600"></p>
    <div class="modal-action">
      <button type="button" class="btn btn-ghost" data-gw-cancel>取消</button>
      <button type="button" class="btn btn-primary" data-gw-ok>确认执行</button>
    </div>
  </div>
  <form method="dialog" class="modal-backdrop"><button>关闭</button></form>
</dialog>
```

动作按钮的渲染约定：

- 有 `confirm` 的 POST 表单：主按钮 `type="button"`，带 `data-gw-confirm`、`data-confirm-title`、`data-confirm-body`；表单内保留 CSRF 隐藏字段。
- 点击后打开 modal；确认时给表单标记“已确认”，调用 `form.requestSubmit()`；提交事件中禁用按钮并加 loading。
- 取消、Esc、点击 backdrop 一律关闭 modal，不提交，焦点回到触发按钮。
- 无 `confirm` 的分类按钮直接提交；普通保存 / 同步 / 投递重试同样只做提交中禁用，不弹 modal。
- 无 JS 时贵重操作按钮不提交（`type="button"` 不会触发表单），并在动作区显示 `<noscript>` 说明：“确认弹窗需要启用 JavaScript，贵重操作暂不可用。” 贵重表单不渲染 `type="submit"` 按钮，只由 JS 在确认后调用 `requestSubmit()`，避免无 JS 时按 Enter 触发隐式提交。普通浏览、筛选、保存表单不依赖 JS。

确认文案（`Action.confirm` 可保持现有语义，展示时补全）：

| 动作 | 标题 | 正文要点 |
| --- | --- | --- |
| 编写文档 | 编写设计文档 | 将调用全站配置的代理编写设计文档并写入库内；不会提交或推送。 |
| 重新编写文档 | 重新编写设计文档 | 将调用代理重写，并覆盖库内文档正文；迭代号和路径不变。 |
| 生成代码 | 生成代码并创建 PR | 将调用代理生成代码，随后由系统提交、推送并创建 Pull Request。 |
| 重试（动工作区） | 重试失败步骤 | 将重试失败步骤，可能重置系统隔离工作区；不会改动登记的本地仓库。 |
| 重试创建 PR | 重试创建 PR | 将调用 GitHub API 重新创建 PR，不重新生成代码。 |

### 7.5 Flash 与表单反馈

- `partials/flash.html` 读取现有 `flash` / `msg` 查询参数，不新增参数。
- 成功：`alert-success` + `role="status"` + 成功图标 + 关闭按钮；5 秒后自动隐藏，不挡操作。
- 错误：`alert-error` + `role="alert"` + 错误图标；**不自动隐藏**，用户可手动关闭。
- 表单字段错误：字段下方红色文案 + `aria-invalid="true"` + `aria-describedby`；页顶 `alert-error` 摘要；第一个错误字段加 `autofocus`。
- 保存 / 同步 / 登录 / 设置保存：提交时禁用提交按钮并显示 spinner，`aria-busy="true"`；不改变 POST 语义。
- 409 / 业务冲突继续由服务端 303 回来源页并带 `flash=error`；页面只负责把原因完整、可读地展示出来。

### 7.6 分页与筛选 URL

- 保持每页 50 行与 `page` 参数不变。
- 列表路由在上下文中提供统一结构：
  ```python
  pagination = {
      "page": page,
      "has_prev": page > 1,
      "has_next": page * PAGE_SIZE < total,
      "prev_url": "...",
      "next_url": "...",
  }
  ```
- `pagination` 宏渲染“上一页 / 第 n 页 / 下一页”；只有一页时整块隐藏。
- Issue 列表的 `prev_url` / `next_url` 必须保留 `kind`、`status`、`github_state`；投递列表保留 `status`。
- 筛选表单使用 GET，不包含 `page` 字段，切换筛选自然回到第 1 页。
- “清除筛选”回到该页默认值：Issue 列表为 `?github_state=open`，投递列表为“全部”。

### 7.7 空状态

统一使用 `empty_state`：

- 图标（SVG）+ 标题一句 + 说明一句 + 可选一个引导链接。
- 真空列表与“筛选无结果”分开：
  - 真空列表：说明数据会如何出现，例如“配置 Webhook 后会自动出现”。
  - 筛选无结果：标题“没有符合筛选的 Issue / 投递”，提供“清除筛选”链接。
- 空状态不使用营销文案，不使用 emoji。

### 7.8 安全与转义

- Issue 正文、设计文档、`last_error`、`sync_error`、投递 `last_error`、日志继续由 Jinja 自动转义；禁止 `|safe`。
- 日志更新使用 `textContent`，不把日志拼进 `innerHTML`。
- 轮询片段由服务端 Jinja 渲染，所有动态值转义；前端只替换约定节点。
- 外链统一 `target="_blank" rel="noopener"`；GitHub 头像 `loading="lazy"`、`referrerpolicy="no-referrer"`、`alt=""`，加载失败回退姓名首字。
- 不在 `data-*` 属性之外拼接确认文案；确认文案由 Jinja 自动转义。

## 8. 全局壳 `base.html`

### 8.1 结构

```text
<body>
  跳转主内容链接（sr-only，聚焦可见）
  <header> 顶栏：品牌 / 主导航 / 用户区 </header>
  <main id="main">
    面包屑（≥2 级时）
    {% block page_header %}{% endblock %}
    flash
    {% block content %}
  </main>
  <footer> 可选页脚 </footer>
  确认 modal + flash 脚本 + 页面脚本
</body>
```

### 8.2 顶栏

- 左侧：内联 SVG 品牌标记 + 产品名“GitHub 工作流”，链到 `/`；可加一行小字“内部运维台”（不抢主标题）。
- 中间：`公司`（`/`）、`Webhook 投递`（`/deliveries`）、`设置`（`/settings`）。
  - 当前项使用 `aria-current="page"`、浅色底 + 主色文字 + 底部指示条；不再只用 `btn-active`。
  - 小屏导航横向滚动，不折叠成需要 JS 的汉堡菜单；顶栏允许换行。
- 右侧：用户首字头像 + 用户名 + `退出`（POST `/logout`，带 CSRF）。退出按钮使用 `btn-ghost btn-sm`，不抢主 CTA。
- 顶栏 `sticky top-0 z-30`，背景 `bg-white/95 backdrop-blur` 或纯白；底部 `border-b`。
- 顶栏高度变化时给主内容 `scroll-margin-top`，避免锚点被遮。

### 8.3 面包屑

- 使用统一图标 `chevron-right` 分隔；首页图标可链到 `/`。
- 最后一项为当前页，不可点击，`aria-current="page"`。
- 长 Issue 标题在窄屏截断，`title` 保留全文。
- 面包屑与页头之间留 `mb-4`。

### 8.4 页头

每页使用 `page_header` 宏，并放在 `base.html` 的 `{% block page_header %}` 中，确保页头位于 flash 之上：

- 可选 eyebrow：`公司` / `仓库` / `Issue` / `系统`。
- 主标题：当前对象名或页面名。
- 一行说明：告诉操作员“这页能做什么 / 数据从哪来”，不超过一到两句。
- 右侧动作区：最多一个主 CTA；其余为 outline / ghost。
- 页头下方才是 flash 与内容，符合基石“主区顶部标题 + 说明，其下 flash 告警区”的顺序。

### 8.5 页脚

- 顶部 `border-t`，内容弱化：产品名 + “内部运维台”；可显示版本 / 环境名。
- 无营销文案、无社交链接、无大段说明。
- 环境名 / 版本来源尚未定义，见第 15 节；未确认时只显示静态产品名。

### 8.6 移动端

- 顶栏品牌、导航、用户区允许换行；导航 `overflow-x-auto whitespace-nowrap`。
- 页头动作区在 `sm` 以下换到标题下方，按钮 `flex-wrap`。
- 卡片内边距从 `p-5` 降到 `p-4`；表格保持横向滚动，不压缩列。
- 不隐藏关键操作；宁可换行，不裁切。

## 9. 页面改版要点

### 9.1 登录 `/login`

**布局**

- 桌面 `lg:grid lg:grid-cols-2`：
  - 左侧品牌区：产品名、简短定位“GitHub Issue → 设计文档 → 代码 → PR”、流程小标签（公司 / 仓库 / Issue / 文档 / 代码 / PR）、一句“仅限授权账号”。
  - 右侧登录卡片：`max-w-md`，白底、圆角、轻阴影。
- 小屏单列：品牌区压缩为顶部品牌行，登录卡片占满宽度。
- 背景保持浅色，不使用暗色默认。

**关键元素**

- 用户名、口令均有可见 `<label>`；口令提供显示 / 隐藏按钮（`aria-label="显示口令"` / `"隐藏口令"`，图标切换）。
- 错误使用 `alert-error` + `role="alert"`；口令错误时用户名输入框 `autofocus`，并设置 `aria-invalid` 与 `aria-describedby`。
- 提交按钮全宽 `btn-primary`，提交中禁用 + spinner。
- 已登录访问 `/login` 仍直接 303 到公司列表，不做额外处理。

**验收点**

- 错误口令 / 停用账号仍返回 200 并展示表单错误，不返回 JSON。
- 登录后 303 到 `/`，cookie 行为不变。
- 键盘可完成登录；口令显示切换不提交表单。

### 9.2 公司列表 `/`

**布局**

- 页头：标题“公司”，说明“按 GitHub 所有者聚合的仓库与 Issue 概览。”；右侧无新建入口（保持非目标）。
- 说明中补一句“未结束 = 功能迭代尚未建 PR，或人工介入待处理，且 GitHub 仍为 open。”，避免误读计数。
- 表格卡片：公司 / 仓库数 / 未结束 Issue。

**关键元素**

- 公司单元格：
  - GitHub 头像（32px 圆形；失败回退姓名首字，底色 `slate-100`）。
  - 公司名链接为主列，`font-medium`。
  - 描述作为次要行，`text-xs text-slate-500 line-clamp-1`；无描述不占位。
  - `account_type == 'User'` 显示 “个人账号” 徽章。
  - `company.sync_error` 存在时显示 `badge-error` “同步失败”，`title` 放错误全文；不新增查询。
- 计数列右对齐、等宽数字、`tabular-nums`；表头保持“仓库数”“未结束 Issue”。
- 行悬停浅色底；公司名链接可使用 `link-hover`，不加下划线常驻。
- 空状态：标题“还没有公司”，说明“收到 GitHub Issue 通知后，公司和仓库会自动出现。”，链接“查看 Webhook 投递”到 `/deliveries`。
- 分页：用 `count_companies` 补 `total` / `has_next`，渲染统一分页条。

**验收点**

- 个人账号徽章、同步失败徽章仍来自现有字段。
- 空列表与有数据列表都不出现横向溢出；分页 URL 保留 `page`。
- 公司名仍链到 `/companies/{id}`。

### 9.3 仓库列表 `/companies/{id}`

**布局**

- 面包屑：公司 → 仓库。
- 页头：eyebrow“公司”，标题为公司名，说明“该所有者下的仓库与同步状态。”。
- 页头右侧显示只读统计“共 N 个仓库”（复用 `repo_count`）；开放 Issue 数放在每一行，避免与公司列表的“未结束 Issue”定义混用。
- 表格卡片：仓库 / 默认分支 / 服务器路径 / 开放 Issue / 操作。

**关键元素**

- 仓库单元格：
  - `owner/repo` 主链接到本系统仓库页，`font-medium`、等宽。
  - GitHub 外链作为次要图标链接（`external-link`，`aria-label="在 GitHub 打开"`）。
- 默认分支：等宽小徽章或 `code` 样式。
- 服务器路径：
  - 已填写：等宽 `text-xs`，单行截断，`title` 全文。
  - 未填写：`badge-warning` “未填写” + “去填写”链接到仓库详情页；这是本页最需要被看见的阻塞项。
- 开放 Issue：数字链接到 `/repos/{id}/issues?github_state=open`，右对齐；`aria-label="查看开放 Issue"`。
- 操作：
  - “Issue” 为 `btn-sm btn-primary`（查看是主操作）。
  - “重新同步” 为 `btn-sm btn-outline` + refresh 图标；POST 带 CSRF，提交中禁用 + spinner。
  - 一行最多一个 primary；不使用 `btn-xs`。
- 空状态：标题“该公司下还没有仓库”，说明“收到该公司的 Issue Webhook 后会自动出现。”。
- 分页：用 `repo_count` 补 `total` / `has_next`。

**验收点**

- 路径未填写时仍能看到“去填写”入口（可复用“填写项目路径”文案）。
- 重新同步成功 / 失败仍走现有 flash；失败不清本地路径。
- 开放 Issue 数仍来自现有统计，不改变定义。

### 9.4 仓库详情 `/repos/{id}`

**布局**

- 面包屑：公司 → `owner/repo`。
- 页头：标题 `owner/repo`（等宽或半粗），右侧“在 GitHub 打开”（outline）与“查看 Issue”（primary）。
- 页头徽章：私有 / 公开、默认分支、最近同步时间。
- 顶部告警区（按顺序）：
  1. `origin_mismatch`：`alert-warning`“origin 与 GitHub 仓库名不一致，请先更新服务器 remote 或改填路径。”
  2. `repo.sync_error`：`alert-error`“同步错误：…”，错误全文可换行。
  3. `form_disabled`：`alert-info`“有进行中的任务，暂不可改路径。”
- 主体 `grid lg:grid-cols-3 gap-6`：
  - 左侧 `lg:col-span-2`：GitHub 资料卡片。
  - 右侧 `lg:col-span-1`：本地配置表单卡片。
  - 小屏按“本地配置 → GitHub 资料”堆叠，保证路径填写不被长资料压到下方。

**GitHub 资料卡片**

- 描述；无描述显示“无描述”弱化文字。
- 定义列表：完整名称、默认分支、是否私有、最近同步、GitHub 链接。
- 卡片头部右侧放“重新同步”按钮（POST，CSRF，提交中禁用）。
- `sync_error` 已在页顶展示，卡片内可再显示一个小警告图标 + 简要说明，不重复长文。

**本地配置卡片**

- 表单字段：
  - 服务器项目路径：可见 label、帮助文字“须为已 clone 的 git 顶层绝对路径；origin 必须匹配 `owner/repo`。”
  - 文档目录：帮助文字“相对路径，默认 `docs`；基石入口为 `{doc_dir}/README.md`。”
- 校验错误：
  - 字段下方红色文案 + `aria-invalid` + `aria-describedby`；
  - 页顶 `alert-error` 摘要“请修正下列字段后重试。”；
  - 第一个错误字段 `autofocus`。
- 表单有进行中任务时：字段与保存按钮 `disabled`，并保留说明；不要只靠颜色表达禁用。
- 保存按钮 `btn-primary`，提交中禁用 + spinner；成功 303 回本页并 flash“已保存”。
- 不新增“删除仓库”“修改 GitHub 名称”等入口。

**验收点**

- 保存路径 / 文档目录的校验与 303 行为不变。
- 校验失败停在本页、字段错误可见、焦点落在第一个错误字段。
- 进行中任务时不能改路径；`origin_mismatch` 警告位保留（是否补只读检查见第 15 节）。

### 9.5 Issue 列表 `/repos/{id}/issues`

**布局**

- 面包屑：公司 → 仓库 → Issue。
- 页头：eyebrow“仓库”，标题“Issue”，说明“按编号倒序；筛选条件会写入 URL。”。
- 工具条一张卡片：类型 / 流程状态 / GitHub 状态 + “应用筛选” + “清除筛选”。
- 表格卡片，列：编号 / 标题 / 类型 / 状态 / 更新 / 操作。

**筛选工具条**

- 类型：`全部 / 功能迭代 / 人工介入 / 待分类`。
- 流程状态：使用固定下拉，选项来自现有 `STATUS_LABELS`（见 7.3），不再使用自由文本输入；参数名仍为 `status`，值不变。
- GitHub 状态：`open` / `closed` / `全部`，默认 `open`。
- 选择变化在 JS 可用时自动提交；保留“应用筛选”按钮作为无 JS 回退。
- “清除筛选”回到 `?github_state=open`，并重置 `page`。
- 工具条在窄屏换行，控件 `min-w-0`，不撑破。

**表格**

- 编号：等宽 `#123` 链到详情；GitHub 外链为图标链接（`aria-label="在 GitHub 打开 Issue #123"`）。
- 标题：主列 `font-medium`，最多两行截断；下方可显示 `@author_login` 作为次要信息（现有字段，不新增查询）。
- 类型 / 状态：使用 7.3 的徽章；状态不只靠颜色。
- 更新：`YYYY-MM-DD HH:MM UTC`，`title` 完整时间；等宽、`text-xs`。
- 操作列：
  - 右对齐，`flex flex-wrap justify-end gap-1.5`。
  - 主操作（编写文档 / 生成代码 / 重试 / 查看进度 / 查看 PR）为 `btn-sm btn-primary`；
  - 次要操作（重新编写文档、分类、填写项目路径、配置代理）为 `btn-sm btn-outline`；
  - “排队中”为禁用态 `btn-sm` + clock 图标 + `aria-disabled="true"`，不改变 Issue 状态；
  - 分类按钮无确认，直接 POST；贵重操作走 7.4 modal。
- 行悬停浅色底；表格 `overflow-x-auto`，窄屏横向滚动，不压缩操作列。
- 筛选无结果：`empty_state`“没有符合筛选的 Issue” + “清除筛选”；真空列表：按现有文案说明“收到 Webhook 后将出现在这里”，人工介入筛选时补充“这一类本期只收录”。
- 分页：用 `count_for_repo` 补 `total` / `has_next`，URL 保留三个筛选参数。

**验收点**

- 按钮启用条件与 `actions_for` 完全一致；关闭 Issue 只保留已有“查看 PR”。
- 切换筛选重置 `page=1`；从详情返回列表可用浏览器后退。
- “排队中”仍禁用重复按钮，且不显示为可点击的主操作。

### 9.6 Issue 详情 `/issues/{id}`

**布局顺序**

1. 面包屑：公司 → 仓库 → `#编号 标题`。
2. 页头：`#编号` + 标题（可换行），右侧“在 GitHub 打开”。
3. 告警区：基石缺失、文档过期、标签不一致、`last_error`。所有警告保留现有文案与触发条件。
4. 操作条：当前 `actions`，主 CTA 靠右；**位于摘要和正文之前**，避免被 Worker / 任务信息淹没。
5. 摘要条：类型 / 流程状态 / GitHub 状态 / 作者 / 更新时间 / 迭代号 / 分支 / PR。
6. 主内容两栏（`xl:grid-cols-3`）：
   - 左 `xl:col-span-2`：Issue 正文卡片、设计文档卡片。
   - 右 `xl:col-span-1`：任务与 Worker 卡片。
7. 全宽：任务日志卡片。

**摘要条**

- 卡片内 `grid grid-cols-2 md:grid-cols-4 gap-4`。
- 每项：小标签 + 值；状态值用徽章。
- 字段：
  - 类型：`kind_badge`。
  - 流程状态：`issue_status_badge`，容器 `aria-live="polite"`。
  - GitHub：`github_state_badge` + 外链。
  - 作者：`@author_login`。
  - 更新：`github_updated_at or updated_at`，UTC。
  - 迭代：有 `iteration_no` 时显示 `v0001` 样式，等宽。
  - 分支：`branch_name`，等宽；无则“—”。
  - PR：有 `pr_url` 时外链“查看 PR”；无则“—”。
- 摘要条不放大段错误；错误在告警区或任务卡片。

**操作条**

- 使用 `issue_actions(actions, csrf_token)`。
- 主 CTA 为 `btn-primary`；重新编写文档、填写项目路径、配置代理等为 outline；`查看 PR` 是终点操作，作为唯一操作时保留 primary 样式。
- 所有贵重操作确认文案见 7.4；确认按钮提交中禁用。
- 无操作时显示弱化说明“当前状态没有可执行的流程操作。”，不伪造按钮。

**Issue 正文卡片**

- 标题区：`Issue 正文` + 作者 / 更新时间次要信息。
- 正文用 `<pre class="whitespace-pre-wrap break-words font-sans text-sm leading-6">{{ issue.body }}</pre>`。
- 正文为空显示“该 Issue 没有正文。”
- 不做 Markdown / GFM 渲染，不把正文插入 `innerHTML`。

**设计文档卡片**

- 仅在 `issue.design_doc_path` 存在时展示；标题区显示“设计文档”+ 等宽路径 + 迭代号徽章。
- 全文使用 `<pre class="whitespace-pre-wrap break-words font-mono text-xs ...">`，最大高度约 `32rem`，内部滚动。
- 不渲染 Markdown；不提供“在 GitHub 打开”（文档在生成代码分支上，避免承诺不存在的默认分支链接）。
- 无设计文档时不显示空卡片；由状态和任务卡片表达“还没有文档”。

**任务与 Worker 卡片**

- “最近任务”：`latest_job.action` 中文标签 + `job_badge`；`started_at` / `finished_at`；`exit_code`（有值时）；`codegen_phase` 中文阶段。
- “Worker”：显示 `worker_status`：
  - 空闲：“Worker 空闲”；
  - 执行中且是本 Issue：“执行中（本 Issue）”；
  - 执行中且是其他 Issue：“执行中（其他 Issue）”；
  - 无心跳：“无心跳，任务可能不会执行”。
- Worker 心跳时间与设置页一致，弱化展示。
- 不展示完整宿主机路径；日志路径等敏感信息留在设置页现有展示。

**任务日志卡片**

- 标题区：`最新任务日志` + `job #id` + action 中文 + `job_badge`；轮询中显示“自动刷新中”+ spinner（reduced motion 下为静态文字）。
- 日志容器：深色终端块（`bg-slate-950 text-slate-100`）或浅灰等宽块（见第 15 节），`font-mono text-xs leading-relaxed`，`max-h-96 overflow-auto`，`whitespace-pre-wrap break-words`。
- 无任务 / 无日志：`empty_state` 或弱化“（暂无日志）”；日志路径不可用时显示 warning“日志路径不可用”。
- 默认跟随最新：更新前若用户位于底部附近，更新后滚到底；若用户已上滚阅读，保持位置并显示“有新日志，回到底部”按钮。
- 日志容器 `aria-label="任务日志"`，不设置 `aria-live`，避免每次轮询朗读整段日志；状态区使用 `aria-live="polite"`。

**轮询行为**

- 仅在 `issue.status in {'drafting', 'generating'}` 时启动；间隔 **5 秒**（与基石界面契约一致）。
- 请求保持现有端点、`credentials: same-origin`、`Accept: text/html`、`X-Requested-With: fetch`、`redirect: manual`。
- 收到 401 / 3xx / 页面像登录页时：停止轮询，在页面内显示 `alert-error`“会话已失效，请重新登录”并给登录链接；不再使用 `alert()`。
- 片段契约见 10.3：根节点 `data-done="0|1"`；`0` 表示继续，`1` 表示停止。
- 状态区更新后不抢焦点；日志使用 `textContent` 更新。
- 任务结束（`data-done=1`）后停止定时器，状态徽章与日志保留最终结果。

**验收点**

- `drafting` / `generating` 时日志仍轮询更新；结束后停止。
- 未登录访问片段仍返回 401，不泄露日志。
- 基石缺失警告保留且不阻断编写文档；过期文档、标签不一致警告保留。
- 关闭 Issue 后只保留已有 PR 链接，不出现流程按钮。

### 9.7 Webhook 投递 `/deliveries`

**布局**

- 页头：标题“Webhook 投递”，说明“GitHub 不会自动重投失败的 Webhook；失败投递可人工重试。”。
- 筛选：一行状态胶囊，保留当前页面已有的筛选值（`all / queued / running / retry / failed / succeeded / ignored`），文案中文化为“全部 / 排队中 / 处理中 / 待重试 / 失败 / 成功 / 已忽略”；链接写入 URL，当前项 `aria-current="page"`；小屏横向滚动。不新增其他状态值。
- 表格卡片：Delivery / 事件动作 / 仓库 / 状态 / 尝试 / 下次重试 / 收到时间 / 错误 / 操作。

**表格**

- Delivery：等宽，显示前 10 位 + `…`，`title` 全文；窄屏不换行。
- 事件动作：`issues · opened` 形式；`event` 与 `action` 分开展示或合并，`action` 为空显示“—”。
- 仓库：优先显示 `owner/repo`（由 `repository_id` 批量只读查询 `repository.github_repo_id` → `github_full_name`）；查不到显示 GitHub id（等宽），不显示完整 payload。
- 状态：7.3 的投递徽章。
- 尝试次数：右对齐数字。
- 下次重试：仅 `retry` 有意义，显示 UTC 时间；其他显示“—”。
- 收到时间：UTC 时间，等宽 `text-xs`。
- 错误：`line-clamp-2 break-words`，`max-w-[20rem]`，`title` 放全文；不允许撑破表格。错误为空显示“—”。
- 操作：仅 `failed` 行显示“重试投递”`btn-sm btn-outline` + refresh 图标；POST 带 CSRF，提交中禁用；成功 / 失败走现有 flash。
- 空状态：
  - 真空：标题“还没有投递”，说明“Webhook 配置好并收到事件后会出现在这里。”
  - 筛选无结果：标题“没有符合筛选的投递”，链接“清除筛选”。
- 分页保留 `status` 参数。

**验收点**

- 仅 failed 行可重试；重试后仍回到列表并 flash“已重新排队”。
- 状态筛选默认“全部”；`status` 参数语义不变。
- 长错误不撑破布局；不展示完整 payload。

### 9.8 设置 `/settings`

**布局**

- 页头：标题“设置”，说明“全站代理只在这里选择；修改立即对之后的任务生效。”。
- 主体 `grid lg:grid-cols-3 gap-6`：
  - 左 `lg:col-span-2`：代理选择卡片。
  - 右 `lg:col-span-1`：Worker 心跳卡片。
- 顶部未选择代理时 `alert-warning`“尚未选择代理。编写文档与生成代码前必须配置。”

**代理选择卡片**

- `fieldset` + `legend`“全站代理”。
- 两个单选卡片：
  - `opencode`：说明“使用 `opencode run` 调用”。
  - `claude`：说明“使用 `claude -p` 调用”。
  - 当前选中项用 `border-primary bg-sky-50` 和“当前生效”徽章突出；未选中项白底。
- 单选保留可见 label，radio 可键盘操作；第一个 `required`，未选择时浏览器校验。
- 表单说明“所有仓库共用这一选择；已开始的任务继续使用任务行上记录的代理。”
- 保存按钮 `btn-primary`，提交中禁用 + spinner；成功 303 回本页并 flash“已保存”。
- 不提供密钥编辑、口令修改、Worker 重启按钮。

**Worker 心跳卡片**

- 状态徽章：`idle` / `running` / `stale` / `missing`，文案与 7.3 一致；`running` 显示 `job #id / issue #id`。
- “最近心跳”：`worker_updated_at`，UTC；`missing` / `stale` 时显示“—”。
- 心跳文件路径：等宽、`break-all`、弱化展示（沿用现有 `worker_heartbeat_path`）。
- `stale` / `missing` 时补一句 `alert-warning`“Worker 可能未启动或已停止；任务不会执行。”，不提供重启动作。
- 卡片不轮询；刷新页面获取最新状态即可（本迭代不新增自动刷新）。

**验收点**

- 空闲 / 执行中 / 无心跳三种状态仍能展示。
- 代理保存仍写入 `config.yaml`，非法值仍 flash 错误。
- 未选择代理时警告仍在。

### 9.9 404

- 继承 `base.html`；未登录时的登录跳转逻辑不变。
- 居中卡片：大号“404”/图标、标题“页面未找到”、说明“请求的资源不存在或已被删除。”、`message` 若有则展示。
- 主按钮“回公司列表”链到 `/`；可加次要链接“Webhook 投递”到 `/deliveries`，不堆更多链接。
- 已软删 Issue 仍返回 404 或说明“已在 GitHub 删除”，不展示流程按钮。
- 404 页面不显示营销文案、不自动跳转。

## 10. 跨页交互细节

### 10.1 导航与当前对象

- 顶栏当前导航使用 `aria-current="page"`；公司 / 仓库 / Issue 层级通过面包屑表达，不把三级都塞进顶栏。
- 仓库详情页的“查看 Issue”链到该仓库 Issue 列表；Issue 详情页面包屑可回到列表。
- 从列表进入详情再返回时，浏览器后退保留列表筛选；面包屑链接不带查询参数（与基石一致）。

### 10.2 操作可见性

- 每行 / 每页最多一个 primary；`issue_actions` 宏兜底降级多余 primary。
- 主 CTA 固定在内容之前；任务状态、日志、Worker 信息不排在其上。
- 禁用态必须同时有文字说明，不只降低透明度；“排队中”用禁用按钮 + 文案，不用可点击链接。
- 外链图标按钮必须有 `aria-label`；按钮与链接保持 `cursor-pointer`。

### 10.3 轮询片段契约

`GET /issues/{id}/status-fragment` 继续返回 HTML 片段，由 `partials/issue_live.html` 渲染；实现时用该 partial 替换现有 `_status_fragment_html()` 的手工字符串拼接，响应类型与鉴权不变。建议结构：

```html
<div data-done="{{ '0' if polling else '1' }}">
  <div id="issue-live-status" aria-live="polite">
    <!-- 流程状态、GitHub 状态、最近任务、阶段、Worker -->
  </div>
  <pre id="issue-log-live" class="hidden">{{ log_text }}</pre>
  <p id="issue-log-updated" class="sr-only">日志已更新</p>
</div>
```

前端约定：

- 读取 `[data-done]`；`1` 时停止定时器。
- 用 `#issue-live-status.innerHTML` 替换状态区（内容由服务端转义）。
- 用 `#issue-log-live.textContent` 更新日志，**不**把日志 HTML 注入页面。
- 更新前记录日志滚动位置；位于底部 32px 内则更新后滚到底，否则保持位置并显示“有新日志”。
- 片段不包含导航、页头、操作按钮、CSRF，避免误替换或重复提交。

### 10.4 时间与空值

- 所有时间为 UTC，显示到分钟；`title` 保留 ISO 全量。
- 空值统一“—”，不显示 `None` / `null`。
- 长标题、长路径、长错误都必须有截断或换行策略，不允许撑破页面。

### 10.5 错误与冲突

- 409 / 业务冲突：服务端 303 + `flash=error` + 可读原因；页面顶部展示完整原因，不吞掉。
- 表单校验失败：HTTP 200 本页重渲染；字段错误 + 页顶摘要 + 焦点。
- 轮询 401：停止轮询 + 页面内错误提示 + 登录链接；不使用阻塞式弹窗。
- 同步失败：保留本地路径，只在页顶 / 行内展示短错误，不弹出新页面。

## 11. 无障碍与响应式底线

### 11.1 无障碍

- 每个输入有可见 `<label>`；不用 placeholder 代替 label。
- 状态不只靠颜色：徽章始终带文字，图标 `aria-hidden`。
- 图标按钮带 `aria-label`；外链说明“在新标签打开”可通过 `title` 或可见图标辅助。
- 跳转主内容链接；主内容 `id="main"`。
- 键盘顺序自然；modal 打开后焦点进入 modal，Esc 关闭，关闭后焦点回到触发按钮。
- 焦点环可见：`focus-visible` 使用主色 outline，不被 `outline-none` 移除。
- 轮询状态区 `aria-live="polite"`；日志不整体朗读；更新有视觉提示。
- 对比度：正文 ≥ 4.5:1，弱化文字不低到不可读；徽章文字与底色对比合格。
- `prefers-reduced-motion: reduce` 下关闭动画 / 过渡；日志滚动不做平滑动画。
- `viewport` 保持 `width=device-width, initial-scale=1`；不禁用缩放。

### 11.2 响应式

- 主内容 `max-w-7xl`；窄屏左右 `px-4`。
- 宽表格外包 `overflow-x-auto`；表格设置合理 `min-w`，允许横向滚动，不压缩到不可读。
- 页头动作区、筛选工具条、操作列使用 `flex-wrap`。
- 卡片网格：`md` / `lg` / `xl` 逐级展开；Issue 详情在 `xl` 以下单列。
- 顶栏导航小屏横向滚动；不做需要 JS 的折叠菜单。
- 最小检查宽度：375px、768px、1280px。

## 12. 影响面

### 12.1 模板与前端

| 文件 | 变更 |
| --- | --- |
| `app/templates/base.html` | 重写壳层：顶栏、导航高亮、用户区、面包屑、flash、页脚、modal 容器、脚本 |
| `app/templates/login.html` | 品牌布局、口令显示切换、错误态、共用 head partial |
| `app/templates/404.html` | 404 视觉与回首页引导 |
| `app/templates/companies.html` | 页头、表格主次、空状态、分页 |
| `app/templates/repos.html` | 页头统计、路径阻塞提示、操作主次、分页 |
| `app/templates/repo.html` | GitHub 资料 / 本地配置分组、字段错误、同步操作 |
| `app/templates/issues.html` | 筛选工具条、徽章、操作主次、筛选空状态、分页 |
| `app/templates/issue_detail.html` | 摘要条、操作条、正文 / 文档 / 任务 / 日志分区、轮询 JS |
| `app/templates/deliveries.html` | 状态胶囊、仓库名、错误截断、筛选空状态、分页 |
| `app/templates/settings.html` | 代理单选卡片、Worker 心跳卡片 |
| `app/templates/partials/head_assets.html` | 新增：CDN、字体、Tailwind 配置、CSS 变量 |
| `app/templates/partials/flash.html` | 新增：成功 / 错误提示 |
| `app/templates/partials/issue_live.html` | 新增：轮询片段 |
| `app/templates/macros/icons.html` | 新增：内联 SVG |
| `app/templates/macros/ui.html` | 新增：徽章、页头、空状态、分页、动作按钮、modal |

### 12.2 Python 只读上下文

| 文件 | 变更 |
| --- | --- |
| `app/services/actions.py` | `Action` 增加 `variant` / `icon` 纯展示字段；`actions_for` 条件不变 |
| `app/api/v1/companies.py` | 传 `total` / `pagination`；不新增查询逻辑，复用 `count_companies` |
| `app/api/v1/repos.py` | 传 `total` / `pagination`；复用 `repo_count`；GET 仍不执行 git（除非第 15 节确认） |
| `app/api/v1/issues.py` | 列表传 `total` / `pagination` / `has_filters` / `status_options`；详情传 `worker_status` / `worker_label` / `worker_related`；片段改为渲染 partial；轮询间隔由前端改 5 秒 |
| `app/api/v1/deliveries.py` | 批量只读查询仓库 `github_full_name`；传 `has_filter` / `pagination` |
| `app/api/v1/settings.py` | 传 `worker_status`；现有 `worker_label` / `worker_updated_at` / path 保留 |

以上均为模板上下文或只读投影，不改变路由签名、响应状态、数据库 schema 或业务写入。

### 12.3 明确不改

- `app/models/**`、`app/alembic/**`：无迁移。
- `app/api/v1/webhook.py`、`app/services/ingest.py`、`app/tasks/**`、`app/services/git_repo.py`、`app/services/agent.py`、`app/services/prompts.py`。
- `app/core/security.py`、`app/dependencies/auth.py`、`app/core/settings.py`。
- `docs/README.md`、`docs/architecture/design.md`、`deploy/**`、`config.yaml.example`。
- 所有 URL、HTTP 方法、CSRF / JWT、按钮入队条件。

### 12.4 测试影响

- 现有 pytest 业务断言应全部通过；`actions_for` 返回的标签与条件不变。
- 新增 `tests/test_ui.py`（或等价）覆盖第 13 节的 UI 冒烟项。
- 不引入截图基线工具；视觉与键盘检查以人工清单为主。

## 13. 验收清单

### 13.1 页面与视觉

- [ ] 登录、壳层、公司列表、仓库列表、仓库详情、Issue 列表、Issue 详情、Webhook 投递、设置、404 均完成改版，风格一致，不再像空白 demo。
- [ ] 顶栏产品名“GitHub 工作流”清晰；导航当前项高亮；用户区、退出、面包屑、页脚完整。
- [ ] 所有状态使用“文字 + 颜色 + 图标”徽章；没有用 emoji 当导航或状态图标。
- [ ] 列表有页头说明、主次列、行悬停、空状态；宽表格在 375px 下横向滚动且不撑破页面。
- [ ] Issue 详情顺序为：操作条 → 摘要 → 正文 / 设计文档 / 任务 → 日志；主 CTA 不被任务状态淹没。
- [ ] 设置页代理选择与 Worker 心跳卡片清晰；空闲 / 执行中 / 无心跳均可辨。

### 13.2 业务行为不回退

- [ ] 登录 → 浏览公司 / 仓库 / Issue → 编写文档 → 生成代码 →（已有）PR 的流程仍可走通。
- [ ] 所有按钮的启用 / 禁用 / 链接条件与改版前一致；CSRF 隐藏字段与校验行为不变。
- [ ] 贵重操作（编写文档、重新编写文档、生成代码、重试动工作区、重试创建 PR）均弹出 DaisyUI modal；取消不提交，确认只提交一次，提交中禁用。
- [ ] flash 成功自动隐藏、错误保留；表单字段错误贴字段并聚焦第一个错误字段。
- [ ] 409 / 冲突文案完整可读；关闭 Issue 后无流程按钮，仅保留已有 PR 链接。
- [ ] 空列表、筛选无结果、人工介入只收录说明均正确。
- [ ] 设置页仍展示 Worker 心跳（空闲 / 执行中 / 无心跳）。
- [ ] 投递页仅 `failed` 可重试，重试后 flash“已重新排队”。

### 13.3 轮询与鉴权

- [ ] Issue 详情在 `drafting` / `generating` 时每 5 秒轮询，状态与日志更新；任务结束停止。
- [ ] 日志默认跟随最新；用户上滚阅读时不被强制拉回，并能回到最新。
- [ ] 未登录访问 `/issues/{id}/status-fragment` 返回 401，不泄露日志。
- [ ] 轮询遇到 401 / 登录页响应时停止并提示重新登录，不使用阻塞式 `alert()`。

### 13.4 无障碍与安全

- [ ] 所有输入有可见 label；图标按钮有 `aria-label`；跳转主内容链接可用。
- [ ] 键盘可完成登录、筛选、保存、打开 / 取消 / 确认 modal；焦点环可见。
- [ ] 状态不只靠颜色；正文对比度合格；`aria-live` 只用于状态区。
- [ ] `prefers-reduced-motion: reduce` 下动画 / 过渡关闭。
- [ ] Issue 正文、设计文档、日志、错误无 `|safe`；日志用 `textContent` 更新；外链带 `rel="noopener"`。

### 13.5 约束

- [ ] 设计文档路径为 `docs/v0001-2/design.md`，未删除 / 替换基石入口。
- [ ] 未新增数据库迁移、API 契约、路由或业务规则。
- [ ] 现有测试通过；新增 UI 冒烟测试通过。

## 14. 实施顺序

1. `partials/head_assets.html`：字体、CDN、Tailwind 配置、CSS 变量、reduced motion。
2. `macros/icons.html` + `macros/ui.html`：图标、徽章、页头、空状态、分页。
3. `base.html`：壳层、导航、面包屑、flash、页脚、modal 容器与脚本。
4. 公司列表、仓库列表、仓库详情。
5. Issue 列表：筛选、徽章、操作、分页、空状态。
6. Issue 详情：摘要、操作、正文 / 文档 / 任务分区；`partials/issue_live.html` 与 5 秒轮询。
7. 投递列表、设置、404、登录页。
8. 只读上下文补齐、测试、375 / 768 / 1280 视觉检查、键盘与 reduced motion 检查。

不涉及数据库迁移，不需要停机窗口；按现有 Web 进程部署方式重启即可。

## 15. 待确认

以下问题 Issue 未写清，先按“默认处理”实施；确认后再调整，均不影响状态机。

| # | 问题 | 默认处理 | 需要确认的点 |
| --- | --- | --- | --- |
| 1 | 页脚是否显示环境名 / 版本号，来源是什么 | 只显示“GitHub 工作流 · 内部运维台”，不显示环境名和版本号 | 当前没有 `APP_ENV` / 版本注入；若需要，请确认变量名与生产取值 |
| 2 | 生产网络是否允许 Google Fonts 和现有 CDN | 使用 `Source Sans 3` / `JetBrains Mono`，失败回退系统栈 | 若生产禁外网字体，改为纯系统栈；Tailwind / DaisyUI CDN 现状不变 |
| 3 | GitHub 头像外链是否允许 | 显示 `avatar_url`，失败回退姓名首字 | 若网络策略不允许外链图片，统一使用姓名首字 |
| 4 | 仓库详情是否在本迭代补 `origin_mismatch` 只读检查 | 保留警告位，GET 不新增 git 检查（当前恒为 `False`） | 若要求页顶真实提示，需要确认允许 GET 执行只读 `git remote` 并接受失败降级 |
| 5 | Issue 列表流程状态筛选是否改为固定下拉 | 改为固定下拉，参数名和值不变，避免手输错值 | 若需兼容未来未知状态，可保留“自定义值”输入；请确认 |
| 6 | 任务日志是否使用深色终端块 | 浅色页面中使用深色日志块，提升等宽日志可读性 | 若要求全浅色，改为浅灰等宽块；不影响信息结构 |
| 7 | 投递列表显示仓库 `owner/repo` 是否接受额外只读查询 | 按 `repository_id` 批量查询 `repository` 表，查不到回退 GitHub id | 不新增字段 / 迁移；确认可接受一次只读查询 |
| 8 | 公司 / 仓库 / Issue 列表是否在本迭代补齐分页控件 | 补齐只读总数与“上一页 / 下一页”，与界面契约一致 | 当前路由未传 `has_next`；若本迭代只做视觉，可另开 Issue 补分页 |

## 16. 参考

- 基石入口：[`docs/README.md`](../README.md)
- 完整产品设计：[`docs/architecture/design.md`](../architecture/design.md)，重点阅读「界面契约」「页面」「错误页」「状态机」
- 本迭代 Issue：GitHub Issue `#2`「全站控制台 UI 改版：从 demo 级页面升级为可用的运维台」
- Skills：`documentation`（编写本文档）、`ui-ux-pro-max`（实现 UI 时加载）
- 现有实现：`app/templates/`、`app/services/actions.py`、`app/api/v1/{companies,repos,issues,deliveries,settings}.py`
