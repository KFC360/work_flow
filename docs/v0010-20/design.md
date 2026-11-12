# Issue 正文折叠预览与生成前设计文档卡内编辑（v0010 / Issue #20）

- 迭代：`v0010`，对应 GitHub Issue `#20`
- 文档路径：`docs/v0010-20/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：**Issue 详情页交互增量 + 设计文档人工编辑入口收敛**。不新增流程状态名，不改写文档 / 生成代码的任务、git、提交、推送与 PR 边界，不新增数据库表或迁移。

## 1. 背景

### 1.1 当前缺口

Issue 详情页存在两个日常使用问题：

1. **Issue 正文始终全文展开**。`/issues/{id}` 的正文卡直接渲染完整 Markdown；长 Issue 会占满左栏，把设计文档、审阅卡和右侧任务区推到很下面。多数时候只需要看正文开头和结尾，再决定是否展开细读。
2. **设计文档只能整份重跑或等待生成**。当前设计文档虽然已有「编辑文档」入口，但它跳到独立页面 `/issues/{id}/design/edit`，且保存前置只允许 `pending_codegen`；操作员无法在详情页卡片内直接做小幅人工修订，也不方便在「写文档失败、准备重试」时先修文档。

### 1.2 现状核对

以本仓库现有实现为准：

| 位置 | 现状 | 与本迭代的关系 |
| --- | --- | --- |
| `app/templates/issue_detail.html` | 正文卡只渲染 `issue_body_html`（失败时回退 `<pre>`），没有折叠控件 | 增加默认折叠、预览与展开控件 |
| `app/templates/partials/head_assets.html` | `.md-content` 已有字号、行高、代码块、表格、滚动等样式 | 折叠测量与预览必须复用同一套排版样式 |
| `app/services/markdown_render.py` | Issue 正文与设计文档均服务端 Markdown + nh3 白名单消毒；正文标题从 `h3` 起 | 折叠只作用于渲染后的 DOM，不改变消毒和渲染链 |
| `app/templates/issue_detail.html` | 设计文档卡头部有「编辑文档」链接，跳到独立编辑页 | 改为卡片内编辑态；保存接口复用现有 POST |
| `app/api/v1/issues.py` | `_design_block_reason` 只允许 `pending_codegen`；GET/POST `/issues/{id}/design/edit` 已有 | 编辑条件拆成独立判定；GET 改为详情页编辑态；POST 增加 409 |
| `app/api/v1/issues.py` | `save_design_edit` 写 `design_doc_text`、清空 `doc_approved_at`、写 `human_edit` 审计，303 回详情 | 保留这些写回语义，只调整入口、返回码和校验 |
| `app/templates/design_edit.html` | 独立编辑页，含大号 textarea 与保存 / 取消 | 改为详情卡内编辑；旧模板在实现中退役或仅保留重定向兼容 |
| `app/crud/job.py` | `has_active_for_issue` 已能判断 queued / running 任务 | 编辑保存前复用，阻止任务进行中写库 |
| `tests/test_design_review.py` | 已有编辑页 200、保存 303、活动任务 303、清批准、消毒等用例 | 需要改为卡片编辑态、409 与新的页面断言 |

### 1.3 问题归纳

本迭代只解决「看得省空间」和「改得动库内文档」两件事：

- 正文折叠是**展示层**能力，不改 Issue 数据，不改后端渲染，不持久化个人偏好；
- 人工编辑是**生成代码前**的文档写回能力，必须与现有批准失效规则一致：任何人工写回正文都清空 `doc_approved_at`；
- 一旦进入生成代码阶段，文档就是实现依据，编辑入口必须关闭，服务端也必须拒绝写库。

## 2. 目标

### 2.1 Issue 正文卡片可折叠，默认折叠

- 正文卡支持展开 / 折叠，**首次加载默认折叠**；刷新后仍默认折叠，本迭代不持久化展开偏好（不写 cookie、localStorage、URL 展开参数）。
- 折叠态按**渲染后可视行**显示：
  - 第一行；
  - 中间省略标记（如 `…`）；
  - 最后两行；
  - 总可视行数 ≤ 3 时：显示全部行，不出现省略标记，也不显示无意义的折叠控件。
- 「可视行」以服务端渲染、消毒后的 DOM 为准，不以 Markdown 源文 `\n` 计。测量方式、块级元素计行规则和固定高度规则见 4.2。
- 展开态继续使用现有全文 Markdown 渲染；消毒、标题层级、代码块 / 表格内部滚动规则不变。
- 折叠控件放在正文卡标题行；`aria-expanded` 正确，按钮文案在「展开全文 / 收起全文」之间切换。
- 无正文时保持现有空状态（「该 Issue 没有正文。」），不出现折叠按钮。

### 2.2 生成代码前允许人工编辑设计文档

- 当 Issue 已有设计文档，且尚未进入生成代码及之后时，详情页设计文档卡片提供「编辑」入口。
- 点击后在**设计文档卡片内**切换为 Markdown 源文编辑态：textarea（或等价控件）显示库内 `design_doc_text`，提供「保存 / 取消」。
- 取消恢复只读渲染，不写库、不发请求；保存走 POST + CSRF，成功后页面立即显示新正文。
- 编辑对象是库内 `design_doc_text`；`design_doc_path`、`iteration_no`、`branch_name` 不变。
- 保存成功：
  - 写回 `design_doc_text`；
  - 若表上存在 `doc_approved_at` 列，则置为 `NULL`；
  - 按现有规则重新 Markdown + nh3 渲染；
  - flash 提示「已保存，需重新批准」。
- 一旦进入生成中 / 已生成 / 已建 PR，或 `codegen_phase != none`：隐藏编辑入口；非法 POST 返回 **409**，不写库。
- 有进行中的编写 / 修订 / 生成任务时拒绝保存，返回 409 并提示任务进行中。
- 保存内容仍走现有消毒渲染；长度上限在 4.3.4 写死。

### 2.3 与基石的关系

- 本迭代不改变 `issue.status`、`doc_approved_at` 的状态机含义，只增加「生成前人工编辑」入口和正文折叠展示。
- 实现 PR 需要同步更新基石中 Issue 详情页、设计文档编辑与异常 / 测试章节；本文件只描述增量，不替代基石。

## 3. 非目标

- 不做完整「审阅批准 / design_feedback / 待确认结构化」流程；已有专门迭代和实现，本迭代不重复。
- 不做多人协同编辑、OT、自动保存草稿、版本树、diff 对比、回滚。
- 不改变「重新编写文档」「请代理修订」「生成代码」的入队条件；本迭代只增加折叠与人工编辑。
- 不改变批准门禁：人工编辑保存会清空批准，但本迭代不新增批准 / 取消批准逻辑。
- 不把人工编辑同步写回 GitHub Issue 正文，也不提交到默认分支。
- 不持久化正文折叠展开偏好。
- 不改变 Worker、代理提示词、git 提交、推送、创建 PR 的边界。
- 不新增前端构建工具、npm 依赖或新测试框架；折叠脚本为原生 JS。

## 4. 方案

### 4.1 总体边界

#### 4.1.1 正文折叠状态

正文折叠只有两个客户端状态，不落库：

```text
collapsed（默认）
  ├─ 点击「展开全文」→ expanded
