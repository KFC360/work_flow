# 仓库页 GitHub 资料卡片增强（v0002 / Issue #4）

- 迭代：`v0002`，对应 GitHub Issue `#4`
- 文档路径：`docs/v0002-4/design.md`
- 状态：设计稿
- 基线：基石入口 [`docs/README.md`](../README.md)；完整产品设计 [`docs/architecture/design.md`](../architecture/design.md)
- 性质：相对基石的**仓库页展示与只读聚合增量**，不替代基石，不改 Webhook / Job / 写文档·生成代码状态机

## 1. 背景

仓库页 `/repos/{id}` 的「GitHub 资料」卡片在 v0001 界面改版后布局已经可用，但信息密度仍然偏低：卡片主体只有描述、`github_full_name`、默认分支、公私有、最近同步和 GitHub 外链。操作员要判断「这个仓库能不能写文档 / 生成代码」，还需要另开 GitHub 核对语言、活跃度、归档状态，再翻 Issue 列表数本系统收录了多少 Issue，最后去 Issue 详情确认基石是否存在。

这与基石的定位不一致。基石已经规定：

- `repository` 的 GitHub 字段由 API 覆盖，`local_path`、`doc_dir` 只由仓库页面写入，同步时保持原值。
- 仓库页面的只读区应展示完整名称、描述、默认分支、是否私有、GitHub 链接、最近同步时间和 `sync_error`。
- 本系统 Issue 的「未结束」指功能迭代里还不是已建 PR，以及人工介入的待处理，且 GitHub 状态为 open、未被删除。
- 基石入口固定为 `{doc_dir}/README.md`，页面按本地 `origin/{default_branch}` ref 判断是否缺失，GET 不执行 fetch。

本迭代在**不改变**上述业务规则的前提下，把「GitHub 资料」卡片从少量身份字段扩展为「身份 + 指标 + 链接 + 本系统就绪摘要」，并把已经入库但尚未展示的字段先呈现出来。

本文档编写使用 `documentation` skill；实现涉及版面时按 Issue 要求加载 `ui-ux-pro-max`，继续沿用现有 `gw-card`、`icon()`、`badge()` 与浅色运维台视觉。

## 2. 目标

1. **先展示已有数据**：把 `company`、`github_repo_id`、`name`、本行 `created_at` 等已入库字段放进资料卡，不依赖迁移即可完成。
2. **同步更多 GitHub 元数据**：扩展 `repository` 与同步映射，展示语言、Star / Fork、GitHub 侧 open issues、主题、许可证、归档 / 禁用、最近推送、项目主页和可见性。
3. **补充本系统就绪摘要**：在资料卡内聚合本地 Issue 数量、`local_path` 是否填写、origin 是否匹配、基石入口是否存在，以及最近同步成败文案。
4. **扫一眼可判断**：归档 / 禁用、origin 不一致、基石缺失、同步失败等风险有明确警告；GitHub 侧计数与本系统计数不混为一谈。
5. **版面不凌乱**：桌面 `lg` 仍是「GitHub 资料 + 本地配置」两栏；空值统一「—」，不产生成排空行；小屏继续保证路径表单不被长资料压到下方。
6. **保持只读与性能边界**：打开页面不调用 GitHub API；只使用库内数据和本地 git 只读命令，不执行 fetch。

成功标准以第 9 节验收清单为准。

## 3. 非目标

- 不在本页嵌入 GitHub README 渲染、Star 趋势图、贡献者列表或仓库文件树。
- 不在每次打开 `/repos/{id}` 时调用 GitHub API；新字段仍靠 Webhook 同步与「重新同步」刷新。
- 不新增同步历史表，不记录每次同步的完整快照或失败历史；`sync_error` 成功后清空的现有语义不变。
- 不修改 `local_path` / `doc_dir` 的表单校验、保存流程、进行中任务禁用规则。
- 不改变 Webhook 验签、Inbox、Job、Worker、Pipeline、写文档 / 生成代码状态机与按钮入队条件。
- 不因为仓库 archived / disabled 而禁用页面按钮；只做风险提示，是否可执行仍以现有条件和任务结果为准。
- 不合并 PR、不跑 CI；实现阶段已有 GitHub Actions。
- 不做暗色主题、多主题切换，不引入新的前端框架或构建链。
- 不新增仓库的新建、删除、改名入口，也不在页面修改从 GitHub 同步来的字段。

## 4. 相对基石的增量声明

### 4.1 保持不变

| 维度 | 结论 |
| --- | --- |
| 仓库身份键 | 仍按 `github_repo_id` 唯一；改名 / 转让仍按 id 对上原行 |
| 本地配置 | `local_path`、`doc_dir` 只由仓库页表单写入；同步不覆盖 |
| 同步失败语义 | 只更新 `sync_error`，不清 `local_path` / `doc_dir` |
| Webhook / Inbox | 验签、202、重试、failed 人工重试逻辑不变 |
| Job / Worker | 单 Worker、双循环、worktree、代理调用、PR 创建逻辑不变 |
| Issue 状态机 | `issue.status`、`kind`、`codegen_phase`、`job.status`、`github_state` 全部不变 |
| 按钮条件 | `actions_for` 的启用 / 禁用 / 链接条件不变 |
| 鉴权 | JWT、cookie、CSRF、`require_page_user` / `require_fragment_user` 不变 |
| 仓库页表单 | 字段、校验顺序、错误文案、进行中任务禁用规则不变 |

### 4.2 本迭代增量

