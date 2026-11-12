# 升级 daisyUI 5，删除自研壳与 --gw-*，全站优先官方组件（v0005 / Issue #10）

- 迭代：`v0005`，对应 GitHub Issue `#10`
- 文档路径：`docs/v0005-10/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：相对基石的 **UI 实现层增量**。只替换前端壳、组件与主题变量，不改路由、状态机、Webhook、Job、按钮入队条件和轮询行为。

## 1. 背景

控制台当前已引入 daisyUI 4（`daisyui@4.12.14` CDN）和 `data-theme="corporate"`，部分控件使用了 `btn`、`badge`、`alert`、`modal`、`input`、`link`。但壳层和多数版面仍是自研类与裸 Tailwind：

| 现状 | 位置 | 问题 |
| --- | --- | --- |
| `.gw-card` | `head_assets.html`、各页面 | 自研卡片，未使用 daisyUI `card` |
| `.gw-nav-link` + 手写 `header` | `base.html` | 未使用 `navbar` / `menu` |
| `.gw-table` | 各列表页 | 未使用 daisyUI `table` |
| 手写面包屑 `ol` + `chevron-right` | `base.html` | 未使用 `breadcrumbs` |
| `--gw-*` + 大量 `bg-slate-*` / `text-sky-*` / `border-slate-*` | `head_assets.html`、各模板 | 自研主题色，未走 daisyUI 语义色 |
| `.gw-markdown` | `head_assets.html`、Issue 详情 | 自研 Markdown 排版，引用 `--gw-*` |
| `font-mono-data` | 各模板 | 自研等宽工具类 |

结果是页面观感更像「Tailwind 运维台」，而不是 daisyUI 组件页。基石仍要求浅色运维台的密度、焦点、反馈和界面契约；本迭代在**不改业务语义**的前提下完成两件事：

1. 升级到 **daisyUI 5**，按官方要求接入 Tailwind 4；
2. 把实现规则改成**组件优先**：daisyUI 5 有对应组件就必须用，没有才允许原生 HTML + Tailwind。

## 2. 目标

### 2.1 升级到 daisyUI 5

1. 从 daisyUI 4 CDN 升级为 **daisyUI 5**，并接入 Tailwind 4。
2. 继续浅色、非暗色默认；主题使用 daisyUI 5 内置浅色主题 `corporate`，对应原 `corporate` 语义。
3. 颜色一律使用 daisyUI 语义色（`primary`、`base-*`、`success`、`warning`、`error`、`info`、`neutral` 及其内容色），不再依赖自研色板堆叠。
4. 集成方式在设计里写死，见 4.1；本迭代不引入 npm、Node、前端构建或生成式 CSS 产物。

### 2.2 组件选用规则（强制）

| 情况 | 做法 |
| --- | --- |
| daisyUI 5 **有**对应组件 | **必须**用该组件，禁止用原生 HTML + Tailwind 再造同等外观 |
| daisyUI 5 **没有**对应组件 | 才允许原生 HTML + Tailwind 工具类自行实现；间距、栅格、截断、`max-w-7xl`、`overflow-x-auto` 等布局补齐也属此类 |

补充约定：

- 仓库页等大卡片属于「有组件」：必须用 `card` 及 `card-body` / `card-title` / `card-actions`。卡片**内部**栅格可用 Tailwind，但卡片外壳、标题和操作区结构不得自研替代。
- 有 daisyUI 组件时，允许在组件上叠加布局/尺寸工具类（例如 `card` 加 `w-full`、`btn` 加 `btn-sm`），但不得重新实现组件的边框、背景、状态和交互外观。
- 图标仍使用现有 SVG `icon()` 宏，不用 emoji 代替导航或状态图标。

### 2.3 删除自研壳与主题变量

以下**删除**，不保留薄封装、不留兼容别名：

- `.gw-card`
- `.gw-table`
- `.gw-nav-link`
- 全部 `--gw-*` CSS 变量及其引用

同时清理两处同源遗留：

- `.gw-markdown` 重命名为 `.md-content`，仅保留 Markdown 正文排版作用域；不保留 `.gw-markdown` 别名。
- `font-mono-data` 替换为 Tailwind `font-mono`（字体栈由 Tailwind 4 `@theme` 定义），不保留旧工具类。

`head_assets.html` 中与上述相关的自研 CSS 一并清掉。若仍需极少全局规则（`prefers-reduced-motion`、等宽字体、焦点兜底、Markdown 正文排版、锚点偏移），必须写明「daisyUI 5 无对应能力」。详见 4.7。

### 2.4 替换范围

覆盖全站已登录页、登录页和 404：

| 区域 | 从 | 到 |
| --- | --- | --- |
| 顶栏 | 手写 sticky header | daisyUI 5 `navbar` |
| 主导航 | `.gw-nav-link` | `menu` + `menu-active`；当前页用 `aria-current="page"` |
| 面包屑 | 手写 `ol` + chevron | `breadcrumbs` |
| 内容卡片（含仓库页大卡片） | `.gw-card` | `card` + `card-body` / `card-title` / `card-actions` |
| 数据表 | `.gw-table` | daisyUI `table` |
| 页脚 | 手写 footer | `footer` |
| 表单 | 不统一 | `fieldset` / `label` / `input` / `select` / `textarea` / `radio` |
| 空状态 / 分页 | 宏内自研块 | `card` + `card-body`；分页用 `join` + `join-item btn` |
| 确认框 | 已有 `modal` | 统一为 daisyUI 5 `modal modal-middle` 用法 |
| 状态徽章 | 已有 `badge` | 保持 `badge`，颜色只用语义 tone |
| 头像 / 指标 | 自研圆点、`rounded-lg bg-slate-50` | `avatar` / `stats` + `stat` |
| 提示 / 加载 | 已有 `alert` / `loading` | 保持组件，清理自造红黄底与动画 |

### 2.5 工程约束

- **不改**路由、状态机、Webhook、Job、按钮入队条件、表单字段名、CSRF、flash 参数、分页参数和轮询 DOM id（如 `#issue-live-status`、`#issue-log`、`#issue-log-live`、`#issue-log-jump`、`#issue-log-updated`、`data-done`）。
- 宏（`macros/ui.html`）输出改为 daisyUI 5 结构；UI 相关 pytest 断言同步更新。
- 不新增数据库迁移、环境变量、Nginx 配置或静态文件路由。
- 合并前更新基石「界面契约」：写明「有组件必须用 daisyUI 5；无组件才可用 HTML + Tailwind」，并写明 `.gw-*` 与 `--gw-*` 已废弃删除。

