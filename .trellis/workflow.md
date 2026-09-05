# 开发工作流

## 核心原则

1. **先计划后编码** —— 动手之前先想清楚要做什么
2. **规范靠注入而非记忆** —— 规范通过 hook/skill 注入，而不是靠记忆回想
3. **一切落盘** —— 研究、决策、经验教训都要写入文件；对话会被压缩，文件不会
4. **增量开发** —— 一次只做一个任务
5. **沉淀收获** —— 每个任务结束后，回顾并把新知识写回 spec

## 激活规则

默认对话不加载本工作流、任务状态或 workflow-state。只有用户消息首字符精确以以下前缀开头时，hook 才为当前 AI 会话启用工作流：

- `创建任务`：读取当前上下文与本文件，按 Phase 1 分类并进入新任务流程；不会自动创建或启动任务。
- `恢复任务`：读取当前上下文与本文件，根据 active task 的状态和产物定位下一步；不会自动改变任务状态。

启用后，本会话后续消息持续接收 workflow-state，直到会话结束。前置空白、非开头匹配或其它措辞不触发；无稳定会话标识时 hook 显示错误且不跨会话保存状态。会话重置（`/clear`）或新建会话会更换会话标识，原激活不延续，需重新以 `创建任务` / `恢复任务` 触发；回到此前已激活的历史会话时，其激活状态仍有效。

## Trellis 系统

### Spec 系统

`.trellis/spec/` 按 package 和 layer 组织编码规范。

- `.trellis/spec/<package>/<layer>/index.md` —— 入口文件，含 **Pre-Development Checklist** 与 **Quality Check**；实际规范在它指向的 `.md` 文件中。
- `.trellis/spec/guides/index.md` —— 跨 package 的思维指南。

**何时更新 spec**：发现新 pattern/约定 · 需固化的 bug 修复预防 · 新技术决策。

### Task 系统

每个任务在 `.trellis/tasks/{MM-DD-name}/` 下有独立目录，存放 `task.json`、`prd.md`，可选 `design.md`、`implement.md`、`research/`，以及子代理上下文 manifest（`implement.jsonl`、`check.jsonl`）。

```bash
# 任务生命周期
python3 ./.trellis/scripts/task.py create "<title>" [--slug <name>] [--parent <dir>]
python3 ./.trellis/scripts/task.py start <name>          # 设为激活任务（可用时按会话隔离）
python3 ./.trellis/scripts/task.py current --source      # 显示激活任务及来源
python3 ./.trellis/scripts/task.py finish                # 清除激活任务（触发 after_finish hooks）
python3 ./.trellis/scripts/task.py archive <name>        # 移到 archive/{year-month}/
python3 ./.trellis/scripts/task.py list [--mine] [--status <s>]

# 子代理上下文 manifest（每行 {"file": "<path>", "reason": "<why>"}，路径相对仓库根）
# implement.jsonl / check.jsonl 由任务创建时按平台预置；现有文件由中央 gate 校验。
python3 ./.trellis/scripts/task.py add-context <name> <action> <file> <reason>
python3 ./.trellis/scripts/task.py list-context <name> [action]
python3 ./.trellis/scripts/task.py validate <name>
python3 ./.trellis/scripts/task.py audit <name> human-gate --kind <prd-confirmed|commit-confirmed|rollback-intervention> --detail "<confirmation>"

# 元数据 / 层级 / PR
python3 ./.trellis/scripts/task.py set-branch <name> <branch>
python3 ./.trellis/scripts/task.py set-base-branch <name> <branch>
python3 ./.trellis/scripts/task.py set-scope <name> <scope>
python3 ./.trellis/scripts/task.py add-subtask <parent> <child>
python3 ./.trellis/scripts/task.py remove-subtask <parent> <child>
python3 ./.trellis/scripts/task.py create-pr [name] [--dry-run]
```

> 权威命令列表：`python3 ./.trellis/scripts/task.py --help`

**当前任务机制**：`create` 创建目录，会话身份可用时自动设为激活任务；`start` 把 `task.json.status` 从 `planning` 翻转为 `in_progress`；`finish` 清除当前会话指针（status 不变）；`archive` 写 `status=completed` 并移到 `archive/`。在可识别会话中，`create` 需要本会话先由消息首字符的「创建任务」激活，`start` 则接受「创建任务」或「恢复任务」激活；无会话身份的直接 CLI 调用保持降级兼容。状态存于 `.trellis/.runtime/sessions/`。

### Workspace 系统

极简档（不建任务）的调研/PRD 片段落盘到 `.trellis/workspace/<developer>/journal-N.md`：

```bash
python3 ./.trellis/scripts/add_session.py --title "<title>" --summary "<summary>" --change "<bullet>" --commit -
# 追加一条 session 记录到 journal，超 2000 行自动轮转；--commit - 表示纯规划/调研session（尚无提交）
```

