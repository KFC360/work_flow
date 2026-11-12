# v0012-24 设置页邮件发件配置与可复用发件能力

> 迭代：v0012 · Issue #24。本文只描述相对基石 [`docs/README.md`](../README.md) 与 [`docs/architecture/design.md`](../architecture/design.md) 的增量，不重复完整产品设计。
>
> 基石中与本迭代直接相关的约定：全站配置只放项目根 `config.yaml`，设置页是唯一写入处，写入采用「临时文件 + 原子替换」；密钥只放环境变量；设置页 `GET/POST /settings` 已存在，页面 POST 带 CSRF，成功后 303 回本页并 flash。

## 1. 背景

当前 `config.yaml` 只有 `agent` 一个可写配置，设置页也只提供代理单选。系统没有任何邮件发件能力，运维无法在页面配置 SMTP，业务代码也没有可复用的发信入口。

本迭代补齐三件事：

1. `config.yaml` 增加邮件发件段，只存非密钥参数；
2. 设置页把「代理 + 邮件」放进同一张表单，一次保存；
3. 提供公共 `send_mail` 与设置页试发，业务事件触发（任务失败、PR 合并等）留待后续 Issue。

## 2. 目标

- 扩展 `config.yaml` 与 `config.yaml.example`，增加 `mail` 段；真实 `config.yaml` 继续不进 git。
- 沿用原子替换写入，一次保存同时写回 `agent` 与邮件非密钥字段；Web 与 Worker 共用同一读取模块。
- SMTP 密码只从环境变量读取，yaml 与页面均不保存、不回显明文；设置页只显示「已配置 / 未配置」。
- 设置页同一表单保存代理与邮件配置，保存成功 303 + flash，校验失败给出明确提示。
- 提供公共 `send_mail(to, subject, html_body, *, text_fallback=None)`，支持简单 HTML，并对 HTML 做白名单消毒。
- 设置页提供「发送测试邮件」，成功 / 失败均有明确 flash；未启用、缺必填字段或缺密码时返回清晰原因。
- 相关 pytest 通过，并补充 mock SMTP 的单元测试。

## 3. 非目标

- 不把 SMTP 密码写入 `config.yaml`、数据库或页面隐藏字段。
- 不新建 `setting` 表，不做多套邮件配置或按仓库覆盖。
- 不做附件、批量营销、收件箱、模板市场、退信处理。
- 不在本迭代绑定任务失败、PR 合并等业务事件发信。
- 不把 JWT、数据库地址、GitHub Token 等迁移进 `config.yaml`。
- 不做异步发信队列、失败重试或发信历史表；试发为同步请求。

## 4. 方案

### 4.1 总体结构

```
设置页 /settings（同一表单）
  ├─ agent 单选 ─────────────┐
  └─ mail 非密钥字段 ────────┤
                             ▼
                 app/services/app_config.py
                 （读 yaml / 校验 / 原子写）
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
      config.yaml（无密码）          环境变量 SMTP_PASSWORD
                                            │
                                            ▼
                              app/services/mail.py
                              send_mail(...) → SMTP
                                            ▲
                              设置页试发 POST /settings/mail/test
```

- 新增 `app/services/app_config.py`，统一读写 `agent` 与 `mail`，替代原先 `config_agent.py` 的读写职责。
- 新增 `app/services/mail.py`，只依赖 `app_config` 与进程环境变量，不依赖 Web 请求，便于业务代码和测试复用。
- 设置页路由只做表单解析、校验结果渲染与 flash，不直接拼 SMTP 细节。

### 4.2 `config.yaml` 结构与约束

```yaml
# 全站代理：opencode 或 claude
agent: claude

# 邮件发件（密码只放环境变量 SMTP_PASSWORD，不写在这里）
mail:
  enabled: false
  smtp_host: smtp.example.com
  smtp_port: 587
  security: starttls      # ssl | starttls | none
  username: ""            # SMTP 认证用户，可为空（匿名中继）
  from_address: notify@example.com
  from_name: GitHub 工作流
  default_to: ""          # 试发默认收件人，可为空
```

