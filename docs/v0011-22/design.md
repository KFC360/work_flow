# 顶栏导航左右分区：左侧业务入口，右侧账号相关（v0011 / Issue #22）

- 迭代：`v0011`，对应 GitHub Issue `#22`
- 文档路径：`docs/v0011-22/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：**已登录全局壳的布局与信息分组增量**。不改路由、鉴权、退出流程、页面内容、数据模型与任务流程，只调整顶栏分组和小屏表现。

## 1. 背景

已登录壳 `app/templates/base.html` 当前顶栏为三段：

- 左侧：产品品牌「GitHub 工作流 / 内部运维台」，链到 `/`。
- 中间：一组 `menu`，同时放 `公司`、`Webhook 投递`、`设置`。
- 右侧：头像、用户名、`退出`（POST `/logout`，带 CSRF）。

当前问题：

1. **业务入口与账号 / 系统项混在一组**。`设置` 属于账号或系统配置，却和 `公司`、`Webhook 投递` 并列在中间菜单，扫读时无法形成「左侧业务、右侧账号」的稳定分区。
2. **小屏分区更弱**。中间菜单使用 `order-3 w-full`，在窄屏整行换到下方；它与右侧账号区在视觉上仍是两段无明确标签的菜单，用户需要靠逐个读文案才能区分业务入口和账号操作。
3. **模板结构没有表达分区语义**。业务导航和账号相关操作没有各自的 landmark 或标签，自动化断言也只能验证「页面里存在某个链接」，不能验证「设置不在业务导航组」。

本迭代只重排已登录顶栏的信息分组，不改任何业务页面本身。

## 2. 目标

把已登录顶栏明确分为两个区域：

| 区域 | 内容 |
| --- | --- |
| **左侧（业务）** | 产品品牌 + `公司`（`/`）+ `Webhook 投递`（`/deliveries`） |
| **右侧（账号相关）** | `设置`（`/settings`）+ 当前用户（头像 / 用户名）+ `退出`（POST `/logout`） |

具体要求：

1. 使用 daisyUI `navbar` 的 `navbar-start` / `navbar-end`（或等价左右分区）；不再把 `设置` 与 `公司`、`Webhook 投递` 放在同一组中间菜单，`navbar-center` 不再承载业务或设置导航。
2. 左侧业务链的当前页高亮行为与现网一致：继续使用 `nav` 上下文值、`menu-active` 和 `aria-current="page"`。
3. 右侧账号区：`设置` 链到 `/settings`；用户名与退出保持现有展示和 CSRF POST 退出；依靠 `navbar-end` 右对齐与左侧业务菜单形成明确间隔。
4. 小屏下左右分区仍可识别：允许换行，但业务链与账号区不能混成一串无标签菜单；不引入抽屉。
5. 路由、鉴权、文案「公司 / Webhook 投递 / 设置 / 退出」不变；只改壳层布局与信息分组。

## 3. 非目标

- 不改登录页未登录态；未登录页本来就没有这套业务顶栏。
- 不新增多级下拉账号菜单。默认保持扁平按钮；仅当「待确认 2」明确要求时才用 daisyUI `dropdown` 收纳账号项，且不改变功能。
- 不改 Webhook / 公司 / 设置页面本身的布局与内容。
- 不做暗色主题或多套顶栏皮肤。
- 不引入抽屉、前端构建工具、npm 依赖或新的 JavaScript 框架。
- 不改 `nav` 上下文值的含义，不改 `auth`、CSRF、JWT、`/logout`、`/settings` 等服务端逻辑。

## 4. 方案

### 4.1 顶部信息架构

调整后的顶栏结构：

```text
┌─────────────────────────────────────────────────────────────────────┐
│ [品牌 GitHub 工作流]  公司  Webhook 投递        设置  [头像] 用户名  退出 │
│ └──────────── navbar-start（业务）────────────┘  └──── navbar-end（账号）────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

- 业务导航只包含 `公司`、`Webhook 投递`，与品牌同处 `navbar-start`。
- 账号区包含 `设置`、头像、用户名、退出，全部归入 `navbar-end`。
- 两个区域在两个独立 `<nav>` landmark 中，分别使用 `aria-label="业务导航"` 和 `aria-label="账号导航"`，供读屏和测试识别。
- 不再输出当前的 `navbar-center` 容器及其三项中间菜单。

### 4.2 模板结构改造

改造集中在 `app/templates/base.html` 的 `<header>`：

