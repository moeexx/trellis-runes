# Central Gate 门禁体系

本文档说明 Trellis workspace 的确定性门禁（gate）如何工作、如何新增、如何安全修改。实现位于 `.trellis/scripts/common/gate.py`，policy 位于 `.trellis/gates.yaml`。

## 概述

门禁（gate）是 task 生命周期操作（`task.py start` / `validate` / `archive`）在执行状态变更**之前**必须通过的确定性检查。所有门禁由 `gate.py` 按 `gates.yaml` 中的声明统一执行，命令、hook、skill 不再各自携带一套门禁拷贝。

- **policy = 配置**：`gates.yaml` 声明有哪些 gate、各 gate 要求的规则与状态转换。
- **engine = 代码**：`gate.py` 实现规则与求值引擎。
- **接线 = 命令**：生命周期命令在改动任何状态前调用 `gate.require(...)`。
- **trust boundary**：policy 是仓库内配置，其信任边界与仓库写权限相同；本地没有关闭或绕过 gate 的命令接口（刻意移除 `--skip-branch-validation` / `--allow-empty-context` 等绕过开关）。

## 现有 gate

| gate | 触发命令 | transition | require 规则 |
|---|---|---|---|
| `task_create` | `task.py create` | 无 | `session_activated_for_create` |
| `task_start` | `task.py start` | `planning → in_progress`（`idempotent: true`） | `task_json_ready`、`planning_artifacts_ready`、`context_ready`、`session_activated_for_start` |
| `context_validate` | `task.py validate` | 无 | `context_ready` |
| `task_archive` | `task.py archive` | `in_progress → completed` | `task_json_ready`、`archive_branch_metadata`、`archive_destination_available` |

当前已实现的规则：`task_json_ready`、`planning_artifacts_ready`、`context_ready`（校验 `implement.jsonl` / `check.jsonl` 的合法性、路径存在性与非空策展）、`archive_branch_metadata`、`archive_destination_available`、`session_activated_for_create`、`session_activated_for_start`。后两者在可解析稳定会话身份时读取同会话的 workflow activation marker：`开始任务` 可 create/start，`恢复任务` 仅可 start；无会话身份的直接 CLI 调用保持既有降级放行行为。

## 架构与数据流

```
gates.yaml ──parse──> policy dict
                          │
task.py start ──gate.require("task_start", GateContext(repo_root, task_dir))──┐
validate      ──gate.require("context_validate", ...)──────────────────────────┤
archive       ──gate.require("task_archive", ...)──────────────────────────────┘
                              │
                              v
                      evaluate(gate_id, ctx)
                     ├─ 校验 transition（from/to/idempotent）
                     ├─ 依次执行 require 中的每条规则
                     └─ 汇成 GateResult(failures)
      失败 -> require 打印 "GATE FAILED: <gate>" + 每项失败到 stderr，返回非零
      通过 -> 命令行继续执行状态变更
```

`gate.require()` 只读：不修改 task.json、session 指针或 task 目录。**所有状态变更必须在 gate 通过之后进行**，且 gate 与变更之间不留其他副作用。

`GateContext` 字段：`repo_root`、`task_dir`、`task_data`（可选，避免二次读取）、`policy_path`（测试用覆盖）、`metadata`。`policy_path` 缺省为 `<repo_root>/.trellis/gates.yaml`。

## 添加新 gate

1. **在 `gates.yaml` 声明 gate**。每个 gate 是一个 mapping：
   ```yaml
   gates:
     my_gate:
       transition:            # 可选；有状态转换时写
         from: planning
         to: in_progress
         idempotent: true     # 可选；已达 target 状态视为通过
       require:               # 必填，非空字符串列表
         - existing_rule      # 复用已有规则
         - new_rule           # 或新增规则
   ```