字段与默认值：

| yaml 键 | 页面字段名 | 类型 / 默认 | 说明 |
| --- | --- | --- | --- |
| `mail.enabled` | `mail_enabled`（checkbox） | bool，默认 `false` | 未勾选时不得发信 |
| `mail.smtp_host` | `mail_smtp_host` | str，默认空 | 主机名，不带协议与路径 |
| `mail.smtp_port` | `mail_smtp_port` | int，默认 `587` | 1–65535 |
| `mail.security` | `mail_security` | 枚举，默认 `starttls` | `ssl` / `starttls` / `none` |
| `mail.username` | `mail_username` | str，默认空 | 认证用户，可为空；不是密码 |
| `mail.from_address` | `mail_from_address` | str，默认空 | 信封 From 地址 |
| `mail.from_name` | `mail_from_name` | str，默认空 | 可选显示名 |
| `mail.default_to` | `mail_default_to` | str，默认空 | 可选，试发默认目标 |

约束：

- `agent` 仍只允许 `opencode` / `claude`；本迭代表单仍要求选择代理。
- 密码名默认 `SMTP_PASSWORD`，只从环境变量读取；`config.yaml`、`config.yaml.example`、页面表单和日志中都不出现密码值。
- 文件不存在、YAML 解析失败、`mail` 段缺失或类型不对时，读取结果为「邮件未启用 + 空字段」，并在设置页给出配置警告；不得因此让设置页 500。
- 写入时保留 `agent` 与 `mail` 之外的未知顶层键（向前兼容），只更新本迭代负责的键。
- `config.yaml.example` 同步上述结构；`.env.example` 增加 `SMTP_PASSWORD=`。
- 真实 `config.yaml` 继续由 `.gitignore` 忽略。

### 4.3 配置读写模块与原子写

新增 `app/services/app_config.py`：

```python
@dataclass(frozen=True)
class MailConfig:
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 0
    security: str = ""
    username: str = ""
    from_address: str = ""
    from_name: str = ""
    default_to: str = ""

@dataclass(frozen=True)
class AppConfig:
    agent: str | None
    mail: MailConfig
    warning: str | None  # 文件无法解析等非致命提示

def read_app_config() -> AppConfig: ...
def read_agent() -> str | None: ...          # 保持原语义：非法/缺失返回 None
def read_mail_config() -> MailConfig: ...
def write_app_config(agent: str, mail: MailConfig) -> None: ...
```

- `read_app_config()` 用 `yaml.safe_load` 读取；只接受顶层 dict。`enabled` 仅接受 YAML 布尔真值；端口接受整数或纯数字字符串，否则记为 `0`；`security` 小写化后只接受枚举值，否则记为空串；字符串字段 `strip()`。
- 不把非法值静默纠正为危险默认。例如 `security: tls` 不会被当成 `starttls`，而是在保存 / 发信时报告「加密方式无效」。
- `write_app_config()` 先读现有顶层 dict，更新 `agent` 与 `mail` 下的全部非密钥键，再用 `path.with_name(path.name + ".tmp")` 写临时文件并 `os.replace` 原子替换；临时文件写入或替换失败时清理残留并抛出异常，由路由转成错误提示。`mail` 的八个键全部写回（含空串），保证页面与文件一一对应。
- `app/services/config_agent.py` 退化为兼容薄层：`read_agent` / `write_agent` 从 `app_config` 重新导出，避免一次改动所有调用点；不再在薄层里单独打开文件。现有测试若 monkeypatch 该模块的 `get_settings`，需改为 patch `app.services.app_config.get_settings`，否则会因属性不存在而立刻失败，而不是误写真实 `config.yaml`。
- 写入路径仍取 `get_settings().config_yaml_path`，Web 与 Worker 进程读同一份文件。

### 4.4 密码来源与状态显示

