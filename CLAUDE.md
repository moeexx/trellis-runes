# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 注意

- `.trellis/workflow.md` 是精简汉化版工作流文档（聚焦开发任务实操），由 hooks 自动注入（已生效）。
- `docs/workflow-backup.md` 是完整英文原文备份，含精简掉的内容（fork 定制、解析器/契约 meta、平台专属块、Codex 内联变体、workspace 会话日志）；需要这些细节时再查看，**默认不阅读**。

## 工作区概览

本仓库是 **Trellis（0.6.16）管理工作区**，分两部分：

- **顶层（本仓库）**：Trellis 运行时脚手架，是实际的工作对象。包含 `.trellis/`（workflow、spec、task、workspace 会话日志、scripts）和各 AI 平台的自举配置（`.agents/`、`.claude/`、`.codex/`、`.kiro/`、`.qoder/`）。附加 helper 位于 `.agents/skills/`（可复用 Trellis skills）与 `.codex/agents/`（自定义 subagents）。
- **`Trellis/`**：Trellis 源码快照（独立 git repo），**仅作参考来源**——可读，用于理解工作区脚手架的来源与生成逻辑；**不要在其中修改或开发**。

顶层 git 仓库只是脚手架快照（无提交、仅托管各平台 skill 文件）。若需定制，按 `.trellis/workflow.md` 或 `trellis-meta` skill（`.claude/skills/trellis-meta`）的指引在**顶层**修改。注意：`trellis update` 会重新生成 `AGENTS.md`（内容来自 `Trellis/packages/cli/src/templates/markdown/agents.md` 模板，含 `<!-- TRELLIS:START -->` / `<!-- TRELLIS:END -->` 托管块），因此已合并进本文件的 Trellis 指引在 update 后可能以独立文件形式重新出现。

## Trellis 运行时（`.trellis/`）

Trellis 是 agent 任务/规范管理系统，工作流定义在 `.trellis/workflow.md`，由 hooks 自动注入本会话（已生效）。可用 Trellis 命令时优先使用（如 `/trellis:finish-work`、`/trellis:continue`），未暴露的平台再手动执行。常用脚本：

```bash
python3 ./.trellis/scripts/init_developer.py <name>          # 开发者身份初始化
python3 ./.trellis/scripts/task.py create|start|finish|archive # 任务生命周期
python3 ./.trellis/scripts/get_context.py --mode packages      # 列出 spec 包/层
python3 ./.trellis/scripts/get_context.py --mode phase --step <X.Y>  # 单步工作流详情
```

编码规范位于 `.trellis/spec/<package>/<layer>/index.md`（当前为 generic 的 backend/frontend 引导层，与 `Trellis/` 源码内的产品无关）。

## 参考：Trellis 源码结构（只读）

`Trellis/` 是 pnpm monorepo（`packages/core` + `packages/cli`），其意义在于解释顶层脚手架从哪来：

- `Trellis/packages/cli/src/templates/<platform>/` — 生成各平台脚手架的模板（claude、cursor、codex、copilot、gemini、kiro、qoder、opencode、omp、pi、droid 等）。顶层 `.agents/`、`.claude/`、`.codex/` 等目录即由此生成。
- `Trellis/packages/core/src/` — channel（多 agent 会话）、task、mem 等领域原语；`packages/cli/src/commands/` — `init`/`update`/`channel` 等 CLI 命令。

> 理解生成逻辑后，若需调整行为，请在顶层做定制（`.trellis/`、hooks、skills），不要在 `Trellis/` 内改动。