expanded
  └─ 点击「收起全文」→ collapsed
```

- 服务端不保存状态；刷新、换设备、从列表返回都按 collapsed 渲染。
- 正文总可视行 ≤ 3 时不存在 collapsed 状态，直接显示全文并隐藏控件。
- 无正文时不存在折叠状态。

#### 4.1.2 设计文档编辑可用性

编辑可用性独立于「审阅与批准」卡；使用一个新的判定函数，不复用只服务 `pending_codegen` 的审阅前置。

| 条件 | 是否可编辑 | 说明 |
| --- | --- | --- |
| Issue 已软删 | 否 | 详情 404，不提供入口 |
| `kind != feature` | 否 | 人工介入不进入文档流程 |
| `github_state != open` | 否 | 关闭的 Issue 不写文档 |
| `design_doc_text` 为空 / 全空白 | 否 | 没有可编辑对象 |
| `codegen_phase != none` | 否 | 已进入生成代码及之后 |
| `status = pending_codegen` | 是 | 仍要求无 queued / running 任务 |
| `status = failed` 且 `failed_action in (write_doc, revise_doc)` | 是（默认，见待确认） | 写文档 / 修订失败后可先人工修文档再重试 |
| `status = failed` 且其它 `failed_action` | 否 | 尤其 `generate_code` 已尝试生成，不能再改文档 |
| `status in (drafting, generating, generated, pr_opened)` | 否 | 进行中或已生成 |
| 有 queued / running 任务 | 否 | 复用 `job_crud.has_active_for_issue`，任何活动任务都拒绝 |
| 已有 `doc_approved_at` | 是 | 允许编辑；保存后清空批准 |

编辑入口在不可用时**隐藏**，不显示灰色按钮；操作员通过「重新编写文档」或等待任务完成处理。若直接用 `?edit=1` 访问不可编辑状态，GET 303 回详情并 flash 原因。

### 4.2 Issue 正文折叠

#### 4.2.1 页面结构

正文卡保留现有 daisyUI `card` 外观，标题行增加折叠按钮；正文拆成「预览容器 + 全文容器」：

```html
<section class="card card-border bg-base-100 shadow-sm"
         aria-labelledby="issue-body-title" data-gw-issue-body>
  <div class="card-body p-5">
    <div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
      <h2 id="issue-body-title" class="card-title text-base">Issue 正文</h2>
      <button type="button" id="issue-body-toggle"
              class="btn btn-xs btn-ghost gap-1"
              aria-expanded="false"
              aria-controls="issue-body-preview issue-body-full"
              data-gw-body-toggle hidden>展开全文</button>
    </div>

    <div id="issue-body-preview" data-gw-body-preview hidden aria-hidden="true">
      <!-- JS 填充：首行槽、省略行、末两行槽 -->
    </div>

    <div id="issue-body-full" data-gw-body-full hidden>
      <!-- 服务端渲染的 issue_body_html；失败时回退 <pre> -->
    </div>

    <noscript>
      <style>
        [data-gw-body-full] { display: block !important; }
        [data-gw-body-preview], [data-gw-body-toggle] { display: none !important; }
      </style>
    </noscript>
  </div>