- `mail.py` 提供 `get_smtp_password() -> str`，直接读 `os.getenv("SMTP_PASSWORD", "")` 并 `strip()`；密码不进入任何 dataclass 字段、`repr` 或模板上下文。
- `password_configured() -> bool` 只判断非空。设置页据此显示 badge「已配置」/「未配置」，不提供密码输入框。
- `.env` 在进程启动时由 `python-dotenv` 载入；修改 `.env` 后需重启 Web / Worker 才生效。页面提示中写明这一点。
- 页面不提供改密码入口；提示修改方式为服务器环境变量或 `.env`。

### 4.5 公共发件 API

`app/services/mail.py`：

```python
class MailError(Exception):
    """邮件配置或发送失败。message 可直接展示，不含密码。"""

class MailConfigError(MailError): ...
class MailSendError(MailError): ...

def send_mail(
    to: str | Iterable[str],
    subject: str,
    html_body: str,
    *,
    text_fallback: str | None = None,
) -> None:
    """按 config.yaml + SMTP_PASSWORD 发送一封邮件；失败抛 MailError。"""
```

发送前检查顺序与错误：

| 检查 | 错误码 / 提示 |
| --- | --- |
| `mail.enabled` 为假 | `disabled`「邮件发件未启用」 |
| `smtp_host` 为空 | `missing_host`「未配置 SMTP 主机」 |
| `smtp_port` 不在 1–65535 | `missing_port` / `invalid_port`「未配置或非法的 SMTP 端口」 |
| `security` 不在枚举 | `invalid_security`「加密方式无效」 |
| `from_address` 为空或格式非法 | `missing_from` / `invalid_from`「发件人地址缺失或无效」 |
| `SMTP_PASSWORD` 为空 | `missing_password`「未配置环境变量 SMTP_PASSWORD」 |
| 收件人为空 | `missing_recipient`「缺少收件人」 |
| 主题或正文为空 | `empty_message`「邮件主题或正文为空」 |
| 收件人 / 主题 / 显示名含 CR/LF 或地址非法 | `invalid_recipient` / `invalid_header`「地址或邮件头非法」 |
| SMTP 连接、认证、发送异常 | `smtp_error`「发送失败：<类别>（详见日志）」 |

- `to` 为字符串时按逗号拆分；也接受字符串序列。逐个用 `email.utils.parseaddr` 解析，要求存在 `@`，拒绝 `\r`、`\n`，防止邮件头注入；主题与 `from_name` 同样拒绝 CR/LF。
- 连接：
  - `security=ssl`：`smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SECONDS, context=ssl.create_default_context())`；
  - `security=starttls`：`smtplib.SMTP(...)` → `ehlo()` → `starttls(context=...)` → 再次 `ehlo()`；
  - `security=none`：明文 `smtplib.SMTP(...)`，页面需显示风险提示。
- `username` 非空才调用 `login(username, password)`；密码校验仍按上表始终要求 `SMTP_PASSWORD` 非空（见待确认 4）。
- 邮件用标准库 `email.message.EmailMessage`：`set_content(text)` 后 `add_alternative(html, subtype="html")`；`From` 用 `formataddr((from_name, from_address))`；`To` 为解析后的地址列表。
- `text_fallback` 为空时，从**消毒后的 HTML** 粗略还原纯文本：块级标签与 `<br>` 转换行、去标签、`html.unescape`、压缩多余空白。只作为纯文本客户端的兜底，不承诺与 HTML 完全等价。
- `send_mail` 内部完成校验、消毒、组信与发送；调用方无需重复处理。发送失败一律抛 `MailError` 子类，不返回布尔值，避免调用方漏判。
- `SMTP_TIMEOUT_SECONDS = 10`；不发异步队列、不自动重试（见待确认 10）。
- 测试可注入：单元测试 monkeypatch `app.services.mail.smtplib.SMTP_SSL` / `SMTP`、`get_smtp_password` 与 `read_mail_config`，无需真实网络。

### 4.6 简单 HTML：白名单与消毒

选择「白名单消毒」而不是「仅内部受信」：公共 API 后续会被业务事件调用，统一在入口处消毒更安全，且仓库已有 `nh3` 依赖（与 Markdown 渲染一致）。

