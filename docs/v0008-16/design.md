# 仓库页「本地配置」卡片防溢出（v0008 / Issue #16）

- 迭代：`v0008`，对应 GitHub Issue `#16`
- 文档路径：`docs/v0008-16/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：**纯前端布局修复**。不改接口、数据模型、任务状态机与保存 / 校验规则。

## 1. 背景

`/repos/{id}`（例如 `/repos/1`）右侧「本地配置」卡片位于 `lg:grid-cols-3` 的 `lg:col-span-1` 轨道。桌面窄栏下，以下内容会横向画出卡片右边框，甚至压到左侧「GitHub 资料」卡片：

- 「服务器项目路径」「文档目录」两个 daisyUI `input`；
- 两个输入框下方的帮助文案，以及文案中的 `KFC360/work_flow`、`{doc_dir}/README.md` 等 `code`。

Issue #14（`docs/v0007-14/design.md`）已提出「仓库本地配置输入防溢出」，当前 `app/templates/repo.html` 也已给栅格容器、`section.card`、`card-body`、`form`、`fieldset` 和 `input` 补了部分 `min-w-0` / `max-w-full`，但线上仍然溢出。说明当时的修复只覆盖了结构节点，没有覆盖「输入框 + 帮助文案」整条宽度链。

### 1.1 当前实现核对

以当前仓库代码和 `daisyUI 5.7.50`（`app/templates/partials/head_assets.html` 固定版本）为准：

| 节点 | 当前写法 | 问题 |
| --- | --- | --- |
| 右栏 `section.card` | 有 `min-w-0` | 基本正确，缺 `max-w-full` |
| `card-body` | 有 `min-w-0` | 基本正确，缺 `max-w-full` |
| `form` | `w-full min-w-0` | 缺 `max-w-full`，约束链不完整 |
| `fieldset` | `fieldset w-full min-w-0` | 缺 `max-w-full` |
| 两个 `input` | `input w-full min-w-0 max-w-full font-mono text-sm` | 类名已齐，但仍会被父级撑宽 |
| 帮助文案 | `<p class="label text-xs ...">` | **本轮主因**：daisyUI `.label` 是 `display:inline-flex; white-space:nowrap`，段落被当成单行 flex 容器 |
| 帮助文案中的 `code` | 只有部分带 `break-all` | 父级 `nowrap` 下 `break-all` 不能生效；`docs` 等 `code` 未断行 |
| 字段错误文案 | `text-sm text-error` | 无断行约束，长错误可能溢出 |

daisyUI 5.7.50 的实际样式为：

```css
.label {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  white-space: nowrap;
}
```

因此帮助文案所在的 `<p class="label">` 不会换行，且其内容宽度会成为 `fieldset` 网格轨道的最小内容宽度。`fieldset` 内的 `input.w-full` 又按被撑宽的轨道取 100%，最终输入框和帮助文案一起越过卡片边框。`code` 上的 `break-all` 只改变断词规则，无法突破父级的 `white-space: nowrap`。

### 1.2 根因归纳

1. flex / grid 子项默认 `min-width: auto`，长内容会把轨道撑到内容宽度；
2. daisyUI `.label` 被误用在帮助段落上，带来 `inline-flex` + `white-space: nowrap`，帮助文案完全不换行；
3. `form` / `fieldset` 缺少 `max-w-full`，宽度约束链不闭合；
4. 帮助文案中的 `code` 未统一设置可断行，长 `owner/repo`、`{doc_dir}/README.md` 会继续撑宽；
5. 错误文案没有 `min-w-0` / `break-words`，校验失败时可能再次溢出。

## 2. 目标

1. 「本地配置」内所有控件与帮助文案都不溢出 `card` / `card-body` 边框，不压到左侧「GitHub 资料」或页面外。
2. 在整条宽度链上补齐约束，缺一不可：
   - 右栏 / `card` / `card-body`：`min-w-0`；
   - `form` / `fieldset`：`min-w-0 max-w-full`；
   - `input`：`w-full min-w-0 max-w-full`；
   - 帮助文案与其中 `code`：`break-all` 或等价断行，长串不撑破。
3. 长路径仍可读：输入框保留原生内部横向滚动，`title` 悬停显示完整值；不靠裁切隐藏布局错误，也不把值截断成不可查看。
4. 桌面右栏与小屏单列都验收；保存、校验、进行中任务禁用逻辑保持不变。
5. 继续使用 daisyUI `card` / `fieldset` / `label` / `input`，不自研输入组件、不引入新 CSS 框架。

## 3. 非目标

- 不改 `local_path` / `doc_dir` 的校验规则、保存接口、字段名、POST 路由与 flash 文案。
- 不重做仓库页信息架构，不调整「本地配置」与「GitHub 资料」的左右位置或栅格比例。
- 不顺便做 Issues 手动同步、重新同步、任务入队或其它功能。
- 不引入新 CSS 框架、构建步骤、前端依赖或自研输入组件。
- 不通过 `overflow-hidden` / `overflow-x-hidden` 裁掉内容来「看起来不溢出」。
- 不改输入框的 `font-mono`、`title`、`autofocus`、错误提示位置与 `disabled` 条件。
- 不改 `app/templates/partials/head_assets.html` 的全局样式；本迭代优先只改仓库页模板。
- 不改后端、数据库、Worker、任务状态机与代理调用。

## 4. 方案

### 4.1 总体思路

在「右栏 → card → card-body → form → fieldset → input / 帮助文案」每一层都建立 `min-w-0`（必要时 `max-w-full`）约束，并把帮助文案从 daisyUI `.label` 改回普通块级段落。这样帮助文案可以正常换行，不再决定整个网格轨道的最小宽度，输入框的 `w-full` 也就只会占满卡片内容区。

不改变 daisyUI 组件选择：字段标题继续用 `<label class="label">`，输入继续用 `input`，卡片继续用 `card` / `card-body` / `fieldset`。

### 4.2 目标结构

`app/templates/repo.html` 中「本地配置」区域调整为：

```html
<div class="grid min-w-0 gap-6 lg:grid-cols-3">
  <section
    class="card card-border order-1 min-w-0 max-w-full bg-base-100 shadow-sm lg:order-2 lg:col-span-1"
    aria-labelledby="local-config-title"
  >
    <div class="card-body min-w-0 max-w-full p-5">
      <h2 id="local-config-title" class="card-title text-base">
        <!-- 图标与「本地配置」 -->
      </h2>

      <form
        method="post"
        action="/repos/{{ repo.id }}"
        class="w-full min-w-0 max-w-full space-y-4"
      >
        <input type="hidden" name="csrf_token" value="{{ csrf_token }}" />

        <fieldset class="fieldset w-full min-w-0 max-w-full">
          <legend class="fieldset-legend">路径设置</legend>

          <label class="label" for="local_path">服务器项目路径</label>
          <input
            id="local_path"
            name="local_path"
            class="input w-full min-w-0 max-w-full font-mono text-sm {% if field_errors.local_path %}input-error{% endif %}"
            value="{{ local_path }}"
            title="{{ local_path }}"
            aria-describedby="local_path-help{% if field_errors.local_path %} local_path-error{% endif %}"
            {% if field_errors.local_path %}aria-invalid="true"{% endif %}
            {% if form_disabled %}disabled{% endif %}
            {% if first_error == 'local_path' %}autofocus{% endif %}
          />
          <p
            id="local_path-help"
            class="mt-1 w-full min-w-0 max-w-full whitespace-normal break-words text-xs leading-5 text-base-content/60"
          >
            须为已 clone 的 git 顶层绝对路径；origin 必须匹配
            <code class="break-all whitespace-normal rounded bg-base-200 px-1 py-0.5 font-mono">{{ repo.github_full_name }}</code>。
          </p>
          {% if field_errors.local_path %}
          <p id="local_path-error" class="mt-1 min-w-0 max-w-full break-words text-sm text-error">
            {{ field_errors.local_path }}
          </p>
          {% endif %}

          <label class="label" for="doc_dir">文档目录</label>
          <input
            id="doc_dir"
            name="doc_dir"
            class="input w-full min-w-0 max-w-full font-mono text-sm {% if field_errors.doc_dir %}input-error{% endif %}"
            value="{{ doc_dir }}"
            title="{{ doc_dir }}"
            aria-describedby="doc_dir-help{% if field_errors.doc_dir %} doc_dir-error{% endif %}"
            {% if field_errors.doc_dir %}aria-invalid="true"{% endif %}
            {% if form_disabled %}disabled{% endif %}
            {% if first_error == 'doc_dir' %}autofocus{% endif %}
          />
          <p
            id="doc_dir-help"
            class="mt-1 w-full min-w-0 max-w-full whitespace-normal break-words text-xs leading-5 text-base-content/60"
          >
            相对路径，默认
            <code class="break-all whitespace-normal rounded bg-base-200 px-1 py-0.5 font-mono">docs</code>；
            基石入口为
            <code class="break-all whitespace-normal rounded bg-base-200 px-1 py-0.5 font-mono">{doc_dir}/README.md</code>。
          </p>
          {% if field_errors.doc_dir %}
          <p id="doc_dir-error" class="mt-1 min-w-0 max-w-full break-words text-sm text-error">
            {{ field_errors.doc_dir }}
          </p>
          {% endif %}
        </fieldset>

        <button type="submit" class="btn btn-primary btn-sm gap-1.5" data-gw-submit {% if form_disabled %}disabled{% endif %}>
          {{ icon('check') }}<span>保存</span>
        </button>
      </form>
    </div>
  </section>