### 2.6 文档同步

- 本迭代结论写入本文件。
- 实现版面时按 Issue 要求使用 `ui-ux-pro-max`；组件选型前逐个阅读 daisyUI 5 官方组件文档（card、navbar、menu、breadcrumbs、table、footer、fieldset、modal、join、stats、avatar 等），不凭记忆写类名。
- 实现 PR 必须同步修改 `docs/architecture/design.md`：
  - 技术栈 UI 行改为 daisyUI 5 + Tailwind 4（CDN，不使用 npm、不做前端构建）。
  - 「界面契约 → 视觉与组件」改为 daisyUI 5 语义色和组件优先规则。
  - 写明 `.gw-card`、`.gw-table`、`.gw-nav-link`、`--gw-*` 已删除，不再作为可复用类或主题变量。
- 本任务只允许写 `docs/v0005-10/design.md`，不直接改基石正文。

## 3. 非目标

- 不做暗色主题、多主题切换、完整设计系统站点或组件文档站。
- 不重做信息架构（公司 → 仓库 → Issue 层级与字段集合不变）。
- 不顺便做 Issue 正文 Markdown 渲染、PR 状态同步等其它功能 Issue。
- 不改变任何业务状态机、入队条件、错误码、flash 文案语义或任务执行逻辑。
- 不引入 npm、`package.json`、`node_modules`、Node 构建链或生成的 CSS 文件；不把 Tailwind 改为构建期编译。
- 不做逐页重新设计；只把现有版面换成 daisyUI 5 组件与语义色，保留浅色运维台密度。
- 不为兼容旧类保留 `.gw-*` 别名或 `--gw-*` 回退值。

## 4. 方案

### 4.1 关键决策：继续 CDN，使用 daisyUI 5 + Tailwind 4 浏览器版

**结论：本迭代不引入 npm 或前端构建，继续使用 CDN；所有 head 资源仍集中在 `app/templates/partials/head_assets.html`。**

理由：

1. 基石技术栈明确「DaisyUI + Tailwind CSS，CDN；不使用 npm，不做前端构建」。本迭代没有必须引入构建链的新需求。
2. 当前实现本来就是 Tailwind Play CDN 运行时编译，升级到 `@tailwindcss/browser@4` 不改变运行形态；差异主要是 daisyUI 5 的 CSS 与主题文件。
3. 部署仍由 Supervisor 跑 Python 进程，不需要在服务器安装 Node 或维护前端构建产物。
4. 若未来要把生产级最小构建作为独立事项，必须先改基石技术栈、CI 与部署流程，另开迭代；不在本迭代夹带。

`head_assets.html` 的目标结构：

```html
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link
  href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Source+Sans+3:wght@400;500;600;700&display=swap"
  rel="stylesheet"
/>

<!-- daisyUI 5：组件与基础样式；themes.css 提供 corporate 等内置主题 -->
<link href="https://cdn.jsdelivr.net/npm/daisyui@5.7.50" rel="stylesheet" type="text/css" />
<link href="https://cdn.jsdelivr.net/npm/daisyui@5.7.50/themes.css" rel="stylesheet" type="text/css" />
<!-- Tailwind 4 浏览器版：仅生成工具类，不再使用 tailwind.config.js -->
<script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>

<style type="text/tailwindcss">
  @theme {
    --font-sans: "Source Sans 3", system-ui, -apple-system, "Segoe UI",
      "PingFang SC", "Microsoft YaHei", sans-serif;
    --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo,
      Consolas, monospace;
  }
</style>
```

要点：

- 删除现有 `tailwind.config = { ... }` 脚本；Tailwind 4 使用 CSS-first 的 `@theme`，字体栈移到上面的 `<style type="text/tailwindcss">`。
- 不写 `@plugin "daisyui"`；daisyUI 5 组件 CSS 由 CDN 文件提供，Tailwind 浏览器版只负责工具类。
- 不写 `@apply`；运行时 CDN 不在构建期处理它。
- 版本写死为 `5.7.50`（设计时 daisyUI 官方文档版本）。实现时若 CDN 已发布更高的 5.x patch，是否升级见第 7 节待确认；不得回退到 daisyUI 4。
- `data-theme="corporate"` 保留在 `base.html` 与 `login.html` 的 `<html>` 上；`themes.css` 提供该内置浅色主题。
- 不新增静态文件、`package.json`、`package-lock.json`、`node_modules` 或生成的 CSS。