| 增量 | 说明 |
| --- | --- |
| `repository` 新列 | 增加 GitHub 元数据列，见 6.3；Alembic 新增加列迁移，无回填 |
| 同步映射 | `sync_owner_and_repo` / `repository_crud.upsert_from_github` 写入新字段 |
| 仓库页上下文 | GET 与保存失败重渲染统一计算 origin、基石、Issue 摘要 |
| 页面 | 重构 `repo.html` 的「GitHub 资料」卡片，增加「本系统」小节 |
| Issue 列表筛选 | 增加展示层 `status=unfinished`（未建 PR），用于摘要计数与列表同口径跳转 |
| 只读 git 检查 | 新增非抛异常的 origin 检查；基石检查复用现有 `read_foundation_from_origin`，仍不 fetch |
| 测试 | 同步新字段、归档提示、origin / 基石状态、摘要计数与筛选链接 |

### 4.3 与 v0001、基石的关系

- v0001 只做界面改版，未扩展数据模型；本迭代沿用其 `page_header`、`gw-card`、`icon`、`badge` 组件与视觉 token。
- v0001 第 15 节「待确认 #4」曾把 `origin_mismatch` 只读检查留到后续。本 Issue 明确要求展示 origin 是否匹配，因此本迭代实现 GET 只读检查，取代该待确认项的默认处理；仍不 fetch、不写本地仓库。
- **基石同步**：本迭代新增 `repository` 列，按基石「改数据模型先更新基石」的约定，合并前应同步更新 `docs/architecture/design.md` 的 `repository` 表、同步公司与仓库步骤、仓库页面只读区说明。本次任务只允许写 `docs/v0002-4/design.md`，未修改基石正文；该动作列入第 10 节待确认，由实现 PR 或后续人工补齐。

## 5. 现状与差距

| 方面 | 现状 | 差距 |
| --- | --- | --- |
| 资料卡身份区 | 完整名称、默认分支、是否私有、同步时间、GitHub 链接、描述 | 未展示所属公司、短名、GitHub 仓库数字 id、本系统收录时间 |
| GitHub 指标 | 无 | 无语言、Star / Fork、GitHub open issues、主题、许可证、最近推送、项目主页 |
| 风险状态 | 只有私有 / 公开 | 无 archived / disabled 提示；无法一眼看出仓库是否已归档 |
| 本系统摘要 | 无 | 无本地 Issue 统计、无路径 / origin / 基石就绪摘要 |
| origin 检查 | `repo_page` 中 `origin_mismatch=False` 硬编码 | 页面顶部的 origin 警告位实际不会触发 |
| 基石检查 | 只有 Issue 详情调用 `read_foundation_from_origin` | 仓库页看不到基石是否存在 |
| 同步字段 | `upsert_from_github` 只写名称、描述、分支、公私有等基础字段 | 新元数据没有落库位置，重新同步也不会更新 |
| Issue 计数跳转 | 仓库列表只链到全部 open Issue | 无法按「未结束功能迭代 / 人工介入待处理 / 失败」精确跳转 |

## 6. 方案

### 6.1 总体信息架构

页面仍为「GitHub 资料 + 本地配置」两栏，资料卡内部按以下顺序组织：

```text
面包屑：公司 → owner/repo
页头：owner/repo + 「在 GitHub 打开」「查看 Issue」
页头徽章区：可见性 | 默认分支 | 最近同步 | 已归档 / 已禁用（如有）
告警区（沿用现有顺序）：
  1. origin 不一致 alert-warning
  2. repo.sync_error alert-error
  3. 有进行中任务 alert-info

主体 grid lg:grid-cols-3 gap-6
├── 左 lg:col-span-2：GitHub 资料卡
│   ├── 卡片头：标题 + 「重新同步」
│   ├── 归档 / 禁用 alert-warning（卡片顶部）
│   ├── 描述
│   ├── 身份区：公司、短名、GitHub 仓库 ID、完整名称、本系统收录时间
│   ├── 指标区：主语言、星标、Fork、GitHub 开放 Issue、最近推送、许可证
│   ├── 主题标签区
│   ├── 链接区：GitHub 仓库、项目主页、GitHub Issues
│   ├── 分隔线
│   └── 本系统小节：三个 Issue 数字 + 路径 / origin / 基石 / 同步结果
└── 右 lg:col-span-1：本地配置表单（结构不变）
```

约定：

- 公私有 / 可见性、默认分支、最近同步时间只在**页头徽章区**出现一次，卡片不再重复；资料卡只保留完整名称等身份字段。
- 小屏沿用现有顺序：本地配置在前，GitHub 资料在后，避免长资料把路径表单压到页面底部。
- 若 1280px 视觉检查发现左栏过长，可把「本系统」小节改为跨两栏的独立卡片，但字段、顺序和口径不变；默认仍放在资料卡下方，符合 Issue 的「同一卡片下方」。
- 不引入新 CSS 框架；继续使用 `gw-card`、`font-mono-data`、DaisyUI 徽章和 Tailwind 工具类。

### 6.2 A 类：展示已有但未使用的信息

| 字段 | 来源 | 展示方式 | 空值 |
| --- | --- | --- | --- |
| 所属公司 | `company.name` / `company.login` | 公司名为主链接，链到 `/companies/{company_id}`；`name` 与 `login` 不同时以 `@login` 作次要文字 | `—` |
| 短名 | `repository.name` | 等宽或半粗文字，放在身份区 | `—` |
| GitHub 仓库 ID | `repository.github_repo_id` | 等宽文字，标签写「GitHub 仓库 ID」，避免与本地 `repository.id` 混淆 | `—` |
| 完整名称 | `repository.github_full_name` | 等宽，允许 `break-all` | `—` |
| 本系统收录时间 | `repository.created_at` | 标签「收录于」，`YYYY-MM-DD HH:MM UTC`，`title` 保留 ISO | `—` |
| 描述 | `repository.description` | 卡片描述段；为空显示弱化「无描述」 | 「无描述」 |
| 可见性 | `repository.visibility`，回退 `private` | 页头徽章：公开 / 私有 / 内部 | 回退公私有 |
| 默认分支 | `repository.default_branch` | 页头徽章，等宽 | `—` |
| 最近同步 | `repository.synced_at` / `sync_error` | 页头徽章：同步于时间 / 同步失败 / 尚未同步 | 「尚未同步」 |
| GitHub 链接 | `repository.html_url` | 页头「在 GitHub 打开」与卡片链接区 | `—` |

