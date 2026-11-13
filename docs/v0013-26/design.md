# v0013-26 仓库页「新 Issue 收件人」列表化编辑

> 迭代：v0013 · Issue #26。本文只描述相对基石 [`docs/README.md`](../README.md) 与 [`docs/architecture/design.md`](../architecture/design.md) 的增量，不重复完整产品设计。
>
> 基石中与本迭代直接相关的约定：仓库页可配置多名新 Issue 收件人，Issue 首次入库时通知一次（Webhook / 全量同步共用）；留空列表表示不发信；全量同步历史数据前应先留空收件人。页面仍采用 DaisyUI CDN、Jinja2 服务端渲染、普通页面 POST + CSRF，不引入前端构建工具。

## 1. 背景

仓库页 `/repos/{id}` 的「本地配置」里，`新 Issue 收件人` 现在是一个多行 `textarea`。已保存的邮箱以换行拼接后回填；用户需要自己从一大段文本里逐行辨认、手工删除字符来移除某个邮箱，增加时也要自己注意分隔符和重复值。

现有实现：

| 位置 | 现状 |
| --- | --- |
| `app/templates/repo.html` | `textarea[name=notify_emails]`，提示「多个邮箱用换行或逗号分隔」；字段错误显示在下方 |
| `app/api/v1/repos.py` | `POST /repos/{id}` 接收单个 `notify_emails` 字符串，调用 `parse_notify_emails` 后写入 `repository.notify_emails` |
| `app/services/issue_notify.py` | `parse_notify_emails` 按空白 / 逗号 / 分号拆分，校验后**静默去重**；`maybe_notify_new_issue` 在 Issue 首次入库时使用该列表发信 |
| `app/models/repository.py` | `notify_emails` 为 `ARRAY(String(320))`，默认空数组 |
| `app/services/issue_notify.py` | 发送失败只记日志，不阻断同步；`issue.notify_email_sent_at` 保证同一 Issue 只发一次 |

本迭代只调整仓库页的录入与展示方式，不改通知触发时机、邮件正文、SMTP 配置和发信失败策略。

## 2. 目标

1. 已保存的收件人显示为**列表**，每行一个邮箱，便于扫读；无收件人时显示「暂无收件人」。
2. 每行提供删除按钮，先从当前表单列表中移除，点「保存」后才写入数据库。
3. 通过单独的单行邮箱输入框 +「添加」按钮一次加入一个邮箱；合法且不重复时进入列表，输入框清空。
4. 非法邮箱、重复邮箱有明确提示，且不会进入列表；服务端仍做最终校验。
5. 点「保存」时把当前列表作为完整列表提交，仍写入 `repository.notify_emails`，继续复用 `POST /repos/{id}`。
6. 清空全部并保存后，仓库不再对新 Issue 发通知。
7. 不改变：首次入库才通知、同一 Issue 只发一次、发信失败不阻断同步、SMTP 配置与邮件正文。
8. 无 JavaScript 时仍能完成增删：保留一个可编辑的文本框回退，不引入 npm 或前端框架。

## 3. 非目标

- 不改通知触发逻辑、邮件主题 / 正文、`notify_email_sent_at` 语义和发信失败处理。
- 不做公司级默认收件人、收件人分组、拖拽排序、批量导入或通讯录选择。
- 不新增数据库表 / 字段 / 迁移；不改 `repository.notify_emails` 的类型和默认值。
- 不新增独立的收件人管理页或 JSON API；不改变 `POST /repos/{id}` 的路径、CSRF 和成功后的 303 行为。
- 不引入 npm、前端构建、Alpine / React / Vue 等框架，也不把 DaisyUI 改成自建组件库。
- 不改「有进行中的任务时表单禁用」的既有规则；只让收件人区域也遵守该规则。
- 不改变服务端对显示名格式（`Name <a@example.com>`）的兼容性；本迭代的输入框以纯邮箱地址为主，详见「待确认」。

## 4. 方案