2. **需要新规则时，在 `gate.py` 实现并注册**。规则是纯函数：`fn(ctx: GateContext) -> RuleResult`（见"规则契约"）。写好后加入 `RULES` dict。只复用不新增则跳过此步。
3. **接入命令**。在相应命令里，于任何状态写入之前调用：
   ```python
   if not gate.require("my_gate", GateContext(repo_root=repo_root, task_dir=task_dir)):
       return 1   # 失败信息已由 require 打到 stderr
   ```
   保持 gate 与受保护的状态转换相邻，不要夹带其他副作用。
4. **补测试**：
   - `tests/test_gate.py`：新 gate 的 pass 路径 + 每条新规则的 fail 路径 + fail-closed 路径；
   - `tests/test_task_lifecycle.py`（若接了命令）：gate 失败时状态保持原状、修复后可重试。

## 修改 gate 的约定

- **保持 fail-closed**：未知 gate、未知规则、policy 解析失败、规则抛异常，都必须判失败，不得静默放行。新增 policy 分支时保持该语义。
- **policy schema**：每个 gate 必须有非空 `require` 列表；`transition.to` 必填，`from` 非空（如存在），`idempotent` 只能是 `true` / `false` 且必须位于 transition 内。当前 parser 不支持的 YAML 语法也必须直接拒绝。
- **规则必须纯函数**：不落盘、不改状态；`task_data` 缓存是唯一允许的可变副作用。求值中途抛异常由引擎兜底为 `rule_error` 失败。
- **不得新增绕过开关**：不要为 gate 加 `--skip-*` / `--allow-*` 之类 CLI flag。需要放行时，通过 `idempotent` 或调整规则语义在 policy 层解决，并同步 `docs/gates.md` 与 `workflow.md` 的说明。
- **transition 一致**：改 `from` / `to` 前确认它仍准确描述命令实际执行的状态翻转；`idempotent: true` 仅用于"重跑已到 target 状态不报错"的语义（如 `task_start`）。`task_archive` 保持非幂等。
- **archive 可重试**：状态写入后 mover 失败时，必须恢复原始 `in_progress` 状态；session pointer 只能在目录移动成功后清理，避免重试被 transition gate 拒绝。
- **一次性同步**：门禁行为或措辞变化时，同批更新四个平台的 skill/command/hook 文案（`.claude/`、`.codex/`、`.kiro/`、`.qoder/`、`.agents/`），避免平台间分叉。
- **按影响面补测试**：改规则实现或 policy 结构时，相应更新 `tests/test_gate.py`。policy `version` 目前固定为 `1`；仅当 policy 结构出现不兼容变更时才提升，并要求引擎同时支持旧版本（迁移策略由实现者定义）。

## 规则契约

一条规则返回三者之一：

- `None` —— 通过；
- `GateFailure(rule, code, message, details)` —— 单个失败；
- `tuple[GateFailure, ...]` —— 多个失败（如 `context_ready` 对 `implement.jsonl` 与 `check.jsonl` 各报一个）。

引擎对"未知规则 / 规则异常"分别产出 `unknown_rule` / `rule_error`，保证任何实现缺陷都不会变成静默放行。命令侧只用 `gate.require(...)` 的布尔结果与 stderr 输出，不自行解释策略。

## 已知取舍

- **坏 `task.json` 无绕过**：`task_json_ready` 是 `task_start` / `task_archive` 的必过项。task.json 缺失或损坏时，fail-closed 拒绝，报错含 `describe_json_read_failure` 的 `repair` 提示（如用 `python3 -m json.tool`）——需手工恢复为有效 JSON object 后重试；archive 没有重建或绕过该检查的命令。
- **context 问题一次全报**：`context_ready` 聚合两个 manifest 的全部问题，一次 `start` / `validate` 全部列出，避免"修一个、再发现一个"的循环。
- **`.trellis/gates.yaml` 是唯一 policy 源**：hook/skill/命令执行的是 engine 之外的行为指令，不重复实现门禁。