</section>
```

说明：

- 控件放在卡片标题行，使用原生 `button`，不直接使用 daisyUI `collapse` 的关闭语义。daisyUI `collapse` 在关闭时会隐藏全部内容，无法呈现「首行 + 省略 + 末两行」预览；视觉仍复用 daisyUI 的 `card`、`btn`、`badge`、`alert`。
- 全文容器由服务端直接输出已消毒 HTML；预览容器只由 JS 克隆生成，不接收新内容，不改变消毒边界。
- `<noscript>` 让禁用 JS 的浏览器直接显示全文并隐藏折叠控件；JS 异常时脚本的 `catch` 同样恢复全文，避免内容永久隐藏。
- 正文为空时不渲染预览 / 全文 / 按钮，只显示现有空状态。

#### 4.2.2 「可视行」测量规则

测量对象是**最终宽度、最终字体、最终 `.md-content` 样式下的 DOM**，在服务端 Markdown + nh3 消毒之后执行。实现放在 `issue_detail.html` 的 `{% block scripts %}`，使用原生 JS，不引入依赖。

设：

- `L` = `.md-content` 的计算 `line-height`；若为 `normal`，用 `1.7 × font-size` 兜底（与现有 `.md-content { line-height: 1.7; }` 一致）。
- `root` = 全文容器内的渲染结果（`.md-content`，或渲染失败时的 `<pre>`）。

测量步骤：

1. 按块容器递归遍历 `root`，避免同一行被父子元素重复计数。
2. 文本节点：用 `Range.selectNodeContents(textNode)` 后 `range.getClientRects()` 取每个非零高度的矩形；按 `top` 排序，`|top - 当前行 top| <= 2px` 的矩形合并为同一可视行（处理同一行内的加粗、链接、行内代码等）。
3. 块级元素按以下规则展开为行单元，不再下钻其内部文本：

| 元素 | 计行规则 |
| --- | --- |
| `p`、`h3`–`h6`、`li` 的直接文本与行内子元素 | 按文本矩形合并后的可视行数计 |
| `blockquote` | 递归其内部块与文本，按实际可视行计 |
| `pre` | `max(1, ceil(pre.scrollHeight / L))`；代码块 `white-space: pre`，每个源码行就是一个可视行，横向滚动不增加行数 |
| `table` | 每个 `tr` 计 `max(1, ceil(tr.getBoundingClientRect().height / L))`；一行表格无论单元格是否换行，都按整行高度折算为 1 行或多行 |
| `hr` | 1 行 |
| `ul` / `ol` | 由内部 `li` 的行数累加，列表容器本身不额外计行 |
| `img` / `video` 等替换元素 | `max(1, ceil(rect.height / L))`；当前 nh3 白名单不含 `img`，此规则只作为未来放开白名单时的兜底 |
| 渲染失败回退的 `<pre>` | `max(1, ceil(pre.scrollHeight / L))`；`whitespace-pre-wrap` 的换行按实际排版行计 |

4. 空行规则：没有可见文字、且高度为 0 的矩形不计行；`<br>` 造成的实际空行按 1 行计。块与块之间的外边距不是可视行，不计入行数。
5. 得到有序数组 `lines[]`，每项至少包含 `top`、`bottom`；`total = lines.length`。
6. 若 `total <= 3`：不折叠，显示全文，隐藏预览与按钮。
7. 若 `total > 3`：进入折叠态，首行取 `lines[0]`，末两行取 `lines[total - 2]`、`lines[total - 1]`。

这套规则的关键约束：

- **行数只由渲染后排版决定**，不读 `issue.body` 的换行，也不按 Markdown 源文行数估算。
- **块不可拆时按整块折算为一行或多行**，不会因为代码块或表格内部结构被误算成 0 行。
- 表格行、代码块行即使实际像素高度大于 `L`，也按其折算的行数进入预算；预览槽位固定为 `L`，超出部分裁切，不让折叠高度随内容跳动。

#### 4.2.3 预览构造与固定高度

折叠态高度固定，不随正文内容变化：

```text
折叠高度 H = 3 × L + E
  ├─ 首行槽：1 × L
  ├─ 省略行：E（固定 1.25rem，不计入 3 行预算）
  └─ 末两行槽：2 × L