### 4.2 主题与语义色映射

不自定义主题色板，直接使用 daisyUI 5 `corporate` 的语义 token。模板中的颜色按以下方式替换：

| 旧写法（示例） | 新写法 | 用途 |
| --- | --- | --- |
| `bg-slate-50` / `--gw-bg` | `bg-base-200` | 页面背景 |
| `bg-white` / `--gw-surface` | `bg-base-100` | 卡片、顶栏、表格容器 |
| `text-slate-900` / `--gw-ink` | `text-base-content` | 主文字 |
| `text-slate-500` / `text-slate-600` / `--gw-muted` | `text-base-content/70` 或 `/60` | 次要文字 |
| `border-slate-200` / `--gw-line` | `border-base-300` | 边框、分隔线 |
| `bg-sky-700` / `text-sky-700` / `--gw-accent` | `bg-primary` / `text-primary` / `link-primary` | 主操作、链接 |
| `bg-sky-50` / `--gw-accent-soft` | `bg-primary/10` | 选中态、信息底 |
| `text-emerald-700` / `--gw-success` | `text-success` | 成功 |
| `text-amber-700` / `bg-amber-50` / `--gw-warning` | `text-warning` / `bg-warning/10` | 等待、警告 |
| `text-red-600` / `bg-red-50` / `--gw-danger` | `text-error` / `bg-error/10` | 失败、错误 |
| `text-sky-700` / `--gw-info` | `text-info` | 进行中 |
| `bg-slate-950 text-slate-100`（日志块） | `bg-neutral text-neutral-content` | 深色日志终端块 |

约定：

- 状态徽章继续「文字 + 颜色」同时表达，不只靠颜色；tone 映射保持现有 `badge-ghost` / `badge-info` / `badge-success` / `badge-warning` / `badge-error`。
- 除日志终端块外，不再出现 `slate-*`、`sky-*`、`red-*`、`emerald-*`、`amber-*` 等自选色阶；日志块使用 `neutral` 语义色，不构成暗色主题。
- 需要透明度时使用 `/10`、`/20`、`/60`、`/70` 等工具类，不新增 CSS 变量。
- `corporate` 的实际色值由 daisyUI 主题提供；实现时用浏览器检查正文对比度与焦点可见性，见第 7 节待确认。

### 4.3 daisyUI 4 → 5 迁移要点

实现时先按官方组件文档选型，再写模板。与本次相关的 v5 变化：

| daisyUI 4 写法 | daisyUI 5 写法 |
| --- | --- |
| `card card-bordered` | `card card-border` |
| `menu` 内 `active` 类 | `menu-active` |
| `input input-bordered` | `input`（默认有边框；`input-ghost` 去边框） |
| `select select-bordered` | `select` |
| `textarea textarea-bordered` | `textarea` |
| `table` 行 `hover` 类 | `hover:bg-base-300` 工具类 |
| `footer` 默认横向 | 默认纵向；横向用 `footer-horizontal` 或 `md:footer-horizontal` |
| `btn-group` | `join` + `join-item` |
| `form-control` / `label-text` / `label-text-alt` | `fieldset` + `fieldset-legend` + `label` |
| `card-compact` | `card-sm`（本迭代不使用） |

### 4.4 组件选型矩阵（强制）

| 区域 | 必须使用的 daisyUI 5 组件 | 关键结构 / 类 | 禁止 |
| --- | --- | --- | --- |
| 顶栏 | `navbar` | `navbar bg-base-100` + `navbar-start` / `navbar-center` / `navbar-end` | 手写 sticky header + 自定义 flex 壳 |
| 主导航 | `menu` | `menu menu-horizontal menu-sm`；当前项 `menu-active` + `aria-current="page"` | `.gw-nav-link` |
| 面包屑 | `breadcrumbs` | `breadcrumbs text-sm` + `ul > li`；最后一项 `aria-current="page"` | 手写 `ol` + chevron 分隔 |
| 内容卡片 | `card` | `card card-border bg-base-100 shadow-sm` + `card-body` + `card-title` + `card-actions` | `.gw-card` |
| 数据表 | `table` | `table` + `overflow-x-auto`；行悬停 `hover:bg-base-300` | `.gw-table` |
| 页脚 | `footer` | `footer footer-center border-t border-base-300 bg-base-100` | 手写 footer 块 |
| 表单 | `fieldset` / `label` / `input` / `select` / `textarea` / `radio` | `fieldset` + `fieldset-legend`；`label` 组件；`input` / `select` 不再加 `*-bordered` | 裸控件 + Tailwind 自绘边框 |
| 空状态 | `card` | `card` + `card-body items-center text-center` + `card-title` + `card-actions` | 宏内自研空状态块 |
| 分页 | `join` + `btn` | `join` + `join-item btn btn-sm`；当前页 `btn-active` | 自研 flex 分页条 |
| 筛选按钮组 | `join` + `btn` | `join` + `join-item btn btn-sm`；激活项 `btn-active` | 自研按钮条 |
| 状态徽章 | `badge` | `badge badge-sm` + tone 类 | 只靠色点 |
| 头像 | `avatar` | `avatar` / `avatar-placeholder` + 圆形容器 | 自研圆点 + 绝对定位图片 |
| 指标 | `stats` / `stat` | `stats` + `stat` + `stat-title` + `stat-value` | 自研 `rounded-lg bg-slate-50` 指标格 |
| 确认框 | `modal` | `modal modal-middle` + `modal-box` + `modal-action` + `modal-backdrop` | `window.confirm` 或自研弹层 |
| 提示 | `alert` | `alert alert-success` / `alert-error` / `alert-warning` / `alert-info` | 自造红底/黄底提示块 |
| 加载 | `loading` | `loading loading-spinner loading-xs` | 自研旋转动画 |
| 文本链接 | `link` | `link link-hover` / `link-primary` | 裸 `<a>` + 手写下划线样式 |