</div>
```

要点：

- 帮助文案不再使用 `.label`。`.label` 是表单标签组件，不是说明文字组件；改用普通 `<p>` 后默认 `display: block`，可自然换行。
- 帮助文案加 `whitespace-normal break-words`，并按 Issue 要求补 `break-all` 或等价断行；普通中文句子用 `break-words`，其中等宽 `code` 用 `break-all`，避免长 `owner/repo`、`{doc_dir}/README.md` 撑宽。
- `code` 上的 `whitespace-normal` 用于显式覆盖可能的 `nowrap` 继承，保证断行规则生效。
- 每个输入框继续保持 `w-full min-w-0 max-w-full`；不设固定 `min-w-[...]`，不在输入框内塞按钮。
- 字段标题仍用 `<label class="label">`。这些标签文本很短（「服务器项目路径」「文档目录」），`nowrap` 不会造成溢出，也保留 daisyUI 的视觉与语义。
- 字段错误文案补 `min-w-0 max-w-full break-words`，避免校验错误较长时再次撑破卡片。
- 所有约束都通过布局宽度实现，不使用 `overflow-hidden` 裁切焦点环或内容。

### 4.3 长路径可读性

- `input` 保持单行文本输入；长值时浏览器原生支持在输入框内部横向滚动，聚焦后可查看完整值。
- `title="{{ local_path }}"` / `title="{{ doc_dir }}"` 保留，鼠标悬停可看完整值。
- 不把输入框改成 `textarea`，不做可展开预览，不截断提交值。
- 输入框内部滚动不影响 `value` 与保存逻辑；服务端仍收到完整路径。

### 4.4 行为保持不变

以下行为只做布局层调整，逻辑与文案不变：

- 表单仍 POST 到 `/repos/{repo.id}`，带 CSRF 隐藏字段。
- `form_disabled` 时两个输入框与保存按钮继续 `disabled`，页顶「有进行中的任务，暂不可改路径」提示不变。
- 校验失败仍返回本页，错误仍在对应字段下方，`first_error` 的自动聚焦不变。
- 保存成功仍 303 回本页并 flash「已保存」。
- `aria-describedby`、`aria-invalid`、可见 `<label>`、`data-gw-submit` 防双提交均保留。

### 4.5 响应式验收方法

在浏览器开发者工具中至少检查以下宽度：

| 宽度 | 场景 |
| --- | --- |
| 1440px | 桌面三栏，右栏 `lg:col-span-1` |
| 1024px | `lg` 临界点，右栏窄栏 |
| 768px | 单列 |
| 375px | 小屏单列 |

每个宽度下检查：

1. `.card` 与 `card-body` 的 `scrollWidth <= clientWidth`；
2. 「本地配置」卡片右边界不超过主内容区，且与左侧「GitHub 资料」卡片不重叠；
3. 两个输入框、帮助文案、字段错误文案均无横向溢出；
4. 页面本身不出现额外横向滚动条（表格页的表格滚动除外）；
5. 键盘 Tab 聚焦输入框时焦点环完整可见，未被裁切。

### 4.6 测试与断言

沿用现有 `tests/test_ui.py` 的静态模板断言方式，更新 `test_layout_footer_and_repo_input_constraints`：

- 右栏 `section` 含 `min-w-0` 与 `max-w-full`；
- `card-body` 含 `min-w-0` 与 `max-w-full`；
- `form` 含 `w-full min-w-0 max-w-full`；
- `fieldset` 含 `fieldset w-full min-w-0 max-w-full`；
- 两个输入框仍各出现一次 `input w-full min-w-0 max-w-full font-mono text-sm`；
- 帮助文案不使用 `.label`：
  - `id="local_path-help"` 与 `id="doc_dir-help"` 所在元素不含 `class="label`；
  - 两个帮助段落均含 `whitespace-normal`、`break-words`、`min-w-0`、`max-w-full`；