```

实现方式：

1. 用全文容器的 `innerHTML` 克隆两份到预览容器：`top clone` 与 `bottom clone`，均带 `.md-content`（回退 `<pre>` 时带对应类）。
2. 给预览克隆加 `gw-body-preview-compact`，把块级元素的外边距压为 0（只影响预览排布，不改变 4.2.2 的原始计行结果）。这样末两行不会被块间距挤出 2L 槽位。
3. 在克隆上按同一测量函数取 `cloneLines`：
   - 首行槽内层 `translateY(-cloneLines[0].top)`；
   - 末两行槽内层 `translateY(-cloneLines[total - 2].top)`；
   - 两个槽均为 `overflow: hidden`，高度分别为 `L` 和 `2L`。
4. 预览里的链接、按钮等可聚焦元素设置 `tabindex="-1"`；预览容器 `aria-hidden="true"`。预览只用于视觉扫读，交互入口是标题行的折叠按钮。
5. 省略行始终显示 `…`，并带 `aria-label` 或可见说明「中间内容已省略」；`total > 3` 时才出现。
6. 折叠高度固定为 `H`，不因为首块是代码块、表格或图片而扩张；被槽位裁切的块内容不额外撑高。

#### 4.2.4 默认态、重测与无 JS 降级

- 服务端默认输出折叠标记：按钮 `aria-expanded="false"`，全文容器 `hidden`；脚本初始化后按测量结果决定：
  - `total <= 3`：显示全文，隐藏预览和按钮；
  - `total > 3`：显示预览和按钮，保持折叠；
  - 无正文：不渲染这些节点。
- 测量在 `DOMContentLoaded` 后执行一次；同时监听：
  - `document.fonts.ready`（字体加载后行宽变化）；
  - 卡片内容区 `ResizeObserver`（窗口缩放、侧栏变化）；
  - 统一 150ms 防抖，重新测量并更新预览，不改变当前 expanded / collapsed 选择。
- 用户点「展开全文」：全文容器 `hidden = false`，预览隐藏，按钮 `aria-expanded="true"`，文案「收起全文」；点「收起全文」反向操作。
- 无 JS：`<noscript>` 直接显示全文、隐藏预览和按钮。JS 异常：`try/catch` 恢复全文并隐藏预览 / 按钮。
- 状态轮询只替换 `#issue-live-status` 和日志，不替换正文卡，不会重置折叠状态；只有整页刷新才回到默认折叠。

#### 4.2.5 无障碍与空状态

- 折叠按钮有可见文字，不只靠图标；`aria-expanded` 与当前状态一致；`aria-controls` 指向预览与全文容器。
- 展开 / 折叠不移动焦点；按钮始终在标题行，键盘可直接操作。
- 预览 `aria-hidden="true"`；折叠时给正文卡一个 `sr-only` 说明「正文已折叠，共 N 行，使用标题行的展开全文按钮查看全部」，避免屏幕阅读器只读到空预览。
- 短正文（`total <= 3`）不显示控件，不产生「无法展开」的噪声。
- 无正文保持现有「该 Issue 没有正文。」文案，不出现省略号或空卡片。

### 4.3 生成前设计文档卡内编辑

#### 4.3.1 路由与状态

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/issues/{id}?edit=1#design-doc` | 在详情页设计文档卡内渲染编辑态；不可编辑时 303 回详情并 flash |
| GET | `/issues/{id}/design/edit` | 兼容旧链接：303 到 `/issues/{id}?edit=1#design-doc`；不可编辑同样回详情 |
| POST | `/issues/{id}/design/edit` | 保存库内 Markdown；复用现有保存接口，不新增写库路径 |

选择服务端 `?edit=1` 渲染编辑态的理由：

- 与现有「普通表单 + 服务端渲染」的交互方式一致，不依赖 JS；
- 取消只是链接回详情，天然不写库；
- 保存失败可以 200 重新渲染编辑态并保留用户输入；
- 旧的 `/design/edit` 地址保留重定向，避免书签和旧测试突然 404。

如果后续需要纯客户端切换，可保留同一个 POST 保存接口，只替换入口的渲染方式；见「待确认」。

#### 4.3.2 入口与判定

新增独立判定（建议放在 `app/services/design_review.py`，便于 pytest 直接覆盖）：

```text
可编辑 = 存在 Issue
        AND deleted_at IS NULL
        AND kind = feature
        AND github_state = open
        AND design_doc_text 去空白后非空
        AND codegen_phase = none
        AND (
              status = pending_codegen
              OR (status = failed AND failed_action IN (write_doc, revise_doc))
            )
        AND 无 queued / running 任务
```

说明：

- `doc_approved_at` 不参与可编辑判定；已批准的文档也允许编辑，保存时清空批准。
- 活动任务判断复用 `job_crud.has_active_for_issue`，任何 queued / running 都拒绝，覆盖 write / revise / generate 三类。
- `failed_action = generate_code` 即使 `codegen_phase` 仍为 `none` 也拒绝，因为已经尝试进入生成阶段；见「待确认」。
- `failed_action = revise_doc` 默认允许编辑：此时正文已存在，操作员可以先人工修文档再决定是否重试修订。