表格默认使用 `table`，**不新增** `table-zebra`：v0001 已确定「列表不使用斑马纹，用行悬停和分隔线建立可扫性」。行悬停按 v5 写法使用 `hover:bg-base-300`。`table-sm` 也不作为默认值，保持现有舒适行高。

### 4.5 全局壳 `base.html`

目标结构：

```html
<body class="min-h-dvh bg-base-200 text-base-content antialiased">
  <a href="#main" class="sr-only focus:not-sr-only ...">跳到主内容</a>

  <header class="sticky top-0 z-30 border-b border-base-300 bg-base-100/95 backdrop-blur">
    <div class="navbar mx-auto max-w-7xl flex-wrap gap-x-4 gap-y-1 px-4 py-1.5 sm:px-6 lg:px-8">
      <div class="navbar-start w-auto flex-none">
        <!-- 品牌：icon() + 产品名 -->
      </div>
      <div class="navbar-center order-3 w-full justify-start overflow-x-auto lg:order-none lg:w-auto">
        <ul class="menu menu-horizontal menu-sm gap-1 px-1" aria-label="主导航">
          <li><a class="menu-active" aria-current="page" href="/">…</a></li>
          <li><a href="/deliveries">…</a></li>
          <li><a href="/settings">…</a></li>
        </ul>
      </div>
      <div class="navbar-end w-auto flex-none gap-2">
        <!-- avatar + 用户名 + 退出表单 -->
      </div>
    </div>
  </header>

  <main id="main" class="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
    {% if breadcrumbs and breadcrumbs|length > 1 %}
    <nav class="breadcrumbs mb-4 text-sm" aria-label="面包屑">
      <ul>
        {% for label, href in breadcrumbs %}
        <li>
          {% if href and not loop.last %}
          <a class="link link-hover max-w-[16rem] truncate" href="{{ href }}" title="{{ label }}">{{ label }}</a>
          {% else %}
          <span class="max-w-[22rem] truncate" {% if loop.last %}aria-current="page"{% endif %} title="{{ label }}">{{ label }}</span>
          {% endif %}
        </li>
        {% endfor %}
      </ul>
    </nav>
    {% endif %}

    {% block page_header %}{% endblock %}
    {% include "partials/flash.html" %}
    {% block content %}{% endblock %}
  </main>

  <footer class="footer footer-center border-t border-base-300 bg-base-100 p-4 text-xs text-base-content/60">
    <p>GitHub 工作流 · 内部运维台</p>
  </footer>

  <dialog id="gw-confirm" class="modal modal-middle" aria-labelledby="gw-confirm-title" aria-describedby="gw-confirm-body">
    <div class="modal-box">
      <h3 id="gw-confirm-title" class="text-lg font-semibold text-base-content"></h3>
      <p id="gw-confirm-body" class="py-3 text-sm leading-6 text-base-content/70"></p>
      <div class="modal-action">
        <button type="button" class="btn btn-ghost" data-gw-cancel>取消</button>
        <button type="button" class="btn btn-primary" data-gw-ok>确认执行</button>
      </div>
    </div>
    <form method="dialog" class="modal-backdrop" data-gw-backdrop>
      <button>关闭</button>
    </form>
  </dialog>
</body>
```

要点：

- 小屏不折叠成汉堡菜单：主导航仍横向滚动，保持 v0001 的壳层约定。
- 面包屑由 `breadcrumbs` 自动生成分隔，不再手写 `chevron-right`；长标题仍用 `truncate` + `title`。
- 顶栏和页脚只换组件与语义色，不改变链接、POST /logout、CSRF 和文案。
- `modal` 仍由现有 `app_scripts.html` 驱动；本迭代只统一 daisyUI 5 结构与 `modal-middle` variant，不改 JS 行为。
- 跳转主内容链接、`sr-only`、`focus:not-sr-only` 属于无障碍兜底，daisyUI 无对应组件，保留原生实现。

### 4.6 宏与 partial

`app/templates/macros/ui.html`：

- `badge` / `kind_badge` / `issue_status_badge` / `list_status_badge` / `pr_state_badge` / `github_state_badge` / `job_badge` / `delivery_badge` / `worker_badge`：继续输出 `badge`，tone 映射不变；只清理外层颜色。
- `page_header`：daisyUI 5 没有页面标题组件；保留原生布局，改用 `text-base-content`、`text-base-content/70`、`text-primary` 等语义色。
- `empty_state`：改为 `card card-border bg-base-100 shadow-sm` + `card-body items-center text-center` + `card-title` + `card-actions`；图标圆底用 `bg-primary/10 text-primary`。
- `pagination`：改为 `join` + `join-item btn btn-sm`；上一页/下一页用 `btn-outline`，当前页用 `btn-active`，禁用项用 `btn-disabled` + `aria-disabled="true"`。保持「只有一页时整块隐藏」。
- `issue_actions`：继续消费 `Action` 列表，不重新判断按钮条件；继续用 `namespace(primary_used)` 保证一行最多一个 `btn-primary`。只把外层文字颜色换成语义色。
- `live_status`：错误摘要改为 `alert alert-error`（或 `alert alert-error` 的紧凑尺寸），不再用 `bg-red-50` 段落；`dl` 内的标签/值使用 `text-base-content/70` / `text-base-content`。