- 帮助文案中的 `code` 均含 `break-all` 与 `whitespace-normal`；
- 两个输入框仍保留 `title="{{ local_path }}"`、`title="{{ doc_dir }}"`；
- 保存按钮仍带 `data-gw-submit`，`form_disabled` 分支仍存在。

可补一个渲染断言：用测试客户端打开仓库页，确认长 `local_path` 同时出现在 `value` 与 `title` 中，且页面仍返回 200；不引入浏览器依赖。

人工检查按 4.5 执行；如果后续需要自动化视觉回归，见「待确认」。

### 4.7 风险与回滚

| 风险 | 说明 | 处理 |
| --- | --- | --- |
| 只改输入框、漏掉帮助文案 | 帮助文案的 `nowrap` 仍会撑宽轨道 | 把「帮助段落不使用 `.label`」列入测试断言 |
| 用 `overflow-hidden` 掩盖问题 | 内容被裁掉，焦点环和长路径不可见 | 明确禁止裁切，改用 `min-w-0` 与断行 |
| 误改字段标签语义 | 把真正的 `<label class="label">` 也去掉，影响可访问性 | 只替换帮助文案；字段标题保留 `<label class="label">` |
| 工具类被 CDN 层叠覆盖 | `min-w-0` / `max-w-full` 未生效 | 先确认 daisyUI 与 Tailwind 的加载顺序；仍不生效时再评估是否需要页面级兜底样式，并在 PR 说明 |
| 小屏回归 | 新增 `max-w-full` 影响其他栅格 | 只改仓库页本地卡片，不扩散到全局样式 |
| 回滚 | 纯模板 + 测试改动 | 回滚整个 PR 即可，无迁移、无数据变更 |