#### 4.3.3 保存语义

保存成功时，在一个事务内：

| 字段 / 对象 | 变更 |
| --- | --- |
| `issue.design_doc_text` | 写入提交的 Markdown 原文 |
| `issue.doc_approved_at` | 若列存在，置 `NULL` |
| `issue.design_doc_path` | 不变 |
| `issue.iteration_no` | 不变 |
| `issue.design_source_updated_at` | 不变（沿用现有行为，stale 警告仍按原规则提示） |
| `issue.status` | 不变（`pending_codegen` 仍是 `pending_codegen`；`failed` 仍是 `failed`） |
| `issue.codegen_phase` | 不变（必须为 `none`） |
| `design_feedback` | 追加一条 `kind = human_edit` 审计，`doc_sha256` 用新正文计算，`body` 记录字符数 |
| `job` | 不创建、不入队 |
| Git / GitHub | 不提交、不推送、不创建 PR、不同步 Issue 正文 |

保存后 303 回 `/issues/{id}`（不再带 `edit=1`）并 flash「已保存，需重新批准」；详情页立即用新 `design_doc_text` 渲染。

如果 `doc_approved_at` 列在目标库中不存在（未迁移旧库），保存逻辑通过 `Issue.__table__.columns` 检测并跳过清空，同时记录 warning；发布前应确保 v0009 迁移已应用，跳过仅用于兼容，不作为目标状态。

#### 4.3.4 校验、错误与长度

| 情况 | 响应 | 是否写库 |
| --- | --- | --- |
| CSRF 缺失 / 失效 | 沿用现有 CSRF 拒绝行为 | 否 |
| Issue 不存在 / 已软删 | 404 | 否 |
| 不满足 4.3.2 的任一状态条件 | **409**，渲染详情页只读态并显示 `alert-error` 原因 | 否 |
| 有 queued / running 任务 | **409**，提示「有进行中的任务，完成后可编辑」 | 否 |
| `codegen_phase != none` | **409**，提示「已进入生成代码阶段，不能编辑」 | 否 |
| `design_doc_text` 去空白后为空 | 200，详情页编辑态 + 字段错误「设计文档不能为空」 | 否 |
| 超过长度上限 | 200，详情页编辑态 + 字段错误 | 否 |
| 正常保存 | 303 回详情 + flash | 是 |

长度上限：

- 新增常量 `MAX_DESIGN_DOC_CHARS = 262_144`（字符数，不是字节数）；
- 服务端用 Python `len()` 校验，超过即拒绝；
- textarea 同时带 `maxlength="262144"` 作为客户端提示，但服务端仍是最终门禁；
- 数据库继续使用现有 `Text` 列，不新增迁移；不引入请求体级别的额外限制。

HTML 消毒：

- 保存只写 Markdown 原文，渲染仍走 `render_design_doc`；
- 链接仅 `http` / `https`，`rel="noopener noreferrer"`；脚本、`javascript:` 等继续被 nh3 白名单剥离；
- 渲染失败时沿用现有转义 `<pre>` 回退；
- textarea 由 Jinja 自动转义，不把用户输入当 HTML 输出。

#### 4.3.5 卡片内交互

只读态：

- 设计文档卡头部：标题、路径、迭代号；可编辑时右侧显示「编辑文档」链接，指向 `?edit=1#design-doc`。
- 文档正文保持现有 `md-content max-h-[32rem] overflow-auto` 渲染。
- 不可编辑时不显示「编辑文档」；已有「重新编写文档」按钮仍在操作区，两者语义不同，不互相替代。

编辑态（`?edit=1`）：

- 卡片头部追加「编辑中」badge，并显示「保存后需重新批准」的说明文字。
- 主体替换为表单：

```html
<form method="post" action="/issues/{{ issue.id }}/design/edit">
  <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />
  <label for="design_doc_text">设计文档 Markdown</label>
  <textarea id="design_doc_text" name="design_doc_text"
            rows="24" maxlength="262144"
            class="textarea textarea-bordered h-[32rem] w-full font-mono text-sm leading-6"
            required>{{ design_doc_text }}</textarea>
  <p>保存后仍按现有 Markdown + HTML 白名单消毒渲染；不会提交到 Git。</p>
  <button type="submit" class="btn btn-primary" data-gw-submit>保存</button>
  <a class="btn btn-ghost" href="/issues/{{ issue.id }}#design-doc">取消</a>
</form>
```

- 取消是普通链接，不触发 POST，不写库。
- 保存按钮防双提交，沿用 `data-gw-submit` 的 loading / disabled 逻辑。
- 字段错误时 textarea 加 `textarea-error`、`aria-invalid="true"`，并聚焦到 textarea；页面顶部同时有 `alert-error` 摘要。
- `stale_doc` 警告在编辑态继续显示，提醒保存只改库内文档、不同步 Issue 新正文。
- 编辑态不显示文档预览区；保存成功回到只读态后再渲染新正文。