说明：

- 公司名与 `login` 都来自已有 `company` 行，不新增查询；`repo_page` 已经加载 `company`。
- `github_repo_id` 用数字原样展示，不加千分位，便于与 Webhook / GitHub API 对照。
- 时间统一走现有 `gw_time` / `gw_iso` 过滤器，不引入新格式。
- A 类不依赖 6.3 的迁移，可先随模板重构落地；B 类字段在迁移和首次同步后再出现，未同步时按「—」展示。实施顺序允许先完成 A 类并单独验收。

### 6.3 B 类：新增 GitHub 元数据

#### 6.3.1 `repository` 新列

| 列 | 类型 | 可空 / 默认 | 语义与展示 |
| --- | --- | --- | --- |
| `language` | `String(100)` | 可空 | 主语言；空显示「—」 |
| `stargazers_count` | `Integer` | 可空 | Star 数；`0` 是有效值，`NULL` 表示尚未同步 |
| `forks_count` | `Integer` | 可空 | Fork 数；同上 |
| `open_issues_count` | `Integer` | 可空 | GitHub 侧 open issues；**包含 PR**，文案需说明 |
| `topics` | `ARRAY(String(255))` | 可空 | 主题标签；`NULL` 表示尚未同步，`[]` 表示已同步但无主题 |
| `license_spdx` | `String(64)` | 可空 | SPDX 标识，如 `MIT`；`NOASSERTION` 归一为 `NULL` |
| `license_name` | `String(255)` | 可空 | 许可证展示名，如 `MIT License` |
| `archived` | `Boolean` | 非空，默认 `false` | GitHub 归档状态；为真时醒目警告 |
| `disabled` | `Boolean` | 非空，默认 `false` | GitHub 禁用状态；为真时醒目警告 |
| `pushed_at` | `DateTime(timezone=True)` | 可空 | GitHub 最近推送时间；空显示「—」 |
| `homepage` | `String(512)` | 可空 | 项目主页；空串归一为 `NULL` |
| `visibility` | `String(32)` | 可空 | `public` / `private` / `internal`；空时回退 `private` 布尔值 |

类型选择理由：

- 计数列保持可空，而不是 `NOT NULL DEFAULT 0`：迁移后的旧行在重新同步前应显示「—」，不能伪装成 0。
- `archived` / `disabled` 是风险标志，旧行默认 `false`；迁移后到首次重新同步前可能短暂显示「未归档」，这是可接受的最终一致。
- `topics` 用 PostgreSQL 数组，与现有 `issue.label_names` 的存储风格一致；本期不按主题检索，不建 GIN 索引。
- `license_spdx` 与 `license_name` 同时保留：前者适合紧凑展示，后者用于可读名称，避免 `NOASSERTION` 或未知 SPDX 时丢失信息。

#### 6.3.2 Alembic 迁移

新增一个 revision，接在现有初始迁移之后：

```text
revision:      20261111_0002
down_revision: 20261111_0001
file:          app/alembic/versions/20261111_0002_repository_github_meta.py
```

迁移内容：

1. `upgrade()` 用 `op.add_column(..., schema=DB_SCHEMA)` 为 `repository` 增加 6.3.1 的 12 列。
2. `archived` / `disabled` 使用 `nullable=False, server_default=sa.text("false")`，保证已有行可立即读取。
3. 计数、文本、数组、时间列均为 `nullable=True`，不设服务器默认值。
4. 不写数据回填，不调用 GitHub API，不做数据搬迁。
5. `downgrade()` 按相反顺序 `drop_column`。
6. 不新增索引；仓库页只按主键读取。

部署顺序：先执行迁移，再发布 Web / Worker。由于全部是新增可空列或带默认值的非空列，旧进程在迁移后仍可运行，不需要停机窗口；新字段在下次 Webhook 同步或点击「重新同步」后填充。

#### 6.3.3 同步映射

`GitHubClient` 当前 `Accept` 为 `application/vnd.github+json`。为稳定获得 `topics`，在同一个请求上追加 topics 预览媒体类型，不新增请求：

```text
Accept: application/vnd.github+json, application/vnd.github.mercy-preview+json
```

`sync_owner_and_repo` 仍调用一次 `get_repository(github_repo_id)`，从同一份 JSON 映射：

| GitHub JSON | 本地列 | 归一化 |
| --- | --- | --- |
| `language` | `language` | 空串 / 缺失 → `None` |
| `stargazers_count` | `stargazers_count` | 整数；缺失 → `None`；`0` 保留 |
| `forks_count` | `forks_count` | 同上 |
| `open_issues_count` | `open_issues_count` | 同上 |
| `topics` | `topics` | 只保留字符串，去空、去重、保持 GitHub 顺序；缺失 → `[]` |
| `license.spdx_id` | `license_spdx` | `NOASSERTION` / 空 → `None` |
| `license.name` | `license_name` | 空 → `None` |
| `archived` | `archived` | `bool(...)` |
| `disabled` | `disabled` | `bool(...)` |
| `pushed_at` | `pushed_at` | 复用 `_parse_dt`，无时区按 UTC |
| `homepage` | `homepage` | `strip()` 后空串 → `None` |
| `visibility` | `visibility` | 空 → `None`；展示时回退 `private` |

`repository_crud.upsert_from_github` 增加同名可选关键字参数，默认值保证现有测试和旧调用不破坏：