### Central Gate

确定性的 lifecycle 前置条件由 `.trellis/scripts/common/gate.py` 读取 `.trellis/gates.yaml` 统一执行。正常工作流调用 `task.py create`、`task.py start`、`task.py validate` 和 `task.py archive`；gate 失败时按返回的具体项修复并重试。`task_archive` 对缺失或损坏的 `task.json` 有意 fail-closed：先手工恢复为有效 JSON object，再重试；archive 没有重建或绕过该检查的命令。policy 是仓库内配置，具有与仓库写权限相同的 trust boundary；本地没有关闭或绕过 gate 的命令接口。新增/改动门禁见 `docs/gates.md`。

### Context 脚本

```bash
python3 ./.trellis/scripts/get_context.py                            # 完整会话运行时上下文
python3 ./.trellis/scripts/get_context.py --mode packages            # 可用 packages + spec layers
python3 ./.trellis/scripts/get_context.py --mode phase --step <X.Y>  # 某工作流步骤的详细指南
```

## Phase Index

```
Phase 1: Plan    → 选定档位（完整/普通/极简），然后按档位撰写规划产物
Phase 2: Execute → 完整/普通档仅在任务状态为 in_progress 后实施；极简档选定后直接实施
Phase 3: Finish  → 验证、更新 spec、提交、收尾
```

### 任务分级

尚无 active task 时，创建任何 Trellis task 之前，先向用户提出单选题，展示以下三档摘要，等待用户选择后再继续（支持结构化选择题的平台用自身机制展示；其余平台以枚举形式提问）：

| 档位 | 适用场景 | 涉及步骤 | 是否建任务 |
|---|---|---|---|
| **完整** | 复杂/多交付物/跨包改动/需求有歧义 | 1.0,1.1,(1.2),1.3,1.4,2.1,2.2,(2.3),(3.2),3.3,3.4 | 是；`design.md`/`implement.md` 按需维护 |
| **普通** | 需求明确的中等任务 | 1.0,1.1,1.4,2.1,2.2,3.3,3.4（跳过 1.2/1.3，只维护 `prd.md`） | 是；仅 `prd.md`，不建 `design.md`/`implement.md`/manifest |
| **极简** | 调研或小改动，不想走任务机制 | 产出一段 PRD 片段/调研笔记（落盘到 Workspace 系统），直接进入实现；不跑 1.0/1.3/1.4/3.3/3.4 | 否；全程不调用 `task.py create/start/archive`，Central Gate 不介入 |

- 档位在创建任务前一次性选定，选定后不中途切换；需要更重的流程时，走完当前档，或另开一个更高档的任务。
- 用户同意创建任务 ≠ 同意开始实现。规划仍要先做。
- 完整/普通档在 `task.py create` 时用 `--meta trellis_tier=full`（或 `normal`）记录档位，供 `恢复任务` 时从 `task.json.meta` 读回，无需重新推断。

### 规划产物

- `prd.md` —— 需求、约束与验收标准。不要放技术设计或执行清单。
- `design.md` —— 复杂任务的技术设计：边界、契约、数据流、取舍、兼容性、上线 / 回滚形态。
- `implement.md` —— 复杂任务的执行计划：有序检查清单、验证命令、评审关卡、回滚节点。
- `implement.jsonl` / `check.jsonl` —— 子代理上下文清单（spec + 研究），不替代 `implement.md`。
- 普通档只有 PRD；完整档的 `design.md` / `implement.md` 由规划流程按语义需要维护。

### 父 / 子任务树

多个可独立验证的交付物 → 父任务（拥有源需求、任务映射、跨子任务验收、最终集成评审；通常本身不做实现）。可独立规划/实现/检查/归档的交付物 → 子任务。父/子不是依赖系统：若子任务 B 依赖 A，在 B 的产物中写明顺序。

```bash
python3 ./.trellis/scripts/task.py create "<title>" --slug <name> --parent <parent-dir>  # 创建子任务
python3 ./.trellis/scripts/task.py add-subtask <parent> <child>     # 关联
python3 ./.trellis/scripts/task.py remove-subtask <parent> <child>  # 解除关联
```

[workflow-state:no_task]
当前没有激活任务。创建任何 Trellis task 之前，先让用户从「任务分级」的完整/普通/极简三档中单选一档；若用户选极简，不创建任务，直接进入实现前的 PRD 片段/调研（落盘到 Workspace 系统）。
[/workflow-state:no_task]

[workflow-state:task_error]
无法读取激活任务记录。不要创建或激活另一个任务。
检查上面提到的任务目录并修复其 task.json：必须是有效 JSON 对象且 status 非空；保留现有字段与产物。无法安全确定 status 时先询问用户。
[/workflow-state:task_error]