白名单写死在 `app/services/mail.py`：

- 允许标签：`p`、`br`、`a`、`strong`、`b`、`em`、`i`、`ul`、`ol`、`li`、`h1`、`h2`、`h3`、`hr`、`blockquote`。
- 允许属性：仅 `a` 的 `href`、`title`。
- 允许协议：`http`、`https`、`mailto`；相对链接拒绝。
- 剥离内容的高危容器：`script`、`style`、`iframe`、`object`、`embed`、`svg`、`math`、`form`。
- 设置 `link_rel="noopener noreferrer"`；消毒异常时 **不发送未消毒内容**，转为 `MailSendError`。
- `send_mail` 对调用方传入的 `html_body` 一律消毒；试发固定模板同样走该路径，不设绕过分支。

### 4.7 设置页 UI 与路由

`GET /settings` 在同一张卡片内渲染：

1. 全站代理：保留现有两个单选卡片；
2. 邮件发件：开关、SMTP 主机、端口、加密方式（`select`）、用户名、发件人地址、发件人显示名、默认收件人；
3. 一个「保存」按钮，提交到 `POST /settings`；
4. 密码状态行：badge「已配置」/「未配置」，旁注「密码只从环境变量 `SMTP_PASSWORD` 读取，页面不显示也不修改」；
5. 试发区域：独立小表单（HTML 不允许嵌套表单），可选「收件地址」输入框 + 「发送测试邮件」按钮。

表单细节：

- 所有字段放在同一个 `<form method="post" action="/settings">`，隐藏 `csrf_token`；复选框未勾选时浏览器不提交，后端按 `False` 处理。
- 邮件字段用 `name="mail_*"`（见 4.2 表），`agent` 保持原名。
- 默认值取已保存配置；无配置时端口 `587`、加密方式 `starttls`，其余为空。
- 页面提示：
  - 未选择代理：沿用现有 `alert-warning`「尚未选择代理」。
  - `mail.enabled` 为真且缺主机 / 端口 / 发件人：`alert-error` 列出缺失项，并说明试发不可用。
  - `mail.enabled` 为真但密码未配置：`alert-warning`「SMTP 密码未配置，保存后仍无法发信」。
  - `security=none`：`alert-warning`「不加密连接会明文传输邮件内容与认证信息」。
  - `config.yaml` 无法解析：`alert-warning` 提示文件读取失败，保存将重建两个已知段。
- 保存校验（服务端）：
  - `agent` 必填且属于枚举；
  - `mail_enabled=false` 时允许其余字段为空，但已填写的值仍做语法校验（端口、加密方式、地址格式）；
  - `mail_enabled=true` 时主机、端口、加密方式、发件人地址必填；
  - 显示名 / 主题禁止 CR/LF；
  - 密码不参与保存校验，缺失只警告，不阻止保存。
- 校验失败：返回 200 重新渲染本页，保留用户已填值，按字段显示 `alert-error`，不写文件；CSRF 失败仍按现有依赖行为处理。
- 校验通过：`write_app_config()` 一次写入 `agent` 与 `mail`，303 到 `/settings?flash=ok&msg=已保存`；写入异常 303 到 `flash=error` 并给出去敏提示。

`POST /settings/mail/test`：

- 独立路由，要求登录 + CSRF；表单字段 `to` 可选。
- 收件地址优先取表单 `to`，为空则取已保存的 `mail.default_to`；两者都为空则 flash 错误「请填写收件地址或配置默认收件人」。
- **只使用已保存配置**，不读取表单里尚未保存的邮件字段；页面需写明「试发使用已保存配置」。
- 固定简单 HTML 模板：标题「GitHub 工作流测试邮件」、发送时间（UTC）、一句「收到此邮件说明 SMTP 配置可用」。模板不含用户可控拼接；所有值仍经消毒。
- 成功 flash「测试邮件已发送」；失败捕获 `MailError`，flash `发送失败：<message>`，不展示 SMTP 原始异常或任何凭据。
- 同步发送最长约 10 秒；提交按钮复用现有 `data-gw-submit` 禁用逻辑，防止重复点击。是否再加服务端频率限制见待确认 6。