`partials/flash.html`：

- 保持 `alert alert-success` / `alert alert-error`、`role`、关闭按钮和 5 秒隐藏行为不变。
- 只把图标/文本外层颜色换成语义色；`btn btn-ghost btn-xs` 保留。

`partials/issue_live.html`：

- 保持 `data-done`、`#issue-live-status`、`#issue-log-live`、`#issue-log-updated` 原样。
- 内部 `live_status` 随宏改造；不新增轮询字段、不改变替换方式。

`partials/app_scripts.html`：

- 不改任何 `data-gw-*` 选择器、`#gw-confirm` id、确认流程、spinner 类或提交禁用逻辑。
- 这些 `data-gw-*` / `gw-confirm` 是**行为钩子**，不是 CSS 组件；本迭代保留它们，避免改 JS 与测试契约。

### 4.7 删除内容与全局 CSS 例外

`head_assets.html` 中删除：

- `tailwind.config` 脚本与 Tailwind 3 配置。
- `:root` 下全部 `--gw-*` 变量。
- `.gw-nav-link`、`.gw-card`、`.gw-table` 全部规则。
- `.gw-markdown` 类名及其所有规则；以 `.md-content` 重写。
- `font-mono-data` 相关规则（改由 Tailwind `font-mono` 提供）。
- 以 `--gw-*` 为值的 `html` / `body` 背景、文字色规则；改由 `bg-base-200` / `text-base-content` 工具类承担。

允许保留的全局 CSS（每项都要有「daisyUI 5 无对应能力」注释）：

| 规则 | 原因 |
| --- | --- |
| `.md-content { ... }` | daisyUI 5 没有 Markdown / prose 正文组件；这是 Issue 正文与设计文档内容的作用域排版，不是壳层或组件替代。颜色使用 `var(--color-base-content)`、`var(--color-base-200)`、`var(--color-base-300)`、`var(--color-primary)`，不再出现 `--gw-*`。 |
| `@media (prefers-reduced-motion: reduce) { ... }` | daisyUI 5 没有全局 reduced-motion 开关；保留无障碍兜底。 |
| `:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible { outline: ... }` | daisyUI 组件自带焦点样式，但原生链接/自定义可聚焦元素需要统一可见焦点；保留低特异性兜底。 |
| `[id] { scroll-margin-top: 5.5rem; }` | sticky `navbar` 的锚点偏移；daisyUI 5 没有对应全局能力。 |

明确不保留：

- 不加 `.gw-card` / `.gw-table` / `.gw-nav-link` 的兼容别名。
- 不加 `--gw-*` 到 `--color-*` 的回退映射。
- 不把 `.gw-markdown` 作为 `.md-content` 的别名保留。

允许使用原生 HTML + Tailwind 的例外（实现 PR / 设计抽查时逐项说明）：

1. `page_header` 页面标题区：daisyUI 5 无页面级标题组件。
2. 跳转主内容链接、`sr-only`、`noscript`、`aria-live` 等无障碍结构。
3. `.md-content` Markdown 正文排版：daisyUI 5 无 prose / Markdown 渲染组件。
4. 任务日志与设计文档源码的 `<pre>`：daisyUI 5 的 `mockup-code` 是装饰性代码窗口，不适合可滚动实时日志；保留语义化 `<pre>` + `font-mono`。
5. 栅格、`max-w-7xl`、`gap-*`、`truncate`、`line-clamp-*`、`overflow-x-auto`、响应式布局。
6. 行内 `code` 与设计文档路径标签：daisyUI 5 无行内代码组件；使用 `bg-base-200 text-base-content`。
7. 表格操作列的多个 POST 表单/链接排列：按钮和表格本身使用 daisyUI，外壳仅用 flex 布局。
8. `dl` 元数据列表（Issue 摘要、仓库只读信息）：daisyUI 5 无 definition-list 组件；不强行套 `stats`。

### 4.8 逐页落点

#### 公司列表 `companies.html`

- 外层：`card card-border bg-base-100 shadow-sm overflow-hidden` + `card-body p-0` + `overflow-x-auto` + `table`。
- 公司头像：`avatar` / `avatar-placeholder`；加载失败仍回退姓名首字。
- 名称、仓库数、未结束数：`link`、`font-mono tabular-nums`、`text-base-content`。
- 空列表：`empty_state` 的 `card` 空状态。
- 页脚分页：`pagination` 宏的 `join`。

#### 仓库列表 `repos.html`

- 外层和表格同公司列表。
- `owner/repo`、默认分支 `code`、服务器路径 `font-mono`、未填写 `badge badge-warning`。
- 操作列：`btn btn-sm btn-primary`（Issue）+ `btn btn-sm btn-outline`（重新同步）；每行最多一个 primary。
- 空列表、分页同上。

#### 仓库页 `repo.html`