```python
def upsert_from_github(
    db: Session,
    *,
    company_id: int,
    github_repo_id: int,
    name: str,
    github_full_name: str,
    description: str | None,
    html_url: str | None,
    default_branch: str,
    private: bool,
    language: str | None = None,
    stargazers_count: int | None = None,
    forks_count: int | None = None,
    open_issues_count: int | None = None,
    topics: list[str] | None = None,
    license_spdx: str | None = None,
    license_name: str | None = None,
    archived: bool = False,
    disabled: bool = False,
    pushed_at: datetime | None = None,
    homepage: str | None = None,
    visibility: str | None = None,
) -> Repository:
    ...
```

写入规则：

- 新建行与已有行都按本次 API 返回值**整对象覆盖**这些字段，不做字段级 merge。
- `topics` 在同步成功时至少写 `[]`，用于区分「从未同步（NULL）」与「已同步无主题」。
- `local_path`、`doc_dir` 不参与覆盖；`synced_at` 成功时更新为当前时间，`sync_error` 清空。
- 同步 API 失败时不写仓库资料，只由现有 `set_sync_error` 更新 `sync_error`；`local_path` 与旧字段保持原值。
- Webhook 同步与仓库页「重新同步」共用 `sync_owner_and_repo`，因此两条路径都会写入新字段；「重新同步」成功后仍按现有行为 303 回公司仓库列表，不改为停留本页。

### 6.4 C 类：本系统运行态摘要

#### 6.4.1 统计口径

三个数字都只统计本系统已收录、`deleted_at IS NULL`、且 `github_state = 'open'` 的 Issue：

| 指标 | 谓词 | 点击跳转 |
| --- | --- | --- |
| 未结束功能迭代 | `kind = 'feature'` 且 `status != 'pr_opened'` | `/repos/{id}/issues?kind=feature&status=unfinished&github_state=open` |
| 人工介入待处理 | `kind = 'support'` 且 `status = 'support_open'` | `/repos/{id}/issues?kind=support&status=support_open&github_state=open` |
| 失败 | `status = 'failed'` | `/repos/{id}/issues?status=failed&github_state=open` |

说明：

- 「未结束」与基石公司列表的定义一致：功能迭代里 `status != 'pr_opened'` 的都算未结束，常见为 `recorded`、`drafting`、`pending_codegen`、`generating`、`generated`、`failed`。
- 三个数字**不是互斥分组**：失败的 Issue 同时计入「未结束功能迭代」；人工介入待处理不计入功能迭代。卡片需用一行小字说明「三类可重叠」。
- 已关闭（`github_state = 'closed'`）或已软删的失败 Issue 不计入失败数；本摘要只反映 open 的待处理面。
- 统计只读本系统 `issue` 表，不调用 GitHub，也不使用 `repository.open_issues_count`。

实现建议：在 `app/crud/issue.py` 增加 `repo_open_summary(db, repository_id)`，用一次条件聚合查询返回三个计数；列表筛选、计数和摘要必须复用同一组谓词，避免数字与跳转结果不一致。

#### 6.4.2 `status=unfinished` 展示层筛选

现有 Issue 列表只支持单个精确 `status` 值，无法表达「不是已建 PR」。为了让摘要数字和跳转列表同口径，新增一个**展示层筛选值**：

- `status=unfinished` 不是 `issue.status` 的数据库取值，不写入数据库，不参与状态机。
- 谓词为 `Issue.status != 'pr_opened'`；可与 `kind`、`github_state` 组合。
- 摘要链接带上 `kind=feature`，因此「未结束功能迭代」= `kind=feature AND status != 'pr_opened'`。
- Issue 列表的流程状态下拉增加一项「未结束（未建 PR）」，值为 `unfinished`；`STATUS_LABELS` 仍只用于 Issue 状态徽章，不把 `unfinished` 当成真实状态。
- 分页 URL 继续保留 `status=unfinished`，与现有 `_issue_list_url` 行为一致。
- 现有精确状态筛选、空状态文案、`has_filters` 判断不变；选择 `unfinished` 时按「有筛选」处理。

若确认不接受新增展示值，可按第 10 节待确认项退化为「数字仍精确、链接只带 `kind=feature&github_state=open`」，但列表会包含已建 PR，数字与列表不完全同口径。

#### 6.4.3 `local_path` 与 origin 状态

新增只读检查函数（建议放在 `app/services/git_repo.py`），返回不抛异常的状态对象：

```python
@dataclass(frozen=True)
class OriginInfo:
    state: str          # none | match | mismatch | unavailable
    origin: str | None  # 实际 origin URL，读不到时为空
    detail: str         # 给页面显示的短原因，不拼 HTML
```

判定顺序：

| 状态 | 条件 | 页面展示 | 页顶警告 |
| --- | --- | --- | --- |
| `none` | `local_path` 为空 | 徽章「未填写」 | 无 |
| `match` | 路径存在、是 git 顶层目录，`origin` 可解析且等于 `github_full_name` | success 徽章「匹配」 | 无 |
| `mismatch` | 路径可用，但 `origin` 可解析且不等于 `github_full_name`，或 URL 无法解析 | danger 徽章「不一致」，展示实际 origin | 沿用现有 `alert-warning` |
| `unavailable` | 路径不存在 / 不是目录 / 不是 git 顶层 / 读不到 origin / git 执行失败 | warning 徽章「无法校验」，展示短原因 | 不新增页顶警告 |

约束：

- 只执行 `git rev-parse --show-toplevel` 和 `git remote get-url origin`，均为本地只读，不 fetch、不写仓库。
- 复用 `parse_origin_full_name`，支持 `git@github.com:owner/repo.git` 与 `https://github.com/owner/repo.git`，与保存表单的 origin 校验语义一致。
- `inspect_origin` 捕获 `GitError` / `OSError`，绝不让路径异常把页面打成 500。
- 保存表单校验仍走 `validate_local_path`，本函数不替代、不修改其规则。