### 4.1 总体结构

继续由服务端提供初始数据，原生脚本做渐进增强；不增加服务端草稿或新路由。

```text
GET /repos/{id}
  Repository.notify_emails
        │
        ├── 服务端渲染收件人 <li> 列表（首屏可见）
        └── 换行拼接为 textarea[name=notify_emails] 的初始值
                    │
                    │ 有 JS：隐藏 textarea，显示列表 + 添加区
                    ▼
        添加 / 删除只改 DOM 与隐藏 textarea.value
                    │
                    │ 点「保存」提交单个 notify_emails 字符串
                    ▼
POST /repos/{id}（路径、CSRF、字段名不变）
        │
        ▼
parse_notify_emails → Repository.notify_emails → 303 回本页
```

关键点：

- 列表是服务端渲染的，禁用 JavaScript 时也能看到已配置的收件人。
- 表单提交字段仍为单个 `notify_emails`，值为换行拼接的完整列表；不新增多值字段，`POST /repos/{id}` 签名基本不变。
- 只有点「保存」才落库；添加 / 删除按钮不发起请求。
- `issue_notify.py` 的发信逻辑不改，空数组自然表示不发信。

### 4.2 页面结构

在 `app/templates/repo.html` 的「本地配置」fieldset 中，把原 `textarea` 替换为以下结构（类名可按 DaisyUI 习惯微调，`data-gw-*` 钩子保留）：

```text
新 Issue 收件人
┌──────────────────────────────────────────────────────┐
│ ops@example.com                         [删除]        │
│ dev@example.com                         [删除]        │
│（空时显示：暂无收件人）                               │
├──────────────────────────────────────────────────────┤
│ [ 输入邮箱                         ] [ 添加 ]          │
│ 非法邮箱 / 重复邮箱的错误提示（仅出错时显示）          │
└──────────────────────────────────────────────────────┘
[每行一个邮箱的文本框，作为无 JS 回退；有 JS 时隐藏]
提示：一次添加一个邮箱；保存后生效；留空则不发新 Issue 通知。
```

具体要求：

1. **列表容器**：使用 `ul` / `li`（或等价的列表语义），每个 `li` 带 `data-gw-notify-row`，邮箱文本用等宽字体、允许 `break-all`；邮箱通过 Jinja 文本节点渲染，自动转义。
2. **删除按钮**：每行一个 `type="button"` 的 ghost / outline 小按钮，文案「删除」，带 `aria-label`（例如「删除收件人 ops@example.com」）。按钮初始可以是 `hidden`，由 JS 在增强成功后显示；无 JS 时不出现无效按钮。
3. **空状态**：列表为空时显示「暂无收件人」，说明「保存空列表后，新 Issue 不会发通知」；列表非空时隐藏空状态。
4. **添加区**：单行 `input[type=email]`，`name` 不参与表单提交（例如 `data-gw-notify-input`，不要命名为 `notify_emails`）；旁边是 `type="button"` 的「添加」按钮。输入框带 `<label>` 或 `aria-label`，并设置 `autocomplete="email"`。
5. **错误提示**：添加区下方有独立的错误容器，默认 `hidden`，使用 `role="alert"` / `aria-live="polite"`，服务端字段错误仍显示在字段下方并参与页顶 `alert-error` 摘要。
6. **提交字段**：保留一个 `textarea[name=notify_emails]` 作为唯一提交字段；初始值仍为 `format_notify_emails(repo.notify_emails)`。JS 初始化后隐藏该 textarea，但保留其 `name` 和值，提交时随表单一起发送。
7. **无 JS 回退**：不隐藏 textarea 时，用户仍可像现在一样按行 / 逗号编辑并保存，从而完成增删；页面用 `<noscript>` 或普通提示说明「JavaScript 未启用时可在此直接编辑，每行一个邮箱」。不承诺无 JS 时提供逐行删除按钮（见「待确认」）。
8. **帮助文案**：把原来的「多个邮箱用换行或逗号分隔」改为「一次添加一个邮箱，保存后生效；留空则不发信。全量同步历史 Issue 前请先留空，避免群发」。无 JS 回退处单独说明分隔符。
9. **禁用态**：`form_disabled` 为真（仓库有 queued / running 任务）时，添加框、添加按钮、删除按钮和保存按钮都 `disabled`，并沿用现有「有进行中的任务，暂不可改路径」提示；文案建议改为「有进行中的任务，暂不可改路径或收件人」。列表仍只读展示。
10. **焦点**：沿用现有 `first_error` 逻辑；邮箱字段校验失败时自动聚焦可编辑控件（有 JS 且已增强时聚焦添加输入框，无 JS / 回退时聚焦 textarea），不改变其它字段的聚焦优先级。