### 4.8 错误与日志

- 页面可见错误只包含检查表里的短消息和 SMTP 异常类别；完整异常写应用日志，便于排查。
- 日志禁止出现密码、`login()` 参数、完整认证命令；不打印邮件正文（可能含业务信息）。
- 建议日志格式：成功 `mail sent to N recipient(s)`；失败 `mail send failed: <ExceptionType> code=<smtp_code>`，其中不含用户名、密码、收件人全量地址。
- 配置读取告警可记录 `config.yaml` 路径与 YAML 错误类型，不记录文件内容。

## 5. 影响面

### 5.1 文件变更（代码生成阶段）

| 文件 | 变更 |
| --- | --- |
| `app/services/app_config.py` | 新增：统一读写、`MailConfig`、字段级校验、原子替换 |
| `app/services/config_agent.py` | 收敛为兼容导出（`read_agent` / `write_agent`） |
| `app/services/mail.py` | 新增：`send_mail`、HTML 消毒、纯文本回退、SMTP 连接与错误类型 |
| `app/api/v1/settings.py` | 同一表单保存代理 + 邮件；新增试发路由；补充模板上下文 |
| `app/templates/settings.html` | 邮件字段、密码状态、试发表单、告警与错误展示 |
| `config.yaml.example` | 增加 `mail` 段 |
| `.env.example` | 增加 `SMTP_PASSWORD=` 与注释 |
| `README.md` | 环境变量与配置说明补充邮件段、密码只走环境变量、试发入口 |
| `docs/README.md` | 系统要点补充「设置页管理代理与邮件发件（非密钥）」 |
| `docs/architecture/design.md` | 更新「全站配置 `config.yaml`」与「设置 `/settings`」两节 |
| `tests/test_mail.py` | 新增发件与消毒单元测试 |
| `tests/test_repos.py` / `tests/test_ui.py` | 扩展设置页保存、密码状态、试发用例 |

### 5.2 数据与兼容

- 无数据库迁移、无新表；不改变 Issue / Job 状态机。
- 旧 `config.yaml` 只有 `agent` 时正常工作，邮件默认关闭；首次保存会自动补齐 `mail` 段。
- `read_agent()` 语义不变，Worker 现有调用点（`app/tasks/jobs.py`、`app/services/actions.py`、`app/api/v1/issues.py`）无需改逻辑。
- 保存邮件配置会重写整个 `config.yaml`，但保留未知顶层键；注释与手工排版不保留（现有 `yaml.safe_dump` 行为一致）。

### 5.3 安全

- 密码只存在于进程环境变量，不进 yaml、数据库、模板、日志或异常消息。
- 页面只回显「已配置 / 未配置」，表单无密码字段，避免浏览器自动填充与历史记录泄漏。
- HTML 在发送入口统一消毒，脚本、事件属性、危险协议与相对链接被移除。
- 邮件头字段做 CR/LF 校验，防止头注入。
- 默认 `starttls` / `ssl`；`none` 明确告警。
- 设置页当前只要求登录用户；试发会真实外发邮件，是否限制管理员见待确认 6。

### 5.4 测试计划

1. **配置读写**
   - 空文件 / 文件不存在 → 邮件默认关闭；
   - 保存 `agent + mail` 后 YAML 同时包含两段且无密码键；
   - 已有未知顶层键被保留；
   - 原子替换：写入后原路径内容完整，临时文件不残留；
   - 非法端口 / 非法加密方式 / 非法地址在启用时被拒绝，关闭时允许留空。