#### 6.4.4 基石入口状态

`local_path` 非空且路径可用于 git 读取时检查；origin 为 `match` 或 `mismatch` 都检查，路径为空或 origin 为 `unavailable` 时不检查。复用现有 `read_foundation_from_origin`，保证与 Issue 详情同一套规则：

- 路径：`foundation_relpath(repo.doc_dir)`，即 `{doc_dir}/README.md`。
- ref：`origin/{repo.default_branch}`。
- 不执行 fetch；只读本地已有 ref。
- `OSError` 降级为「无法检查」，不让页面报错。
- origin 不一致时仍按该路径的 `origin/{default_branch}` 读取，并在展示处标注「当前路径 origin 与仓库不一致，结果仅供参考」，与 Issue 详情「有路径就检查」的规则一致。

| 状态 | 条件 | 页面展示 |
| --- | --- | --- |
| `no_path` | `local_path` 为空 | 中性「未填写路径，无法检查」 |
| `not_checked` | 路径已填但 origin 为 `unavailable` | 中性「无法检查（路径不可用）」 |
| `exists` | `git show origin/{branch}:{doc_dir}/README.md` 成功 | success「存在」，显示路径与 ref；origin 不一致时附「结果仅供参考」 |
| `missing` | 命令返回非零 | warning「未找到」，附注「GET 不 fetch；可能尚未 fetch 或基石确实缺失」；origin 不一致时附「结果仅供参考」 |
| `unavailable` | `OSError` / 路径不可读 | warning「无法检查（路径不可用）」 |

基石缺失只在卡片内提示，**不阻断**编写文档 / 生成代码；与基石「警告但不阻断入队」一致。Issue 详情现有的 `foundation_missing` 行为不变。

#### 6.4.5 同步结果文案

不新增同步历史表。卡片内「同步」一行按现有字段组合：

- 从未同步：`synced_at` 为空且 `sync_error` 为空 → 「尚未同步」。
- 最近成功：`synced_at` 有值、`sync_error` 为空 → 「成功于 `YYYY-MM-DD HH:MM UTC`」。
- 最近失败：`sync_error` 有值 → 「最近失败：{单行摘要}」；若 `synced_at` 也有值，补「上次成功：{时间}」。
- 完整错误仍在页顶 `alert-error` 展示，卡片只放一行摘要，`title` 可放全文，不重复长文。

`sync_error` 成功后被清空是现有语义，本迭代不保留历史；因此「最近一次失败」只在当前行仍带错误时可见。

#### 6.4.6 GET 行为与性能

- `repo_page` **不实例化** `GitHubClient`，不发起任何 GitHub 请求。
- 只增加：1 次 Issue 条件聚合查询；`local_path` 非空时最多 2 次本地 git 只读调用（origin 检查、基石检查）。
- `company` 已由现有查询加载，不新增 N+1。
- `repo_save` 校验失败重渲染时，摘要仍按**已保存的** `repo.local_path` / `repo.doc_dir` 计算；表单显示用户刚提交的值，避免把未保存路径当成事实。
- GET 与保存失败重渲染抽同一个 `_repo_page_context(db, user, repo, **overrides)` 构造器，保证新增上下文不会在错误路径漏传。

### 6.5 页面呈现细节

#### 6.5.1 页头徽章区

仍放在 `page_header` 下方，一行 `flex flex-wrap`：

| 徽章 | 文案 | 来源 |
| --- | --- | --- |
| 可见性 | 公开 / 私有 / 内部 | `visibility`，空时回退 `private` |
| 默认分支 | `main` 等，等宽 | `default_branch` |
| 最近同步 | 「同步于 …」/「同步失败」/「尚未同步」 | `synced_at` / `sync_error` |
| 归档 | 「已归档」warning / danger | `archived` |
| 禁用 | 「已禁用」danger | `disabled` |

卡片内不再重复可见性、默认分支、同步时间；完整名称仍保留在身份区，便于复制。

#### 6.5.2 归档 / 禁用警告

在资料卡标题下方、描述之前放 `alert-warning`：

- 仅归档：「该仓库已在 GitHub 归档（只读）。同步可能失败，写文档 / 生成代码前请确认仓库状态。」
- 仅禁用：「该仓库已在 GitHub 禁用。同步与后续流程可能失败。」
- 两者都有：「该仓库已在 GitHub 归档并禁用。」
- 末尾固定一句弱化说明：「本页不改变任务按钮条件，实际结果以任务日志为准。」

警告只做提示，不禁用「重新同步」「查看 Issue」或任何流程按钮。

#### 6.5.3 身份区

使用 `dl` 两列网格（小屏单列）：

- 所属公司：链接到 `/companies/{company_id}`，`name` 为主，`@login` 为辅。
- 短名：`repo.name`。
- GitHub 仓库 ID：`repo.github_repo_id`，等宽。
- 完整名称：`repo.github_full_name`，等宽、`break-all`。
- 收录于：`repo.created_at`，UTC。

描述放在身份区上方；为空显示「无描述」弱化文字，不占多行空位。

#### 6.5.4 指标区

使用 `grid grid-cols-2 gap-3 sm:grid-cols-3` 的小指标块，每块「标签 + 值」：

| 标签 | 值 | 空值 |
| --- | --- | --- |
| 主语言 | `language` | `—` |
| 星标 | `stargazers_count`，千分位 | `—` |
| Fork | `forks_count`，千分位 | `—` |
| GitHub 开放 Issue | `open_issues_count`，可链到 `{html_url}/issues` | `—` |
| 最近推送 | `pushed_at`，`YYYY-MM-DD HH:MM UTC` | `—` |
| 许可证 | `license_spdx or license_name`；两者都有时 `title` 放全名 | `—` |