### 4.3 原生脚本行为

在 `repo.html` 增加 `{% block scripts %}`（该模板目前没有此 block），放入一段内联原生 IIFE，写法与 `app/templates/partials/app_scripts.html`、`issues.html` 一致：使用 `var`、`document.querySelector` / `addEventListener`，不依赖构建产物或第三方库。

脚本职责：

| 步骤 | 行为 |
| --- | --- |
| 初始化 | 读取 `textarea[data-gw-notify-source]` 的值，按 `[\s,;]+` 拆分、`trim`、忽略空项，得到初始邮箱数组；隐藏 textarea 和初始「暂无收件人」之外的回退提示，显示添加区与删除按钮 |
| 同步 | 每次增删后执行 `textarea.value = emails.join("\n")`；空数组写成空字符串，保证「清空全部并保存」提交的是空值 |
| 添加 | 读取输入值并 `trim`；空值提示「请输入邮箱」；重复（忽略大小写与首尾空白）提示「重复邮箱：<地址>」；格式不合法提示「非法邮箱：<地址>」；通过后 push 到数组、渲染一行、清空输入框、隐藏错误、焦点留在输入框 |
| 删除 | 从数组移除对应项并重绘列表 / 空状态，同步 textarea；焦点优先移到下一行的删除按钮，没有则回到添加输入框 |
| 提交前同步 | 监听表单 `submit`，在既有防重复提交逻辑之前再同步一次，避免用户输入后未点「添加」直接保存时丢失文本 |
| 禁用态 | 表单 `disabled` 时只渲染只读列表，不绑定添加 / 删除动作，不显示可点击按钮 |
| 安全 | 新行用 `document.createElement` + `textContent` 构造，邮箱内容不拼进 `innerHTML`；不把邮箱写入未转义的 HTML 属性 |

前端校验规则以服务端 `parse_notify_emails` 的最终结果为准，只做即时提示，避免出现「前端放行、服务端报错」的常见路径：

- 去掉首尾空白后必须非空。
- 拒绝含 CR / LF / 空白的值；要求存在且仅存在一个可解析的地址，`@` 两侧非空。
- 重复判断使用 `toLowerCase()`，保留用户输入的大小写；服务端返回的规范化地址以保存后刷新为准。
- `input[type=email]` 提供浏览器原生提示，但脚本不依赖浏览器气泡，统一用页面内错误容器提示。

### 4.4 服务端与校验

#### 4.4.1 路由与上下文

`app/api/v1/repos.py` 继续使用 `POST /repos/{id}`，请求字段仍为：

```python
notify_emails: Annotated[str, Form()] = ""
```

`_repo_page_context` 增加一个只读列表上下文 `notify_email_items`，与原始表单值分开：

| 上下文 | 来源 | 用途 |
| --- | --- | --- |
| `notify_emails` | GET：`format_notify_emails(repo.notify_emails)`；POST 校验失败：用户提交的原始字符串 | textarea 的值 / 无 JS 回退 |
| `notify_email_items` | GET：`repo.notify_emails`；POST 校验失败：已成功解析的提交列表，邮箱解析失败时用 `repo.notify_emails` | 服务端渲染列表 |
| `notify_enhance` | 邮箱字段有错误时为 `False`，否则 `True` | 邮箱解析失败时暂停 JS 增强，保留原始 textarea 供修正 |