[workflow-state:planning]
完成规划并请求用户评审。准备进入实现时运行 `python3 ./.trellis/scripts/task.py start <task-dir>`；命令会执行中央 gate。
若 gate 失败，只修复返回的失败项后重试；未通过前保持 planning。
多交付物范围：考虑父任务加若干可独立验证的子任务；依赖写进子任务产物，而非靠树结构位置暗示。
[/workflow-state:planning]

[workflow-state:in_progress]
工具：`trellis-implement` / `trellis-research` 是子代理类型（非 Skill）；`trellis-update-spec` 是 skill；`trellis-check` 两者皆可，代码改动后验证优先用 Agent 形态。
流程：`trellis-implement` -> `trellis-check` -> `trellis-update-spec` -> 提交（Phase 3.4）-> `/trellis:finish-work`。
主会话默认派发 implement/check 子代理；子代理自身不得再派发同类的 implement/check。分派 prompt 以 `Active task: <task.py current 任务路径>` 开头；上下文读取顺序：jsonl 条目 -> `prd.md` -> `design.md`（如存在）-> `implement.md`（如存在）。
[/workflow-state:in_progress]

> Codex 内联变体（planning-inline / in_progress-inline）与已失效的 completed 块已省略，见 `docs/workflow-backup.md`。

### Phase 1：计划（Plan）
- [1.0 创建任务](./workflow/steps/1.0.md) `[required · once]`（完整/普通档；仅在选定档位之后；极简档跳过）
- [1.1 需求探索](./workflow/steps/1.1.md) `[required · repeatable]`（`prd.md`；完整档按需维护 `design.md` + `implement.md`；极简档产出落盘到 Workspace 系统而非任务目录）
- [1.2 研究](./workflow/steps/1.2.md) `[optional · repeatable]`（完整档）
- [1.3 配置上下文](./workflow/steps/1.3.md) `[required · once]`（仅完整档 + 子代理分发平台；普通档跳过，子代理会 fallback 读 `prd.md`；内联平台跳过）
- [1.4 激活任务](./workflow/steps/1.4.md) `[required · once]`（完整/普通档；评审后运行 `task.py start`；central gate 通过后 status → in_progress；极简档跳过）

### Phase 2：执行（Execute）
- [2.1 实现](./workflow/steps/2.1.md) `[required · repeatable]`
- [2.2 质量检查](./workflow/steps/2.2.md) `[required · repeatable]`（极简档不强制派发 `trellis-check`，但仍需自行确认测试/lint 通过）
- [2.3 回滚](./workflow/steps/2.3.md) `[on demand]`

### Phase 3：收尾（Finish）
- [3.2 Debug 复盘](./workflow/steps/3.2.md) `[on demand]`
- [3.3 Spec 更新](./workflow/steps/3.3.md) `[required · once]`（完整/普通档；极简档跳过）
- [3.4 提交改动](./workflow/steps/3.4.md) `[required · once]`

> 注：3.1 已并入 2.2（最后一轮全范围检查）与 3.4（提交前奏）；1.5 已并入 1.4；3.5 已并入 3.4；编号均保留以避免破坏外部引用。

### 规则

1. 先确认当前处于哪个阶段，然后从下一步继续
2. 在每个阶段内按顺序执行步骤；`[required]` 步骤不能跳过
3. 阶段可以回退（如 Execute 暴露 prd 缺陷 → 回计划修正再重新进入执行）
4. `[once]` 步骤若输出已存在则跳过，不重复执行
5. 规划产物与语义收敛共同决定下一步；`design.md` / `implement.md` 是否需要由规划流程判断
6. 档位（完整/普通/极简）在创建任务前一次性选定，不中途切换；需要更重的流程时走完当前档或另开更高档任务

### 激活任务路由

激活任务内请求匹配以下意图时，先路由，再按需加载对应步骤详情（Claude Code 等子代理分发平台）：

- 规划或需求不明确 -> `trellis-brainstorm`。
- `in_progress` 的实现/检查 -> 派发 `trellis-implement` / `trellis-check`。
- 反复调试 -> `trellis-break-loop`；spec 更新 -> `trellis-update-spec`。

（内联平台：编辑前 `trellis-before-dev`，编辑后 `trellis-check`。）

### 护栏

- 创建任务许可 ≠ 实现许可；实现等产物评审后 `task.py start`。
- 完整档的 `design.md` + `implement.md` 判断仍由规划流程负责；确定性前置条件由 `task.py start` 的 central gate 执行。
- 规划必须落盘到任务产物；报告完成前必须先运行检查。

### 加载步骤详情

```bash
python3 ./.trellis/scripts/get_context.py --mode phase --step <step>
# 例如 python3 ./.trellis/scripts/get_context.py --mode phase --step 1.1
```

---
