# Worker 内置 OpenCode Skills

权威目录在本应用仓，**不**写入目标业务仓 worktree。

| Skill ID | 用途 |
| --- | --- |
| `documentation` | 编写/维护技术文档（写设计文档时加载） |
| `ui-ux-pro-max` | UI/UX 设计与实现指导（涉及界面时加载） |

## 生产挂载（OpenCode 发现）

Worker 用户（如 `linuxuser`）执行一次，或每次升级后：

```bash
./scripts/sync_opencode_skills.sh
```

默认把本目录软链到 `~/.config/opencode/skills`。也可在 `~/.config/opencode/opencode.json` 使用绝对路径，见 `deploy/opencode/opencode.json.example`。