- GET 不做写操作，列表和 textarea 都由数据库当前值生成。
- POST 成功时：`repo.notify_emails = parsed_emails`，`db.commit()`，303 回 `/repos/{id}?flash=ok&msg=已保存`；与现有行为一致。
- POST 失败时：不写数据库，200 重新渲染本页并显示字段错误；路径 / 文档目录错误仍按现有分支处理。
- 有进行中的 Job 时，仍按现有逻辑 303 回本页并 flash 拒绝，不进入解析和保存。

#### 4.4.2 `parse_notify_emails` 的重复与非法处理

当前函数遇到非法项会返回错误，但遇到重复项会静默跳过。按 Issue 要求「重复邮箱有明确提示」，改为**重复即错误**：

```python
def parse_notify_emails(raw: str) -> tuple[list[str], str | None]:
    """按空白/逗号/分号拆分；返回 (规范化去重列表, 错误提示)。"""
```

规则：

1. `raw` 为空或只有分隔符：返回 `([], None)`，表示清空列表，合法。
2. 逐项 `strip()`；空项跳过。
3. 用现有 `is_valid_address` 校验；失败返回 `([], f"非法邮箱：{part}")`。
4. 用 `parseaddr` 取地址部分并 `strip()`；按 `address.lower()` 判断是否已出现。
5. 重复时返回 `([], f"重复邮箱：{address}")`，保留首次出现的值，不静默吞掉。
6. 全部合法且不重复时按输入顺序返回规范化地址列表，保持大小写。

这样即使有人绕过前端直接 POST 重复地址，也会收到明确的 200 字段错误，数据库保持原值，而不是被悄悄去重。现有单元测试中「静默去重」的断言需要同步改为「重复报错」。

错误提示沿用中文短句，页面直接展示，不记录完整收件人列表到日志：

| 场景 | 提示 |
| --- | --- |
| 输入框为空点「添加」 | `请输入邮箱` |
| 含非法字符 / 无法解析 | `非法邮箱：<原始值>` |
| 已在列表中（忽略大小写） | `重复邮箱：<地址>` |
| 服务端收到非法 / 重复值 | 同上的字段错误，页面 200，数据库不变 |

#### 4.4.3 与现有通知链路的兼容

- `app/services/issue_notify.py` 的 `maybe_notify_new_issue`、`build_new_issue_mail`、`send_mail` 调用均不改。
- 保存空列表后 `repo.notify_emails == []`，`maybe_notify_new_issue` 在读取收件人时直接返回 `False`，不发信。
- 首次通知仍由 `created=True`、`notify_email_sent_at is None` 和收件人非空共同决定；Webhook 与全量同步继续共用。
- 发信失败仍只 `logger.warning`，不抛出、不阻断入库 / 同步；`notify_email_sent_at` 只在发送成功后写入。
- 仓库页不展示「已发 / 未发」状态，也不触发试发；试发仍只在设置页。

#### 4.4.4 安全与可访问性

- 邮箱通过 Jinja 自动转义；删除按钮的 `aria-label` 也不使用未转义拼接。
- JS 重绘列表只用 `textContent`，防止收件人字符串被当作 HTML 执行；虽然服务端已校验邮箱，仍不放松 DOM 侧约束。
- 列表有可见标题「新 Issue 收件人」；添加输入框有 label；错误容器有 `role="alert"`；删除按钮有可区分的无障碍名称。
- 表单仍带 `csrf_token`；`POST /repos/{id}` 仍由 `require_csrf` 保护。
- 不把收件人邮箱写入日志；现有通知日志只记录数量。

### 4.5 交互状态汇总