## 5. 影响面

| 区域 | 影响 |
| --- | --- |
| `app/templates/repo.html` | 调整本地配置卡片的容器类、帮助文案元素与 `code` 断行类；不改字段、路由、按钮行为 |
| `tests/test_ui.py` | 更新仓库页布局静态断言，覆盖完整宽度链与帮助文案断行 |
| 后端 / API / 数据库 | 不改；无迁移、无新字段、无接口变更 |
| Worker / Job / 状态机 | 不改；保存与任务禁用逻辑不变 |
| 全局样式 / 前端依赖 | 不改 `head_assets.html`，不新增 CSS 框架或 npm 依赖 |
| 其它页面 | 不受影响；「GitHub 资料」卡片内容与交互不变 |
| 文档 | 本迭代只新增本文档。是否把「本地卡片所有子项需 `min-w-0`」写回基石界面契约，见「待确认」 |

## 6. 验收

- [ ] `/repos/{id}` 填入长绝对路径（如 `/home/linuxuser/repos/work_flow`）时，两个输入框与帮助文案均在卡片内，无横向溢出。
- [ ] 帮助文案中的 `owner/repo`、`{doc_dir}/README.md` 等 `code` 可断行，不撑破边框。
- [ ] 小屏单列同样无溢出；桌面 1440px、`lg` 临界 1024px、768px、375px 均检查通过。
- [ ] 卡片 `scrollWidth <= clientWidth`，右栏不压到左侧「GitHub 资料」，页面无额外横向滚动条。
- [ ] 帮助段落不再使用 daisyUI `.label`；字段标题仍保留可见 `<label>`。
- [ ] 输入框仍保留 `title`，长路径可通过输入框内部横向滚动查看完整值；未被 `overflow-hidden` 裁切。
- [ ] 保存成功 / 校验失败行为与改前一致；校验错误仍在字段下方并可断行。
- [ ] 存在 queued 或 running 任务时，两个字段与保存按钮仍 `disabled`。
- [ ] 键盘焦点环完整可见，不被卡片裁切。
- [ ] `tests/test_ui.py` 的相关断言通过；`uv run pytest -q` 通过。
- [ ] 未引入新 CSS 框架、自研输入组件或后端改动。
- [ ] 实现走 `dev_16` 并开 PR。