2. **`send_mail`（mock SMTP）**
   - `ssl` 使用 `SMTP_SSL`，`starttls` 调用 `starttls()`，`none` 使用明文 `SMTP`；
   - 用户名非空时调用 `login`，空时跳过；
   - 收件人、主题、HTML 与纯文本回退进入 `EmailMessage`；
   - 未启用、缺主机、缺端口、缺发件人、缺 `SMTP_PASSWORD`、缺收件人分别抛出对应 `MailConfigError`；
   - SMTP 异常包装为 `MailSendError`，消息不含密码；
   - `html_body` 中的 `<script>`、`onerror`、`javascript:` 链接被剥离，安全标签保留；
   - 主题 / 地址中的 `\r\n` 被拒绝。
3. **设置页**
   - 同一 POST 同时写入代理与邮件字段，303 + flash；
   - 页面显示密码「已配置 / 未配置」，任何响应与模板上下文中都不出现密码值；
   - 启用但缺必填字段 → 200 + 字段错误，文件未变；
   - 试发成功 / 失败 flash 正确，试发只读已保存配置；
   - CSRF 缺失被拒绝。
4. **回归**
   - 现有代理保存、Worker 读取代理、`tests/test_repos.py` 相关用例通过；
   - `pytest` 全量通过。

## 6. 验收

- [ ] 设置页同一表单可一次保存代理 + 邮件非密钥配置到 `config.yaml`，保存后 303 + flash。
- [ ] `config.yaml` 与 `config.yaml.example` 无密码字段；`.env.example` 含 `SMTP_PASSWORD`（最终定名见待确认 1）。
- [ ] 页面只显示密码「已配置 / 未配置」，无明文回显、无密码输入框；日志与异常消息无密码。
- [ ] 配置正确且启用时，试发成功并收到简单 HTML 邮件；HTML 中危险标签 / 属性被消毒。
- [ ] 未启用、缺主机 / 端口 / 发件人、缺 `SMTP_PASSWORD`、缺收件人时，试发与 `send_mail` 均失败且原因清晰。
- [ ] 公共 `send_mail` 可通过 mock SMTP 做单元测试，覆盖成功与各类失败分支。
- [ ] 原子写行为保持；旧版仅含 `agent` 的配置可正常读取与升级；未知顶层键保留。
- [ ] 相关 pytest 通过；按流水线在 `dev_{number}` 分支开 PR。
- [ ] `docs/README.md`、`README.md`、`docs/architecture/design.md` 已同步邮件配置、密码环境变量与设置页行为。

## 7. 待确认

以下规则 Issue 未给出最终结论，本文按括号内方案实现；若需调整应在生成代码前确认。

1. **环境变量最终名**：本文用 `SMTP_PASSWORD`。是否加前缀（如 `MAIL_SMTP_PASSWORD`）？
2. **yaml 键名**：本文用顶层 `mail`，字段 `smtp_host` / `smtp_port` / `security` / `username` / `from_address` / `from_name` / `default_to`。是否与团队既有命名一致？
3. **启用但密码未配置**：本文允许保存并显示警告，只在发信时失败。是否改为保存即拒绝？
4. **匿名中继**：`username` 为空时本文仍要求 `SMTP_PASSWORD` 非空（按 Issue 验收文字）。无认证 SMTP 是否应允许密码为空？
5. **`security=none`**：本文允许保存但页面告警。生产环境是否应直接禁止？
6. **试发权限与频率**：设置页目前只要求登录。是否需要限制管理员角色、增加服务端冷却或每日次数上限？本文未加服务端限流。
7. **试发读取哪份配置**：本文只读已保存配置，不读表单未保存值。是否要求试发前先保存？
8. **多收件人**：本文 `to` 支持逗号分隔或序列。是否只允许单个收件人？
9. **未知顶层键**：本文保存时保留。是否应改为严格 schema、遇到未知键报错？
10. **超时与重试**：本文固定 10 秒、不自动重试、不同步重试。是否需要可配置超时或失败重试？
11. **HTML 白名单**：本文固定 15 个标签并允许 `mailto`。是否需要支持图片、表格或内联样式（`style` 属性）？

---

参考：基石 [`docs/README.md`](../README.md)；完整设计 [`docs/architecture/design.md`](../architecture/design.md)（「全站配置 `config.yaml`」「设置 `/settings`」）。