在指标区下方加一行小字：「GitHub 的开放 Issue 计数包含 Pull Request；本系统只收录部分 Issue，两个数字不可直接相减。」

#### 6.5.5 主题与链接

- 主题：`topics` 渲染为徽章列表，最多展示 12 个；超出显示 `+N`，`title` 列出其余主题。为空显示 `—`，不渲染空列表。
- 链接区：
  - GitHub 仓库：`html_url`，外链 `target="_blank" rel="noopener"`。
  - 项目主页：`homepage`，仅当以 `http://` 或 `https://` 开头时渲染为外链；其他值以纯文本展示，不生成可点击的 `javascript:` / `data:` 链接。
  - GitHub Issues：`{html_url}/issues`，方便核对 GitHub 侧 Issue。
  - 每个外链带 `aria-label` 或可见文字，图标 `aria-hidden="true"`。

#### 6.5.6 本系统小节

位于资料卡底部，`border-t` 分隔：

```text
本系统
[未结束功能迭代 N] [人工介入待处理 N] [失败 N]
说明：仅统计 open、未删除的本系统 Issue；三类可重叠。

服务器路径   已填写 / 未填写 + 路径
origin       匹配 / 不一致 / 无法校验 / 未填写
基石         {doc_dir}/README.md @ origin/{default_branch}
同步         成功于 … / 最近失败：…
```

- 三个数字用 `a` 块展示，数字 `tabular-nums`、右对齐或大号；标签下方一行说明可点击筛选。
- 链接严格使用 6.4.1 的 URL；分页参数保持现有语义。
- 失败数大于 0 时仅用 danger 文字色辅助，标签和数字本身已表达含义，不只靠颜色。
- 路径行显示完整 `local_path`，等宽、`break-all`；过长时可 `line-clamp-2`，`title` 放全文。
- origin 不一致时同时显示实际 origin 与期望的 `github_full_name`，并保留页顶警告；基石检查仍执行，但标注「结果仅供参考」。
- 基石行显示 `{doc_dir}/README.md` 与 `origin/{default_branch}`，缺失时 warning；附注「GET 不 fetch」。
- 同步行按 6.4.5；页顶 `sync_error` 仍是主要错误展示。

#### 6.5.7 空值、格式与无障碍

- 空值统一 `<span class="text-slate-400">—</span>`，不渲染 `None` / `null` / 空 `<dd>`；描述为空例外，用「无描述」。
- `0` 是有效计数，显示 `0`，不要误判为空。
- 数字千分位，时间统一 UTC 到分钟，`title` 保留 ISO。
- 身份区与指标区使用 `dl` / `dt` / `dd`，屏幕阅读器能读出标签与值。
- 外链必须有可辨识文字或 `aria-label`；归档警告用 `role="status"`，不用阻塞式弹窗。
- 主题徽章、状态徽章不只靠颜色；图标全部 `aria-hidden`。
- 小屏指标区两列，身份区单列，链接区换行；不产生横向滚动。

### 6.6 安全与降级

- 所有 GitHub 文本继续由 Jinja 自动转义；`description`、`topics`、`language`、`license_name`、`sync_error`、`homepage` 禁止 `|safe`。
- `homepage` 只允许 `http://` / `https://` 外链；其他协议按纯文本展示，避免 `javascript:` / `data:` 注入。
- 外链统一 `target="_blank" rel="noopener"`。
- 本地 git 检查只读；任何失败降级成「无法校验 / 无法检查」，不把异常、stderr 或完整命令拼进 HTML。
- 页面 GET 不调用 GitHub API；新字段只在同步时写入，避免打开页面触发限流或慢请求。
- 长路径、长主题、长许可证名必须截断或换行，不撑破 `lg` 三列布局。

## 7. 影响面

### 7.1 代码与模板

| 文件 | 变更 |
| --- | --- |
| `app/models/repository.py` | 增加 6.3.1 的 12 个映射列；`topics` 使用 PostgreSQL `ARRAY` |
| `app/alembic/versions/20261111_0002_repository_github_meta.py` | 新增迁移：加列 / 删列，无回填 |
| `app/crud/repository.py` | `upsert_from_github` 增加可选参数并整对象覆盖新字段 |
| `app/services/ingest.py` | 从 `repo_data` 提取并归一化新字段，传给 upsert |
| `app/services/github_api.py` | `Accept` 增加 topics 媒体类型；不新增请求方法 |
| `app/services/git_repo.py` | 新增 `OriginInfo` 与 `inspect_origin` 只读、非抛异常检查 |
| `app/crud/issue.py` | 新增 `repo_open_summary`；`list_for_repo` / `count_for_repo` 支持 `status=unfinished` |
| `app/api/v1/repos.py` | `repo_page` 组装 origin / 基石 / 摘要 / 链接上下文；GET 与保存失败共用构造器 |
| `app/api/v1/issues.py` | 流程状态选项增加 `unfinished`；筛选与分页保留该值 |
| `app/templates/repo.html` | 重构 GitHub 资料卡：页头徽章、归档警告、身份区、指标区、主题、链接、本系统小节 |
| `app/templates/issues.html` | 如需要，仅为 `unfinished` 提供下拉项；表格结构不变 |
| `app/templates/macros/icons.html` | 按需补充 `star`、`fork`、`tag`、`scale`、`calendar`、`archive`、`link` 等内联 SVG；仍走 `icon()` 宏 |

### 7.2 数据与部署