## 7. 待确认

以下事项 Issue 未给出唯一结论，本文先按默认方案推进；最终以评审或实现 PR 确认为准。

1. **验收浏览器与宽度矩阵**：本文默认覆盖 Chromium 系（Chrome / Edge）与 Firefox，宽度为 1440 / 1024 / 768 / 375px，不包含 Safari 专项。如果团队要求 Safari 或更窄的 320px，请补充验收范围。
2. **是否引入自动化视觉回归**：当前测试栈是 pytest + httpx，没有浏览器依赖。本文默认用静态模板断言 + 人工多宽度检查；如果要把「不溢出」做成 CI 级保障，需要引入 Playwright 或等价工具并增加浏览器环境，属于测试基础设施变更。
3. **帮助文案的断行粒度**：本文默认普通文本用 `break-words`、`code` 用 `break-all`，兼顾可读性与长串不溢出。如果设计要求整段统一 `break-all`，需要同步调整断言；目前未把整段设为 `break-all`，以免中文句子在不自然的位置断行。
4. **是否回写基石界面契约**：本文默认只改模板与测试，不改 `docs/architecture/design.md`。如果评审希望把「卡片内所有子项 `min-w-0`、帮助文案不得使用 `.label`」写成通用界面规则，应另开基石更新或在实现 PR 中同步补充。
5. **错误文案的超长内容**：本文给错误段落加了 `break-words`，但没有定义单条错误的最大长度或截断策略。若后端错误可能包含超长原始路径 / 堆栈，是否需要服务端截断，需另行确认。
6. **`max-w-full` 的覆盖范围**：Issue 明确要求 `form` / `fieldset` 带 `max-w-full`；本文同时给 `section.card` 与 `card-body` 补了 `max-w-full`，作为整条约束链的兜底。若评审希望严格只改 Issue 列出的节点，可移除这两处，但不建议。
7. **全局兜底样式**：如果实现时发现 Tailwind CDN 与 daisyUI 的层叠顺序导致工具类不生效，是否需要新增页面级或全局 CSS 兜底，本文未预先决定；默认优先通过工具类和元素结构调整解决，不扩大全局样式改动。
8. **是否保留 `.label` 的视觉间距**：去掉帮助段落的 `.label` 后，daisyUI 的 `gap` 与颜色不再自动生效。本文用 `mt-1` 与 `text-base-content/60` 显式补足；最终间距以设计走查为准，必要时只微调间距类，不改布局方案。