#### 4.3.6 与「重新编写文档」「请代理修订」的关系

| 入口 | 作用 | 是否清批准 | 是否调用代理 | 本迭代变化 |
| --- | --- | --- | --- | --- |
| 编辑文档 | 人工直接改库内 Markdown | 是 | 否 | 改为卡内编辑；放宽到写文档 / 修订失败可重试时 |
| 重新编写文档 | 代理整份重写 | 是 | 是 | 不改变入队条件和确认框 |
| 请代理修订 | 按意见代理修订 | 是 | 是 | 不改变 |
| 生成代码 | 按文档生成代码 | 不适用 | 是 | 不改变；生成开始后编辑入口消失 |

- 人工编辑不自动把未处理的 `design_feedback` 标为 `resolved_at`；它只是正文写回，不等同于「按意见修订完成」。
- 人工编辑不改变失败状态；`failed` 行保存后仍是 `failed`，操作员可继续用原有重试入口。是否自动清除 `last_error` / 回到 `pending_codegen` 见「待确认」。

### 4.4 实现落点

新增 / 修改：

- `app/api/v1/issues.py`
  - 新增编辑可用性判定调用；
  - 详情上下文增加 `design_edit_available`、`design_edit_mode`、`design_edit_text`、`design_edit_error`；
  - `issue_detail` 支持 `?edit=1`；
  - `design_edit` GET 改为重定向到 `?edit=1#design-doc`；
  - `save_design_edit` 使用新判定，非法状态返回 409，空 / 超长返回 200 编辑态，成功保持现有写回与审计。
- `app/services/design_review.py`
  - 新增 `MAX_DESIGN_DOC_CHARS` 与 `design_edit_block_reason(db, issue)`（或等价命名）；
  - 不改变现有批准、待确认、反馈逻辑。
- `app/crud/job.py`
  - 默认复用 `has_active_for_issue`；若实现阶段需要精确过滤，可增加只匹配 `write_doc` / `revise_doc` / `generate_code` 的查询，但语义不得放宽。
- `app/templates/issue_detail.html`
  - 正文卡预览 / 全文 / 折叠按钮；
  - 设计文档卡只读 / 编辑两态；
  - `{% block scripts %}` 增加正文测量脚本（与现有轮询脚本并列，互不依赖）。
- `app/templates/partials/head_assets.html`
  - 增加 `.gw-body-preview`、槽位、省略行、紧凑克隆的少量 CSS；不改变 `.md-content` 既有排版。
- `app/templates/design_edit.html`
  - 不再作为主入口；实现 PR 可删除并更新测试，或保留为重定向后的未引用模板。建议删除，避免两套编辑 UI 漂移。
- `tests/test_design_review.py`、`tests/test_ui.py`
  - 更新编辑入口、409、卡片编辑态、清批准、消毒、长度与折叠静态断言。
- `docs/architecture/design.md`、`docs/README.md`
  - 实现 PR 同步基石：Issue 详情正文折叠、设计文档卡内编辑、409 异常与测试项。
- 不新增 Alembic 迁移、环境变量、数据库列或前端依赖。

### 4.5 测试与验收方式

pytest 覆盖：

- 编辑可用性矩阵：`pending_codegen`、`failed + write_doc`、`failed + revise_doc`、`failed + generate_code`、`generating`、`generated`、`pr_opened`、`codegen_phase != none`、活动任务、空正文。
- `GET ?edit=1` 可编辑时 200 且卡内出现 textarea；不可编辑时 303 回详情并带原因。
- 旧 `GET /issues/{id}/design/edit` 303 到 `?edit=1`。
- POST 保存成功：正文更新、`doc_approved_at` 清空、`design_doc_path` / `iteration_no` 不变、状态不变、`human_edit` 审计、303 回详情。
- POST 非法状态：409，正文与批准不变。
- POST 空正文 / 超长：200，字段错误，正文不变。
- POST 无 CSRF：沿用现有拒绝行为，不写库。
- 消毒：提交 `<script>`、`javascript:` 链接后详情不出现可执行内容；渲染失败回退 `<pre>`。
- 有活动任务时 POST 409。
- UI 静态断言：正文卡有 `data-gw-body-preview`、`data-gw-body-full`、`aria-expanded`、`aria-controls`；无正文不出现按钮；短正文由脚本隐藏按钮；设计文档卡有「编辑文档」链接与编辑态 textarea / 保存 / 取消。
- 回归：批准、待确认、反馈、修订、生成代码 / PR 测试不因编辑判定拆分而改变。

浏览器手工核对（当前仓库无浏览器测试框架，不强行引入）：