1. `navbar` 外层继续保留 `flex-wrap`、`max-w-7xl` 和现有内边距；允许窄屏换行。
2. `navbar-start` 保留 `w-auto flex-none`，内部由「品牌链接 + 业务 `<nav>`」组成；业务 `<nav>` 内继续使用 `ul.menu.menu-horizontal.menu-sm`。
3. 删除 `navbar-center` 整段。
4. `navbar-end` 保留 `w-auto flex-none gap-2`，内部依次为「账号导航 `<nav>`（设置）+ 头像 + 用户名 + 退出表单」。
5. 右侧账号区增加向左推的间距：桌面用 `ms-auto`；窄屏用 `basis-full justify-end` 让其独占一行并右对齐，`sm` 及以上恢复 `basis-auto`，与左侧同处一行。断点可按实际宽度微调，但「窄屏账号区独立成行、右对齐」的规则不变。
6. `menu-active` / `aria-current` 的 Jinja 条件原样迁移，不改变 `nav` 值来源。

示意结构（实现时可调整类名组合，但分区与语义必须保留）：

```html
<div class="navbar mx-auto max-w-7xl flex-wrap gap-x-4 gap-y-1 px-4 py-1.5 sm:px-6 lg:px-8">
  <div class="navbar-start w-auto flex-none flex-wrap items-center gap-x-3 gap-y-1">
    <a href="/"><!-- 品牌：图标 + GitHub 工作流 + 内部运维台 --></a>
    <nav aria-label="业务导航">
      <ul class="menu menu-horizontal menu-sm gap-1 px-1">
        <li><a ... href="/">公司</a></li>
        <li><a ... href="/deliveries">Webhook 投递</a></li>
      </ul>
    </nav>
  </div>
  <div class="navbar-end w-auto flex-none basis-full justify-end gap-2 sm:basis-auto sm:ms-auto">
    <nav aria-label="账号导航">
      <ul class="menu menu-horizontal menu-sm gap-1 px-1">
        <li><a ... href="/settings">设置</a></li>
      </ul>
    </nav>
    <!-- 头像 + 用户名 + 退出表单，保持现有结构与 CSRF 隐藏字段 -->
  </div>
</div>
```

`设置` 只在账号导航中出现一次，业务导航中不得再出现 `设置` 链接。

### 4.3 高亮与路由

路由与 `nav` 上下文不变，模板继续按现有值判断：

| 页面 | 传入 `nav` | 高亮项 |
| --- | --- | --- |
| 公司列表 `/`、公司 / 仓库 / Issue 页面 | `companies` | 左侧 `公司` |
| Webhook 投递 `/deliveries` | `deliveries` | 左侧 `Webhook 投递` |
| 设置 `/settings` | `settings` | 右侧 `设置` |

- 当前项仍同时输出 `menu-active` 与 `aria-current="page"`，非当前项不输出。
- `设置` 移到右侧后，其高亮规则与其他项完全一致；不因分区不同而新增第二套类名。
- 品牌链接 `/` 不加 `aria-current`，保持现状。

### 4.4 右侧账号区行为

- `设置`：普通 `<a href="/settings">`，当前页高亮；不改为按钮、不新增确认。
- 头像：保持现有 daisyUI `avatar` + `avatar-placeholder` 结构，首字母取 `user.username`，`aria-hidden="true"`。
- 用户名：保持现有行为，桌面宽度显示文本，小屏隐藏文本仅保留头像；展示内容仍为 `user.username`。
- `退出`：继续是 `form method="post" action="/logout"`，带隐藏 `csrf_token`，按钮继续使用 `btn btn-ghost btn-sm` 与 `data-gw-submit`；文案和图标不变。
- 本迭代不把设置、用户名或退出做成 JavaScript 弹层；如后续确认使用 `dropdown`，下拉内容仍复用上述真实链接与 POST 表单。

### 4.5 响应式与小屏

- **`sm` 及以上（默认桌面 / 平板）**：左侧品牌 + 业务菜单靠左，右侧设置 + 头像 + 用户名 + 退出靠右；两组之间由 `ms-auto` 留出空白，不增加分隔线等额外装饰。
- **`sm` 以下（窄屏）**：
  - 账号区通过 `basis-full justify-end` 独占第二行并右对齐，与左侧业务区形成上下两段。
  - 左侧品牌与业务菜单允许在 `navbar-start` 内自行换行；换行后仍处于左对齐的业务区，不脱离业务导航。
  - 账号区各项保持扁平排列，允许在极端窄屏下继续换行；退出按钮始终可点击，不做重叠定位。
- 不引入抽屉、折叠菜单或悬浮按钮。
- 顶栏仍为 `sticky`；窄屏换行导致高度增加时，由文档流自然撑开，不使用固定高度或 `position: fixed` 覆盖内容。

### 4.6 无障碍