- 两个大卡片：`card card-border bg-base-100 shadow-sm` + `card-body p-5`；标题用 `card-title`；操作按钮放 `card-actions`。
- 本地配置表单：`fieldset` + `fieldset-legend` + `label` + `input`；不再使用 `input-bordered`。
- GitHub 资料：`badge`、`alert`、`dl`；只读字段使用 `font-mono` / `text-base-content/70`。
- 指标格（主语言、星标、Fork、开放 Issue、最近推送、许可证）：改为 `stats` + `stat` + `stat-title` + `stat-value`，分两行或可横向滚动，不再用自研 `rounded-lg bg-slate-50`。
- 「本系统」三个摘要链接：改为 `card card-border` + `card-body`，保留链接、数值、hover 和 focus；不再用自研 bordered `a`。
- 分隔线优先用 `divider`；不需要文字时用 `<div class="divider"></div>`。

#### Issue 列表 `issues.html`

- 筛选区：`card card-border` + `card-body p-4`；每个筛选字段用 `label` + `select`（不加 `select-bordered`），按钮用 `btn btn-sm btn-primary`（应用筛选）和 `btn btn-sm btn-ghost`（清除）。
- 列表：`card` + `table`；编号、标题、类型/状态徽章、更新时间、操作列保持原字段和顺序。
- 操作列：继续调用 `issue_actions`；`data-gw-confirm` / `data-confirm-title` / CSRF 隐藏字段不变。
- 空状态：按「人工介入」「筛选无结果」「真空列表」三种文案继续调用 `empty_state`。
- 分页：`join`。

#### Issue 详情 `issue_detail.html`

- 流程操作卡、摘要卡、正文卡、设计文档卡、任务卡、日志卡：全部 `card` + `card-body`；标题用 `card-title`。
- 摘要 `dl` 保持 8 项字段和顺序；标签用 `text-base-content/70`，值用 `text-base-content`；PR 链接用 `link link-primary`。
- 正文：`<div class="md-content">`；设计文档源码 `<pre>` 保持等宽、可滚动、`whitespace-pre-wrap`。
- 日志块：`bg-neutral text-neutral-content`，保留 `#issue-log`、`tabindex="0"`、`aria-label`、最大高度、滚动与「有新日志，回到底部」按钮。
- 轮询状态区和右栏 `data-gw-region="issue-side"` 不动；任务/日志卡顺序不动。

#### Webhook 投递 `deliveries.html`

- 顶部状态筛选：`card` + `card-body p-3`，内部用 `join` + `join-item btn btn-sm`；当前项 `btn-active` + `aria-current="page"`。
- 表格：`card` + `table`；状态徽章、错误摘要、时间为原字段。
- 失败行「重试投递」：`btn btn-sm btn-outline`；POST / CSRF 不变。
- 空状态、分页同其它列表。

#### 设置 `settings.html`

- 全站代理卡、Worker 心跳卡：`card` + `card-body` + `card-title`。
- 代理选项：使用 daisyUI 5 可选卡片 `label.card` + `input.radio.radio-primary` + `card-body`；当前生效项用 `border-primary bg-primary/5` 表达，不再用自研 bordered `label`。
- 未配置代理的 `alert-warning`、心跳告警保持 `alert` 组件。
- 保存按钮 `btn btn-primary btn-sm`；字段名、POST、flash 不变。

#### 登录 `login.html`

- 右侧登录卡：`card card-border bg-base-100 shadow-sm` + `card-body`；标题用 `card-title`。
- 用户名/口令：`fieldset` + `fieldset-legend` 或 `label` + `input`；不再使用 `input-bordered`；口令显示/隐藏按钮保持原 JS 与 `aria-pressed`。
- 左侧品牌区：保留原生布局；流程标签使用 `badge badge-outline`（daisyUI 组件），不使用自研圆角 `li`。
- 错误：`alert alert-error`；登录按钮 `btn btn-primary w-full`。
- 登录页无业务顶栏/页脚，保持现状。

#### 404 `404.html`

- `card card-border bg-base-100 shadow-sm` + `card-body items-center text-center` + `card-title`。
- 404 数字用 `font-mono text-base-content/30`；说明用 `text-base-content/70`。
- 回公司列表 `btn btn-primary btn-sm`，Webhook 投递 `btn btn-ghost btn-sm`。

### 4.9 业务行为不变的边界

实现 PR 只改模板、head 资源、测试和文档；以下保持不变：

- `app/api/**`、`app/services/**`、`app/models/**`、`app/tasks/**`、数据库 schema 与迁移。
- 所有路由、HTTP 方法、POST 目标、状态码、303 flash 参数、409 冲突处理。
- `Action` 列表的生成条件、按钮文案、入队条件、确认文案语义。
- 表单字段名（`local_path`、`doc_dir`、`agent`、`kind`、`status`、`pr_state`、`github_state` 等）与 GET/POST 参数。
- 分页每页 50 行、`page` 参数、筛选重置 `page=1`。
- CSRF 隐藏字段、cookie/JWT、登录/退出逻辑。
- 轮询 DOM id、`data-done`、片段替换方式、`aria-live`、日志 `textContent` 更新方式。
- 外链 `target="_blank"` / `rel="noopener"`、头像 `loading="lazy"` / `referrerpolicy="no-referrer"`、Jinja 自动转义。

### 4.10 测试与验证

UI 相关 pytest 以**静态 HTML 断言**为主，不引入浏览器测试依赖。

新增 / 调整 `tests/test_ui.py`：

1. `test_head_assets_use_daisyui5`：
   - 页面 HTML 包含 `daisyui@5`、`themes.css`、`@tailwindcss/browser@4`、`data-theme="corporate"`。
   - 不包含 `daisyui@4`、`cdn.tailwindcss.com`、`tailwind.config`、`--gw-`。