- 长正文：默认折叠，首行 + `…` + 末两行；点击展开全文；再收起。
- 短正文（1 / 2 / 3 行）：全部显示，无省略、无按钮。
- 4 行正文：首行 + 省略 + 末两行，中间 1 行被省略。
- 代码块、表格、引用、嵌套列表位于首部 / 中部 / 尾部时的折叠高度固定，无跳动。
- 缩放窗口、字体加载完成后预览重新对齐。
- 禁用 JS：显示全文，无折叠按钮；JS 抛错时同样恢复全文。
- 编辑态取消不写库；保存后新正文立即出现，批准 badge 变为「未批准」。
- 编辑态字段错误保留输入并聚焦。

检查命令：

```bash
uv run pytest -q
```

### 4.6 风险与回滚

| 风险 | 说明 | 处理 |
| --- | --- | --- |
| 可视行测量复杂 | 不同浏览器 / 缩放 / 字体导致行盒差异 | 以 `Range.getClientRects()` + 2px 容差为准；字体加载后、ResizeObserver 触发时重测；固定预览高度兜底 |
| 首屏闪烁 | 折叠要等 JS 测量 | 服务端默认输出折叠标记；JS 初始化后一次性显示；无 JS 用 `<noscript>` 显示全文；异常 catch 恢复全文 |
| 块级内容撑高 | 代码块 / 表格高度大于行高 | 槽位固定 L / 2L，超出裁切；计行规则按块折算，不让折叠高度随内容变化 |
| 编辑门禁与审阅门禁混淆 | 编辑允许 `failed`，审阅只允许 `pending_codegen` | 新增独立判定函数，不修改批准 / 待确认前置；测试分别覆盖 |
| 清批准遗漏 | 人工编辑写回正文但未清 `doc_approved_at` | 保存事务内显式置 `NULL`；测试断言批准徽章与字段 |
| 409 改变现有行为 | 旧测试预期 303 | 按 Issue 要求改为 409；同步更新测试与页面提示 |
| 两套编辑 UI 漂移 | 独立页与卡内编辑并存 | GET 旧地址重定向；实现 PR 删除或退役 `design_edit.html` |
| 超长文档 | 大 textarea 占内存 / 请求体过大 | 262,144 字符上限，服务端 `len()` 校验；继续使用 `Text` 列 |
| 并发编辑覆盖 | 两个标签页同时保存 | 本迭代接受后写覆盖；不加版本锁，见待确认 |
| 无 JS 用户 | 折叠与编辑态都依赖 HTML / 少量 JS | 折叠无 JS 显示全文；编辑态由 `?edit=1` 服务端渲染，无 JS 也可保存 |

回滚：

- 代码回退即可恢复「正文始终展开、独立编辑页」；无数据库迁移，不需要数据回滚。
- 编辑保存仍走原 POST，回滚不会丢失已保存的 `design_doc_text` 或 `design_feedback`。

## 5. 影响面

| 区域 | 影响 |
| --- | --- |
| 数据库 | 无新增表 / 列 / 迁移；继续使用 `issue.design_doc_text`（`Text`）与已有 `doc_approved_at` |
| `app/api/v1/issues.py` | 详情上下文、`?edit=1`、GET 重定向、POST 409 / 200 / 303、编辑判定 |
| `app/services/design_review.py` | 新增编辑可用性判定与长度常量；批准 / 待确认逻辑不变 |
| `app/crud/job.py` | 默认复用 `has_active_for_issue`；仅在不放宽语义的前提下可增加动作过滤 |
| `app/templates/issue_detail.html` | 正文折叠结构、设计文档卡只读 / 编辑态、测量脚本 |
| `app/templates/partials/head_assets.html` | 预览槽位、省略行、紧凑克隆的 CSS |
| `app/templates/design_edit.html` | 退役或仅保留兼容；主入口移到详情卡 |
| `tests/test_design_review.py` | 编辑入口、409、清批准、消毒、长度、失败状态编辑 |
| `tests/test_ui.py` | 折叠标记、`aria-expanded`、编辑态 textarea、保存 / 取消 |
| `docs/architecture/design.md` | 实现 PR 更新 Issue 详情页、编辑入口、异常与测试章节 |
| `docs/README.md` | 实现 PR 可补「正文默认折叠、生成前可人工编辑」摘要；本迭代文档不直接改 |
| Worker / 代理 / git / PR | 无变化；人工编辑不入队、不调用代理、不提交、不推送 |
| 部署 | 无新环境变量；无迁移；仅前端模板与路由行为变化 |

## 6. 验收