- 两个 `<nav>` 分别有唯一的 `aria-label`：`业务导航`、`账号导航`，避免出现两个同名导航地标。
- 当前项高亮不只靠颜色：保留 `aria-current="page"`，`menu-active` 只做视觉强化。
- 头像首字母继续 `aria-hidden`；退出按钮保留可见文本「退出」（小屏隐藏文本时仍保留可访问名称，必要时以 `aria-label` 补齐，不改变视觉文案）。
- 保留现有 focus ring、`cursor-pointer` 与键盘可达性；不新增仅靠 hover 才出现的操作。
- 不改变 `viewport` 设置，不禁止缩放。

### 4.7 与基石的关系

本迭代改变的是已登录全局壳的顶栏分组，属于 [`docs/architecture/design.md`](../architecture/design.md)「界面契约 → 全局壳（已登录）」中顶栏描述的变更。实现 PR 应同步把该表从「左侧品牌 / 中间主导航（含设置）/ 右侧用户名与退出」更新为「左侧品牌 + 业务导航 / 右侧设置 + 用户名与退出」，避免基石与实现不一致。

本文件只描述增量，不替代基石；除上述顶栏描述外，不改动基石其它内容。

## 5. 影响面

| 范围 | 影响 |
| --- | --- |
| `app/templates/base.html` | 唯一产品代码改动：删除 `navbar-center`，拆分业务导航与账号导航，调整 `navbar-end` 的响应式类 |
| `docs/architecture/design.md` | 实现时同步「全局壳（已登录）」顶栏行，保持基石与页面一致 |
| `tests/test_ui.py` | 更新 / 增加顶栏断言：业务导航含 `公司`、`Webhook 投递` 且不含 `设置`；账号导航含 `设置`；`/settings` 页 `aria-current` 落在账号区；退出表单仍带 CSRF |
| 路由与鉴权 | 无变化；`/`、`/deliveries`、`/settings`、`POST /logout` 的路径、方法与权限保持原样 |
| 数据模型 / 任务流程 | 无变化；不新增字段、迁移、状态或任务 |
| 其它模板 | 不改；未登录页、公司 / 仓库 / Issue / 投递页面内容不变 |

风险与约束：

- 本次是纯模板重排，主要风险是小屏换行后点击区域被挤压；验收需在窄视口实际检查。
- 若把 `设置` 移出中间菜单后仍残留旧链接，会出现重复导航项；模板中 `设置` 只允许出现一次。
- 两个导航地标必须有不同 `aria-label`，否则读屏无法区分左右分区。
- 不新增任何外部资源或脚本，不改变现有 CSP / 静态资源策略。

## 6. 验收

### 6.1 功能与布局

- [ ] 桌面宽度下：左侧可见品牌 + `公司` + `Webhook 投递`；右侧可见 `设置` + 用户（头像 / 用户名）+ `退出`；`设置` 不与 `公司` / `Webhook 投递` 同处一个菜单组。
- [ ] 当前路由下对应项高亮正确：`公司`、`Webhook 投递`、`设置` 分别在其页面输出 `menu-active` 与 `aria-current="page"`，且只有当前项输出。
- [ ] `退出` 仍是带 CSRF 隐藏字段的 POST `/logout`，可正常退出；用户名展示与现网一致（桌面显示文本，小屏保留头像）。
- [ ] 小屏下业务区与账号区仍可区分：账号区独立成行并右对齐，业务菜单保持左侧分组；无严重重叠、遮挡或无法点击。
- [ ] 页面上不存在重复的 `设置` 链接；`navbar-center` 不再承载导航内容。

### 6.2 自动化测试

- [ ] 页面渲染断言覆盖：
  - `aria-label="业务导航"` 分组内含 `href="/"` 的 `公司` 与 `href="/deliveries"` 的 `Webhook 投递`；
  - `aria-label="账号导航"` 分组内含 `href="/settings"` 的 `设置`；
  - 退出表单仍包含 `name="csrf_token"` 与 `action="/logout"`；
  - `/settings` 页面 `aria-current="page"` 出现在账号导航的 `设置` 项上。
- [ ] 现有 UI 组件断言（`navbar`、`menu`、`breadcrumbs` 等）继续通过。
- [ ] 全量相关测试通过，无新增依赖或构建步骤。

### 6.3 交付

- [ ] 实现走 `dev_{number}` 分支并创建 PR。
- [ ] 实现 PR 同步更新基石「全局壳（已登录）」的顶栏描述。

## 7. 待确认

1. **「设置」的归属**：本 Issue 默认把「设置」固定放在右侧账号区；若产品希望「设置」继续留在左侧业务区，实现前需改口，模板与测试断言随之调整。
2. **小屏是否收纳账号区**：是否在窄屏把右侧收成头像 `dropdown`（内含设置 / 用户名 / 退出）。默认**不做**，保持扁平按钮；若确认要做，仍需保留真实链接、CSRF POST 退出和当前页高亮，并相应更新小屏验收与测试。