| 状态 | 展示 / 行为 |
| --- | --- |
| 无收件人 | 列表显示「暂无收件人」；textarea 为空；保存后不发信 |
| 有收件人 | 每行邮箱 + 删除按钮；textarea 为换行列表 |
| 添加合法邮箱 | 立即出现在列表；输入框清空；textarea 同步；不提交表单 |
| 添加非法 / 重复邮箱 | 输入框下方红色提示；不进入列表；textarea 不变 |
| 删除一项 | 从列表和 textarea 移除；未保存前数据库不变 |
| 点「保存」 | 提交完整列表；成功 303 + flash「已保存」；失败 200 保留本页并指出字段 |
| 校验失败（服务端） | 页顶 `alert-error` + 字段下方错误；数据库保持原值；邮箱错误时保留原始 textarea |
| 有进行中任务 | 列表只读；添加 / 删除 / 保存禁用；提示暂不可改路径或收件人 |
| 无 JavaScript | 列表只读展示 + 可编辑 textarea；可手工增删后保存 |

## 5. 影响面

### 5.1 代码

| 文件 | 变更 |
| --- | --- |
| `app/templates/repo.html` | 收件人区域改为列表 + 添加区 + 回退 textarea；增加 `data-gw-notify-*` 钩子与 `{% block scripts %}` 原生脚本；更新帮助文案和禁用态文案 |
| `app/api/v1/repos.py` | `_repo_page_context` 增加 `notify_email_items` / `notify_enhance`；POST 失败分支按「邮箱错误 / 其它字段错误」传入不同列表；保存逻辑不变 |
| `app/services/issue_notify.py` | `parse_notify_emails` 把重复项从静默跳过改为返回错误；其余通知函数不改 |
| `tests/test_issue_notify.py` | 更新拆分 / 去重测试；新增重复报错、空列表、保存空值、非法值不落库的断言 |
| `tests/test_repos.py` / `tests/test_ui.py` | 按实际模板结构补充 GET 列表、字段错误、禁用态和 `data-gw-notify` 钩子断言；不引入浏览器测试框架 |
| 数据库 / Alembic | 无变更 |
| `app/models/repository.py` | 无变更 |

### 5.2 兼容性

- `POST /repos/{id}` 仍只要求一个 `notify_emails` 字段，CSRF、路径校验、成功 303、错误 200 的契约不变。
- 旧页面 / 外部脚本若直接 POST 重复邮箱，以前会被静默去重，现在会得到 200 字段错误；这是本迭代有意的行为变化，符合「重复要有明确提示」。除此之外不改变发信结果。
- 现有数据库中的邮箱数组无需迁移；页面读取顺序即数组顺序，不做排序。
- 无 JS 用户仍可使用原 textarea 流程，功能不丢失；只是列表删除按钮不可用。
- 不新增 npm 依赖、CSS 构建步骤或外部 CDN 资源。

### 5.3 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 服务端渲染列表与 JS 列表重复 / 不一致 | 以 textarea 为唯一提交源；JS 初始化时从 textarea 解析并接管列表；服务端保存后重新渲染 |
| 邮箱含引号 / HTML 特殊字符导致 DOM 注入 | 服务端自动转义；JS 只用 `textContent` |
| 用户输入后未点「添加」直接保存 | 表单 `submit` 监听器再次同步；未添加的输入不进入列表（符合「添加后才进入列表」） |
| 前端校验与后端校验不一致 | 前端只做即时提示，服务端 `parse_notify_emails` 始终是最终判定；错误在 200 页面明示 |
| 重复值策略变化影响旧调用 | 仅仓库页使用该函数；测试覆盖并记录在「待确认」 |
| 禁用态下仍能通过 DOM 移除按钮 | 服务端 `form_disabled` 只读 + 按钮 `disabled`；保存路由仍按 active Job 拒绝 |

### 5.4 文档

本迭代只写本文件，不修改基石。当前 `docs/architecture/design.md` 的「仓库页面」与数据模型章节尚未记录 `notify_emails` 的详细规则（基石入口摘要已收录该功能）；是否单独补基石不在本 Issue 范围，见「待确认 6」。