2. `test_templates_have_no_legacy_shell`：
   - 遍历 `app/templates/**/*.html`，断言不出现 `gw-card`、`gw-table`、`gw-nav-link`、`gw-markdown`、`font-mono-data`、`--gw-`。
   - 不把 `data-gw-*` / `id="gw-confirm"` 纳入禁用清单；它们是行为钩子。
3. `test_pages_use_daisyui_components`：
   - 已登录页断言 `class="navbar`、`class="menu`、`breadcrumbs`、`class="table`、`class="card`、`footer` 等组件标记存在。
   - 列表页断言 `class="table"`；空状态断言 `card` + `card-title` + `card-actions`。
4. `test_forms_use_daisyui5`：
   - 登录/仓库/设置/筛选表单断言 `fieldset`、`label`、`input` / `select` / `radio`；不出现 `input-bordered`、`select-bordered`。
5. 保留并继续断言：
   - `data-gw-confirm`、`data-confirm-title`、`id="gw-confirm"`、`确认执行`。
   - `data-gw-region="issue-side"`、`#issue-live-status`、`#issue-log`、`#issue-log-jump`、`#issue-log-live`、`data-done`。
   - `aria-live="polite"`、`aria-current="page"`、CSRF 隐藏字段。
6. 更新 `tests/test_ui.py` 中 `.gw-markdown` 断言为 `.md-content`。
7. 更新 `tests/test_issues.py` 中绑定 `font-mono-data text-slate-900` 的 4 处断言。建议给计数 span 加稳定的 `data-count` 钩子（如 `<span data-count="total" class="font-mono ...">2</span>`），测试断言 `data-count` 与文本，不再绑定颜色类。

验证命令：

```bash
# 旧壳与旧变量应为 0 命中
grep -RInE 'gw-card|gw-table|gw-nav-link|gw-markdown|--gw-' app/templates

# 旧 CDN / 旧配置应为 0 命中
grep -RInE 'daisyui@4|cdn\.tailwindcss\.com|tailwind\.config' app/templates

# UI 与全量测试
uv run pytest -q
```

人工检查清单（实现 PR 附截图或说明）：

- 1440px 与 375px 宽度：顶栏导航横向滚动、面包屑截断、表格横向滚动、卡片不撑破。
- 当前导航项有 `menu-active` + `aria-current="page"`；面包屑最后一项不可点。
- 所有列表为 `table`，所有内容区为 `card`，仓库页大卡片与空状态为 `card`。
- 表单控件有可见 `<label>`；焦点环可见；`prefers-reduced-motion` 下无进出动画；轮询替换不产生平滑滚动。
- 状态徽章文字 + 颜色同时表达；正文对比度满足 4.5:1。
- 每行最多一个 `btn-primary`；贵重操作仍弹 `modal`，取消不提交。
- 浏览器 Network 面板确认 daisyUI 5 / themes.css / Tailwind 4 均加载成功，控制台无脚本错误。

### 4.11 风险与回滚

| 风险 | 说明 | 处理 |
| --- | --- | --- |
| CDN 运行时编译 | Tailwind 官方把 Play CDN 标为开发用途；daisyUI 5 依赖现代 CSS（`oklch` / `color-mix`）。 | 本迭代沿用基石既有 CDN 形态，不新增构建；实现后用目标浏览器检查。若生产 hardening 要求构建，另开迭代并先改基石。 |
| CDN 不可用 | jsDelivr 或 Google Fonts 不可达时页面样式/字体会降级。 | 与现状同类风险；实现 PR 记录 CDN 版本，发布后检查 Network。若长期需要离线，另开自托管迭代。 |
| 主题对比度 | `corporate` 的实际色值可能让少数语义色对比度不足。 | 实现时用浏览器检查；若不足，用 daisyUI 5 theme generator 生成等价浅色主题并保留 `--color-*` 语义名（见待确认）。 |
| 运行时类扫描 | 轮询片段动态插入的类若从未在初始 DOM 出现，可能未被 Tailwind 生成。 | 片段只复用页面已出现的类；实现后实际触发轮询检查状态/日志样式。 |
| 组件优先执行不一致 | 评审只看「能显示」而放过自研替代。 | 本文件 4.4、4.7 作为检查清单；实现 PR 说明例外项；测试断言关键组件标记。 |
| 回滚 | 本迭代改模板结构与类名，不能只回滚 head_assets。 | 回滚整个 PR（模板 + head + 测试）；无数据库迁移，无数据回滚。 |

## 5. 影响面