- 迁移为纯加列，无数据回填、无停机；旧行新字段为 `NULL` 或 `false`，页面显示「—」/未归档。
- 部署后需一次 Webhook 同步或手动「重新同步」才能看到完整指标；这是预期行为，不做启动时批量回填。
- 同步失败只写 `sync_error`，不修改 `local_path`、`doc_dir` 或上次成功写入的元数据。
- 新列不建索引；仓库页按主键读取，Issue 摘要按 `repository_id` 现有索引统计。

### 7.3 明确不改

- `app/api/v1/webhook.py`、`app/tasks/**`、Worker / Pipeline、`app/services/agent.py`、`app/services/prompts.py`。
- `app/services/actions.py` 的 `actions_for` 条件；归档 / 禁用只提示，不禁用按钮。
- `app/services/git_repo.py` 中 `validate_local_path` / `validate_doc_dir` 的校验规则与保存流程。
- `app/core/security.py`、`app/dependencies/auth.py`、CSRF / JWT 行为。
- `docs/README.md`、`docs/architecture/design.md`（本任务不修改；基石同步见第 10 节）。
- 所有现有路由、HTTP 方法、筛选参数语义（除新增展示值 `status=unfinished`）。

### 7.4 测试

| 测试 | 覆盖 |
| --- | --- |
| `tests/test_sync.py` | Fake GitHub 返回新字段后落库；`topics` / `license` / `archived` 归一化；重新同步更新新字段；失败只写 `sync_error` 且不清 `local_path` |
| `tests/test_repos.py` | 资料卡渲染新字段；空值「—」；归档 / 禁用警告；origin 匹配 / 不一致 / 不可用；基石存在 / 缺失 / 未填路径；GET 不实例化 GitHub 客户端 |
| `tests/test_issues.py` | `status=unfinished` 的列表与计数一致；现有精确状态筛选不回退；分页保留参数 |
| `tests/test_ui.py` | 仓库页资料卡关键区块与文案冒烟；计数链接 URL 正确 |
| Alembic 手工检查 | 在一次性数据库执行 `upgrade head` / `downgrade`，确认列与默认值正确 |

测试注意：

- 现有 `tests/conftest.py` 用 `Base.metadata.create_all` 建表，模型加列会自动生效；迁移本身需单独验证。
- 现有 `tests/test_repos.py` / `tests/test_ui.py` 中创建仓库的调用不传新参数，必须因可选默认值继续通过。
- origin / 基石测试可复用 `tests/conftest_git.py` 的 `init_bare_and_clone`，在本地 clone 中提交 `docs/README.md` 并保留 `origin/main` ref。
- 「GET 不 fetch」通过代码审查与断言页面不调用 `GitHubClient` 覆盖；git 调用只允许 `remote get-url` / `show`。

### 7.5 文档

- 本迭代设计只写 `docs/v0002-4/design.md`。
- 因新增 `repository` 列，按基石约定应更新 `docs/architecture/design.md` 的 repository 表、同步步骤和仓库页面说明；本次任务未改，列入第 10 节。
- 基石入口 `docs/README.md` 的索引不需要新增条目，迭代文档已按约定路径存放。

## 8. 实施顺序

1. Alembic 迁移与 `Repository` 模型列；确认 `upgrade` / `downgrade`。
2. `repository_crud.upsert_from_github` 新参数与默认值；现有测试先跑通。
3. `GitHubClient` Accept、`sync_owner_and_repo` 字段提取与归一化；补同步测试。
4. `inspect_origin` 只读检查；补 origin 状态测试。
5. `repo_open_summary` 与 `status=unfinished` 筛选；补列表 / 计数一致性测试。
6. `repos.py` 统一上下文构造器，接入 origin、基石、摘要、链接。
7. `repo.html` 重构；补 icons；按 375 / 768 / 1280 检查两栏与空值。
8. 补 `test_repos` / `test_ui` / `test_issues`，跑全量测试与 Alembic 手工检查。
9. 按基石约定补 `docs/architecture/design.md`（由实现 PR 或后续人工完成）。
10. 实现走 `dev_{number}` 分支并开 PR；CI 绿后合并。

## 9. 验收

### 9.1 页面与信息密度

- [ ] `/repos/{id}` 资料卡展示所属公司（链到 `/companies/{id}`）、短名、`github_repo_id`、完整名称、本系统收录时间。
- [ ] 页头徽章区统一展示可见性、默认分支、最近同步时间；卡片内不重复这三项。
- [ ] 资料卡展示主语言、Star、Fork、GitHub 开放 Issue、最近推送、许可证、主题、项目主页、GitHub Issues 链接。
- [ ] 空值显示「—」，描述为空显示「无描述」；不出现成排空行、`None` 或 `null`。
- [ ] 桌面 `lg` 仍是 GitHub 资料 + 本地配置两栏，版面舒适；375px 下无横向溢出，路径表单仍在前。
- [ ] 归档 / 禁用仓库在卡片顶部有 `alert-warning`，页头有对应徽章；不改变按钮启用条件。

### 9.2 同步与数据

- [ ] Alembic `upgrade head` 后 `repository` 新列存在，`archived` / `disabled` 默认 `false`，计数列为可空；`downgrade` 可回退。
- [ ] Webhook 同步与「重新同步」都会写入新字段；`topics`、`license`、`pushed_at`、`visibility` 归一化正确。
- [ ] 重新同步后页面指标更新；`0` 显示为 `0`，未同步显示「—」。
- [ ] 同步失败只更新 `sync_error`，不清 `local_path` / `doc_dir`，旧元数据不被清空。
- [ ] 页面 GET 不调用 GitHub API；新字段不会因打开页面而刷新。

### 9.3 本系统摘要