## 6. 验收

### 6.1 功能

- [ ] 打开仓库页，已保存的收件人以列表展示，每行一个邮箱；无收件人时显示「暂无收件人」。
- [ ] 在添加框输入合法邮箱并点「添加」，邮箱进入列表，输入框清空；点「保存」后刷新页面仍在列表中，数据库 `repository.notify_emails` 与列表一致。
- [ ] 添加非法邮箱时出现明确错误（`非法邮箱：...`），不进入列表，数据库不变。
- [ ] 添加重复邮箱（大小写不同也算重复）时出现明确错误（`重复邮箱：...`），不进入列表，数据库不变。
- [ ] 删除列表中某一项后点「保存」，数据库中对应邮箱被移除；刷新页面不再显示。
- [ ] 删除全部并保存后 `notify_emails == []`；新 Issue 首次入库不发送通知。
- [ ] 有进行中的任务时，收件人列表只读，添加 / 删除 / 保存均不可用，提示文案包含收件人。
- [ ] 缺少 CSRF 的 POST 仍被拒绝，不写数据库。
- [ ] 禁用 JavaScript 时，列表仍可见，textarea 可编辑；手工增删后保存能正确落库。

### 6.2 通知回归

- [ ] 首次入库（Webhook / 全量同步）且收件人非空、邮件已启用、密码存在时，通知发送一次。
- [ ] 同一 Issue 再次同步不重复发送（`notify_email_sent_at` 生效）。
- [ ] 收件人为空、邮件未启用或缺 `SMTP_PASSWORD` 时不发送，且不报错。
- [ ] SMTP 发送失败只记日志，Issue 仍正常入库 / 同步，不影响 Webhook 202 与 Worker 流程。
- [ ] 邮件主题、正文和收件人解析行为与改动前一致（重复值策略除外）。

### 6.3 测试建议

- `pytest tests/test_issue_notify.py tests/test_repos.py tests/test_ui.py` 通过。
- 新增 / 更新的服务端断言：
  - GET 页面包含已保存邮箱和 `data-gw-notify-*` 钩子；
  - 提交换行列表后数据库数组正确；
  - 提交空字符串后数组为空；
  - 提交非法值 / 重复值返回 200、包含对应错误、数据库保持原值；
  - 有 active Job 时 POST 不修改收件人。
- 前端脚本不新增浏览器测试依赖；至少用模板断言确认添加输入、删除按钮、回退 textarea 和脚本钩子存在。人工验证 JS 开关两种路径。

## 7. 待确认

1. **重复值的服务端语义**：现实现 `parse_notify_emails` 对重复邮箱静默去重，本设计按 Issue 要求改为报错。若存在依赖静默去重的调用方，需要在实现前确认；目前仓库内只有仓库页保存使用该函数。
2. **无 JS 回退的形态**：本设计保留可编辑 textarea（可手工增删，但没有逐行按钮），以满足「至少仍能完成增删」。如果产品要求无 JS 也有逐行删除 / 添加按钮，则需要额外的服务端草稿或多步 POST，本文未采用。
3. **收件人数量与长度上限**：Issue 未规定。当前仅受数据库 `String(320)` 和邮箱格式约束，本迭代不新增业务上限；是否需要限制最大收件人数或单个地址长度待确认。
4. **显示名格式**：现有服务端接受 `Name <a@example.com>` 并规范化为 `a@example.com`；本设计的添加输入框以纯邮箱为主，浏览器 `type=email` 可能拒绝显示名。是否需要在前端明确支持显示名待确认。
5. **「添加」是否即时落库**：本文按 Issue 描述设计为只进入表单列表，点「保存」才写库。如果期望「添加即保存」，需要新增独立 POST，且会与现有「保存」语义分离，本文不采用。
6. **基石同步**：`docs/architecture/design.md` 的仓库页面与数据模型尚未详细记录 `notify_emails`；本迭代只写增量，是否另开文档补齐由维护者决定。