| 区域 | 影响 |
| --- | --- |
| `app/templates/partials/head_assets.html` | 替换 CDN、删除 `tailwind.config`、新增 `@theme` 字体、删除 `--gw-*` / `.gw-*`，保留并重写 `.md-content` 与极少量全局规则 |
| `app/templates/base.html` | `navbar` + `menu` + `breadcrumbs` + `footer` + `modal` 结构；语义色 |
| `app/templates/login.html` | 登录卡改 `card`；表单改 `fieldset` / `label` / `input`；流程标签改 `badge` |
| `app/templates/404.html` | 改 `card` + `card-body` + `card-title` + `card-actions` |
| `app/templates/macros/ui.html` | `empty_state` 改 `card`；`pagination` 改 `join`；`page_header` / `live_status` / `issue_actions` 语义色与结构清理 |
| `app/templates/companies.html` / `repos.html` / `issues.html` / `deliveries.html` | 列表外壳改 `card`，表格改 `table`，筛选改 `fieldset` / `label` / `select` / `join`，分页改 `join` |
| `app/templates/repo.html` | 两张大卡片、表单、指标 `stats` / `stat`、摘要链接 `card`、分隔线 |
| `app/templates/issue_detail.html` | 六张卡改 `card`；`.md-content`；日志块 `bg-neutral text-neutral-content`；轮询 id 不变 |
| `app/templates/settings.html` | 代理选项改可选 `card` + `radio`；两张卡改 `card`；告警保持 `alert` |
| `app/templates/partials/flash.html` / `issue_live.html` / `app_scripts.html` | 仅类名/语义色调整；JS 选择器、DOM id、行为不变 |
| `tests/test_ui.py` | 新增 daisyUI 5 静态断言；更新 `.gw-markdown` 为 `.md-content`；保留确认框/轮询/CSRF 断言 |
| `tests/test_issues.py` | 更新 4 处绑定旧计数类名的断言，改用稳定 `data-count` 或新类名 |
| `docs/architecture/design.md` | 实现 PR 更新技术栈 UI 行与「界面契约」：daisyUI 5、语义色、组件优先、`.gw-*` / `--gw-*` 已删除 |
| `README.md` | 建议同步「DaisyUI CDN」为「daisyUI 5 + Tailwind 4 CDN」；不属于业务代码 |
| 后端 / 数据库 / 部署 | 无变化；无迁移、无环境变量、无 Nginx 变更；仅需发布后重启 Web 进程或确认模板热加载 |

## 6. 验收

- [ ] 运行时为 daisyUI 5：页面加载 `daisyui@5` + `themes.css` + `@tailwindcss/browser@4`，不再依赖 `daisyui@4` / `cdn.tailwindcss.com` 旧链路。
- [ ] `data-theme="corporate"` 生效；页面为浅色，正文、次要文字、边框、链接、状态色均来自 daisyUI 语义 token。
- [ ] 代码与产物中**不存在** `.gw-card` / `.gw-table` / `.gw-nav-link` / `--gw-*`；`.gw-markdown` 与 `font-mono-data` 也已删除或替换。
- [ ] 顶栏为 `navbar`；主导航为 `menu` + `menu-active`；面包屑为 `breadcrumbs`；列表为 `table`；内容区（含仓库页大卡片）为 `card` + `card-body` / `card-title` / `card-actions`；页脚为 `footer`。
- [ ] 表单使用 `fieldset` / `label` / `input` / `select` / `textarea` / `radio`；不再出现 `input-bordered` / `select-bordered` / `textarea-bordered`。
- [ ] 确认框使用 daisyUI 5 `modal modal-middle` 用法，variant 与全站一致；取消不提交，焦点回到触发按钮。
- [ ] 凡 daisyUI 5 有官方组件的控件 / 壳层，模板中不再用原生 HTML + Tailwind 自绘同等外观；仅 4.7 列出的无对应组件场景使用原生 HTML + Tailwind，并在实现 PR / 设计中可抽查说明。
- [ ] 浅色运维台契约不回退：密度、焦点可见、`prefers-reduced-motion`、状态「文字 + 颜色」、一行最多一个 `btn-primary`。
- [ ] 业务行为不变：路由、状态机、Webhook、Job、按钮入队条件、表单字段、CSRF、flash、分页参数、轮询 DOM id 与片段替换方式均未改。
- [ ] UI 相关 pytest 通过；新增的 daisyUI 5 / 无旧壳断言通过；`tests/test_issues.py` 不再绑定旧颜色类。
- [ ] 基石「界面契约」已同步：写明「有组件必须用 daisyUI 5；无组件才可用 HTML + Tailwind」以及 `.gw-*` / `--gw-*` 已删除。
- [ ] 迭代设计写入 `docs/v0005-10/design.md`；实现走 `dev_10` 并开 PR。

## 7. 待确认

以下事项 Issue 未给出唯一结论。本文先给出默认处理，最终以评审或实现 PR 确认为准：

1. **daisyUI 5 精确版本**：本文写死 `5.7.50`（设计时官方文档版本）。实现时若 CDN 已发布更高的 5.x patch，是否允许仅 patch 升级？默认不跨 minor；若升级，需在 PR 说明版本差异并重跑测试。
2. **daisyUI skill 分发**：本仓 `agent_skills/` 当前只有 `documentation` 与 `ui-ux-pro-max`，没有 daisyUI 官方 skill。实现时以 daisyui.com 的 5.7.50 组件文档为准；是否在本迭代补 skill 分发到 Worker 环境，待确认。
3. **`corporate` 对比度**：实现时用浏览器检查正文 4.5:1、焦点环和状态徽章。若 `corporate` 的某个语义色不满足，是否用 daisyUI 5 theme generator 生成等价浅色主题（保留 `primary` / `base-*` 等 token 名）？本文默认不改主题名，只调 token 值。
4. **表格斑马纹**：本文按 v0001「列表不使用斑马纹」保留 `table` + `hover:bg-base-300`，不添加 `table-zebra`。若评审希望更强扫读，可仅加 `table-zebra` 修饰符，不影响组件选型；默认不加。
5. **生产运行时 CDN 的后续硬化**：本迭代已按 4.1 写死 CDN，不引入构建；Tailwind 官方把 Play CDN 标为开发用途。是否在后续迭代切最小构建（需要 npm/Node、CI 与基石变更）不属于本迭代范围，也不影响本设计验收。