- [ ] 「未结束功能迭代」数字等于 `kind=feature AND status != 'pr_opened' AND github_state=open` 的本系统 Issue 数。
- [ ] 「人工介入待处理」数字等于 `kind=support AND status='support_open' AND github_state=open`。
- [ ] 「失败」数字等于 `status='failed' AND github_state=open`。
- [ ] 三个数字点击后进入对应筛选列表，列表 `total` 与卡片数字一致；分页保留筛选参数。
- [ ] `status=unfinished` 不写入数据库、不改变 Issue 状态徽章；现有精确状态筛选语义不变。
- [ ] 卡片说明「三类可重叠」「仅统计 open、未删除的本系统 Issue」，避免误读。

### 9.4 路径、origin 与基石

- [ ] `local_path` 为空时摘要显示「未填写」，「未结束 / 人工介入 / 失败」统计仍可用。
- [ ] `local_path` 已填且 origin 匹配时显示 success「匹配」；不一致时显示实际 origin，并保留页顶 `alert-warning`。
- [ ] 路径不存在 / 不是 git 顶层 / 读不到 origin 时显示「无法校验」，页面不 500。
- [ ] 基石存在时显示 success「存在」+ `{doc_dir}/README.md` + `origin/{default_branch}`。
- [ ] 基石缺失时显示 warning「未找到」并附「GET 不 fetch」说明；不阻断编写文档 / 生成代码。
- [ ] 路径不可用（不存在 / 不是 git 顶层）时，基石显示「无法检查」；origin 不一致不阻止检查，但标注「结果仅供参考」，不把不一致路径的结论当成仓库事实。
- [ ] 与 Issue 详情使用同一套 `read_foundation_from_origin` 规则，GET 不执行 fetch。

### 9.5 安全、兼容与约束

- [ ] 所有动态内容由 Jinja 自动转义，无 `|safe`；`homepage` 非 http(s) 不生成可点击外链。
- [ ] 外链均带 `rel="noopener"`；图标按钮有 `aria-label`；状态不只靠颜色。
- [ ] 保存表单校验、进行中任务禁用、origin 校验失败文案与 303 行为不变。
- [ ] 现有测试全部通过；新增测试覆盖同步、归档、origin / 基石、摘要与筛选。
- [ ] 设计文档路径为 `docs/v0002-4/design.md`，未删除或替换基石入口。
- [ ] 实现走 `dev_{number}` 分支并开 PR；CI 绿。
- [ ] 基石更新已安排：`docs/architecture/design.md` 的 repository / 同步 / 仓库页面说明与本文档一致。

## 10. 待确认

以下规则 Issue 未写清，先按「默认处理」实施；确认后再调整，均不改变状态机。

| # | 问题 | 默认处理 | 需要确认的点 |
| --- | --- | --- | --- |
| 1 | 是否允许为「未结束」新增 `status=unfinished` 展示筛选值 | 新增；仅作列表筛选，不写入 `issue.status`，不参与状态机 | 若不允许改 Issue 列表筛选，则链接退化为 `kind=feature&github_state=open`，数字仍精确但列表含已建 PR |
| 2 | 失败数是否只统计 open | 只统计 `github_state=open`、未软删；closed 的失败不计入 | 若希望统计全部失败历史，需要另加口径与链接，现有列表筛选无法表达 |
| 3 | archived / disabled 是否应禁用流程按钮 | 只做 warning 提示，不改变 `actions_for` 条件 | 若要求归档仓库禁止写文档 / 生成代码，应先改基石与按钮条件，另开 Issue |
| 4 | GitHub `open_issues_count` 的文案 | 标签「GitHub 开放 Issue」，并注明包含 PR、与本地口径不同 | 若只想要 issue 数，需要额外 API 或本地自行统计，偏离「只用仓库对象」 |
| 5 | 仓库页 GET 是否允许执行本地只读 git 检查 | 允许；只执行 `rev-parse` / `remote get-url` / `show`，不 fetch，失败降级 | 是否接受路径在慢速文件系统上的页面延迟；是否需要给 git 调用加超时 |
| 6 | 许可证是否同时保留 SPDX 与展示名 | 新增 `license_spdx` + `license_name` 两列 | 若只保留一列，需确认展示优先用 SPDX 还是名称；`NOASSERTION` 仍需归一 |
| 7 | 是否接受 `topics` 预览媒体类型 | 在现有 Accept 上追加 `application/vnd.github.mercy-preview+json`，不新增请求 | 若企业代理 / 网关不接受该媒体类型，需确认 topics 为空时的降级文案 |
| 8 | `homepage` 非 http(s) 时如何展示 | 纯文本展示，不生成可点击链接 | 若希望隐藏，统一显示「—」；不得渲染 `javascript:` / `data:` |
| 9 | 基石正文更新由谁完成 | 实现 PR 中同步更新 `docs/architecture/design.md` 的 repository / 同步 / 仓库页面说明 | 本次任务只写迭代文档；需要确认是否由实现流水线自动补，还是人工另行提交 |

## 11. 参考

- 基石入口：[`docs/README.md`](../README.md)
- 完整产品设计：[`docs/architecture/design.md`](../architecture/design.md)，重点阅读「repository 模型」「同步公司与仓库」「仓库页面 `/repos/{id}`」
- 本迭代 Issue：GitHub Issue `#4`「仓库页 GitHub 资料卡片增强：同步更多元数据与本仓运行态摘要」
- 现有实现：
  - `app/templates/repo.html`
  - `app/models/repository.py`
  - `app/crud/repository.py`
  - `app/services/ingest.py`
  - `app/services/github_api.py`
  - `app/services/git_repo.py`
  - `app/services/foundation.py`
  - `app/api/v1/repos.py`
  - `app/api/v1/issues.py`
  - `app/crud/issue.py`
- 测试：`tests/test_sync.py`、`tests/test_repos.py`、`tests/test_issues.py`、`tests/test_ui.py`、`tests/conftest_git.py`
- Skills：`documentation`（编写本文档）、`ui-ux-pro-max`（实现 UI 时加载）