- [ ] 长正文默认折叠：可见首行 + 省略 + 末两行；点击可展开全文；行数按渲染后可视行计算，不按 Markdown 源文 `\n`。
- [ ] 短正文（可视行 ≤ 3）折叠态显示全部行，无错误省略、无无意义折叠控件。
- [ ] 无正文保持现有空状态，不出现折叠按钮或省略号。
- [ ] 块级元素（代码块 / 表格 / 引用 / 列表）的折叠高度符合 4.2 的可测规则，窗口缩放与字体加载后不跳动。
- [ ] 折叠控件在正文卡标题行，`aria-expanded` 正确，展开 / 收起文案正确；刷新后仍默认折叠。
- [ ] `pending_codegen` 且未开始生成时，可在设计文档卡片内编辑并保存，页面立即显示新内容。
- [ ] 保存成功后若存在 `doc_approved_at` 则已被清空；`design_doc_path`、`iteration_no` 不变。
- [ ] 取消编辑不写库；生成中 / 已生成 / 已建 PR / `codegen_phase != none` 时编辑入口不可见，非法 POST 返回 409。
- [ ] 有进行中任务时保存返回 409 并有明确提示。
- [ ] 保存内容仍走现有 Markdown + nh3 消毒；空正文 / 超长文档被拒绝且有字段错误。
- [ ] 相关 pytest / UI 断言通过；实现走 `dev_20` 并开 PR。
- [ ] 未新增流程状态名、数据库迁移、角色权限、协同编辑或自动保存。

## 7. 待确认

以下事项 Issue 没有给出唯一结论，本文先按默认方案推进；最终以评审或实现 PR 确认为准。

1. **代码块 / 表格的「行」如何折算**：本文默认 `pre` 按源码行数、`table` 按 `tr` 高度折算为 1 行或多行，预览槽位固定并裁切超出部分。若产品希望「代码块整块只算 1 行」或「表格每行固定算 1 行而不看换行」，需要改 4.2.2 的规则。
2. **省略行是否占用 3 行预算**：本文默认预览为「1 行 + 固定省略行 + 2 行」，省略行不占 3 行内容预算。若要求折叠后总高度严格等于 3 个行高，需要把省略行压到行内或改为覆盖层。
3. **块跨越裁切边界时是否扩展到整块**：本文默认固定高度、按行槽裁切，不因为代码块 / 表格被切成两半而扩张预览。若要求块必须完整显示，折叠高度会随内容变化，需要接受跳动或改为 `max-height`。
4. **`failed_action = revise_doc` 是否允许编辑**：本文默认允许（正文已存在，先人工修再决定是否重试）。若只允许 `failed_action = write_doc`，收紧 4.3.2。
5. **`failed_action = generate_code` 且 `codegen_phase = none` 是否允许编辑**：本文默认拒绝，因为已经尝试进入生成阶段。若允许，需要明确「生成失败后改文档再重试」的语义。
6. **失败状态保存后是否清 `last_error` / 回到 `pending_codegen`**：本文默认状态不变、仅改正文并清批准，操作员继续用原有重试入口。若希望保存后自动回到待生成，需要改保存事务。
7. **长度上限数值**：本文默认 262,144 字符（继续使用 `Text` 列）。若现有或预期文档更大，需要调整常量；若希望完全沿用 DB `Text` 不设应用上限，需要去掉服务端长度校验。
8. **并发编辑是否加版本锁**：本文默认后写覆盖，不校验 `doc_sha256`。若要求「打开编辑后文档已被修订则拒绝保存」，form 需要带打开时的 `doc_sha256` 并在保存时比较。
9. **人工编辑是否更新 `design_source_updated_at`**：本文默认不更新，沿用现有 stale 警告（Issue 在文档完成后有更新）。若人工保存视为已同步当前 Issue 正文，需要写回规则。
10. **人工编辑是否处理未完成 feedback**：本文默认不自动标记 `resolved_at`，人工编辑不等同于「按意见修订完成」。若希望把人工编辑视为处理全部未处理意见，需要批量标记。
11. **不可编辑时隐藏还是禁用**：本文默认隐藏「编辑文档」按钮。若希望保留灰色按钮并提示原因，需要增加 disabled 态和说明文案。
12. **卡片内编辑用服务端 `?edit=1` 还是纯客户端切换**：本文默认服务端渲染 `?edit=1`，无 JS 也能编辑；若希望点击不刷新页面，可改为客户端切换，但保存接口仍复用 POST。
13. **无 JS 时正文是否必须折叠**：本文默认无 JS 直接显示全文（`<noscript>`），折叠是 JS 增强。若要求无 JS 也必须默认折叠，需要用 `<details>` 等原生结构，但会失去「首行 + 末两行」预览。
14. **`doc_approved_at` 列不存在时的行为**：本文默认检测到列缺失则跳过清空并记录 warning，发布前要求 v0009 迁移已应用。若要求缺列直接失败，需要在保存前做 schema 检查。
15. **「可视行」是否忽略尾部空行**：本文默认忽略零高度空矩形，`<br>` 造成的真实空行计 1 行。若 Markdown 渲染器产生空 `<p>` 或尾部换行，需要在实现时用同一规则统一处理。
16. **表格 / 代码块在预览中是否可横向滚动**：本文默认预览槽位 `overflow: hidden`，不提供横向滚动，避免折叠态出现第二条滚动轴；完整内容在展开态可滚动。若希望预览也能横向查看，需要单独设计交互。
