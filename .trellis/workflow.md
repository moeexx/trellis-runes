# 开发工作流（精简汉化版）

> 本文档是 `.trellis/workflow.md` 的中文精简版，聚焦开发任务实操，是运行时的工作流依据。
> 完整英文原文（含 fork 定制、解析器/契约 meta、平台专属重复块、Codex 内联变体、
> workspace 会话日志等精简掉的内容）见 `docs/workflow-backup.md`。

## 核心原则

1. **先计划后编码** —— 动手之前先想清楚要做什么
2. **规范靠注入而非记忆** —— 规范通过 hook/skill 注入，而不是靠记忆回想
3. **一切落盘** —— 研究、决策、经验教训都要写入文件；对话会被压缩，文件不会
4. **增量开发** —— 一次只做一个任务
5. **沉淀收获** —— 每个任务结束后，回顾并把新知识写回 spec

## Trellis 系统

### 开发者身份

首次使用初始化身份：

```bash
python3 ./.trellis/scripts/init_developer.py <your-name>
```

创建 `.trellis/.developer`（gitignored）+ `.trellis/workspace/<your-name>/`。不初始化身份时 `task.py start` 无法设置激活任务。

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
# implement.jsonl / check.jsonl 建任务时预置空种子；仍为空时 validate 失败、start 拒绝。
python3 ./.trellis/scripts/task.py add-context <name> <action> <file> <reason>
python3 ./.trellis/scripts/task.py list-context <name> [action]
python3 ./.trellis/scripts/task.py validate <name>

# 元数据 / 层级 / PR
python3 ./.trellis/scripts/task.py set-branch <name> <branch>
python3 ./.trellis/scripts/task.py set-base-branch <name> <branch>
python3 ./.trellis/scripts/task.py set-scope <name> <scope>
python3 ./.trellis/scripts/task.py add-subtask <parent> <child>
python3 ./.trellis/scripts/task.py remove-subtask <parent> <child>
python3 ./.trellis/scripts/task.py create-pr [name] [--dry-run]
```

> 权威命令列表：`python3 ./.trellis/scripts/task.py --help`

**当前任务机制**：`create` 创建目录，会话身份可用时自动设为激活任务；`start` 把 `task.json.status` 从 `planning` 翻转为 `in_progress`；`finish` 清除当前会话指针（status 不变）；`archive` 写 `status=completed` 并移到 `archive/`。状态存于 `.trellis/.runtime/sessions/`。若 hook 输入、`TRELLIS_CONTEXT_ID` 或平台会话环境变量均无 context key，`start` 报会话身份错误。

### Context 脚本

```bash
python3 ./.trellis/scripts/get_context.py                            # 完整会话运行时上下文
python3 ./.trellis/scripts/get_context.py --mode packages            # 可用 packages + spec layers
python3 ./.trellis/scripts/get_context.py --mode phase --step <X.Y>  # 某工作流步骤的详细指南
```

## Phase Index

```
Phase 1: Plan    → 分类请求、取得创建任务许可，然后撰写规划产物
Phase 2: Execute → 仅在任务状态为 in_progress 后实施
Phase 3: Finish  → 验证、更新 spec、提交、收尾
```

### 请求分类

- 简单对话或小任务：只询问本次是否需要创建 Trellis task。若用户说不，则本会话跳过 Trellis。
- 复杂任务：询问是否允许创建 Trellis task 并进入规划。若用户说不，不要做宽泛的内联实现；解释、澄清范围，或建议拆成更小任务。
- 用户同意创建任务 ≠ 同意开始实现。规划仍要先做。

### 规划产物

- `prd.md` —— 需求、约束与验收标准。不要放技术设计或执行清单。
- `design.md` —— 复杂任务的技术设计：边界、契约、数据流、取舍、兼容性、上线 / 回滚形态。
- `implement.md` —— 复杂任务的执行计划：有序检查清单、验证命令、评审关卡、回滚节点。
- `implement.jsonl` / `check.jsonl` —— 子代理上下文清单（spec + 研究），不替代 `implement.md`。
- 轻量任务可只有 PRD；复杂任务在 `task.py start` 前必须三件套齐全。

### 父 / 子任务树

多个可独立验证的交付物 → 父任务（拥有源需求、任务映射、跨子任务验收、最终集成评审；通常本身不做实现）。可独立规划/实现/检查/归档的交付物 → 子任务。父/子不是依赖系统：若子任务 B 依赖 A，在 B 的产物中写明顺序。

```bash
python3 ./.trellis/scripts/task.py create "<title>" --slug <name> --parent <parent-dir>  # 创建子任务
python3 ./.trellis/scripts/task.py add-subtask <parent> <child>     # 关联
python3 ./.trellis/scripts/task.py remove-subtask <parent> <child>  # 解除关联
```

[workflow-state:no_task]
当前没有激活任务。先对本次会话分类，在创建任何 Trellis task 之前先取得创建任务许可。
简单对话 / 小任务：只询问本次是否需要创建 Trellis task。若用户说不，则本会话跳过 Trellis。
复杂任务：询问用户是否允许创建 Trellis task 并进入规划阶段。若用户说不，解释、澄清范围，或建议拆成更小的任务。
[/workflow-state:no_task]

[workflow-state:task_error]
无法读取激活任务记录。不要创建或激活另一个任务。
检查上面提到的任务目录并修复其 task.json：必须是有效 JSON 对象且 status 非空；保留现有字段与产物。无法安全确定 status 时先询问用户。
[/workflow-state:task_error]

[workflow-state:planning]
加载 `trellis-brainstorm`，保持规划状态。
轻量任务：`prd.md` 即可。复杂任务：完成 `prd.md`、`design.md`、`implement.md`；在 `task.py start` 之前请用户评审。
多交付物范围：考虑父任务加若干可独立验证的子任务；依赖写进子任务产物，而非靠树结构位置暗示。
子代理模式：在 start 前把 `implement.jsonl` / `check.jsonl` 策划好。
[/workflow-state:planning]

[workflow-state:in_progress]
工具：`trellis-implement` / `trellis-research` 是子代理类型（非 Skill）；`trellis-update-spec` 是 skill；`trellis-check` 两者皆可，代码改动后验证优先用 Agent 形态。
流程：`trellis-implement` -> `trellis-check` -> `trellis-update-spec` -> 提交（Phase 3.4）-> `/trellis:finish-work`。
主会话默认派发 implement/check 子代理；子代理自身不得再派发同类的 implement/check。分派 prompt 以 `Active task: <task.py current 任务路径>` 开头；上下文读取顺序：jsonl 条目 -> `prd.md` -> `design.md`（如存在）-> `implement.md`（如存在）。
[/workflow-state:in_progress]

> Codex 内联变体（planning-inline / in_progress-inline）与已失效的 completed 块已省略，见 `docs/workflow-backup.md`。

### Phase 1：计划（Plan）
- 1.0 创建任务 `[required · once]`（仅在有任务创建许可之后）
- 1.1 需求探索 `[required · repeatable]`（`prd.md`；复杂任务还需 `design.md` + `implement.md`）
- 1.2 研究 `[optional · repeatable]`
- 1.3 配置上下文 `[required · once]`（子代理分发平台；内联平台跳过）
- 1.4 激活任务 `[required · once]`（评审关卡，然后 `task.py start`；status → in_progress）
- 1.5 完成标准

### Phase 2：执行（Execute）
- 2.1 实现 `[required · repeatable]`
- 2.2 质量检查 `[required · repeatable]`
- 2.3 回滚 `[on demand]`

### Phase 3：收尾（Finish）
- 3.2 Debug 复盘 `[on demand]`
- 3.3 Spec 更新 `[required · once]`
- 3.4 提交改动 `[required · once]`
- 3.5 收尾提醒

> 注：3.1 已并入 2.2（最后一轮全范围检查）与 3.4（提交前奏），编号保留以避免破坏外部引用。

### 规则

1. 先确认当前处于哪个阶段，然后从下一步继续
2. 在每个阶段内按顺序执行步骤；`[required]` 步骤不能跳过
3. 阶段可以回退（如 Execute 暴露 prd 缺陷 → 回计划修正再重新进入执行）
4. `[once]` 步骤若输出已存在则跳过，不重复执行
5. 产物存在性决定下一步；缺 `design.md` / `implement.md` 对轻量任务有效，对复杂任务则是规划不完整

### 激活任务路由

激活任务内请求匹配以下意图时，先路由，再按需加载对应步骤详情（Claude Code 等子代理分发平台）：

- 规划或需求不明确 -> `trellis-brainstorm`。
- `in_progress` 的实现/检查 -> 派发 `trellis-implement` / `trellis-check`。
- 反复调试 -> `trellis-break-loop`；spec 更新 -> `trellis-update-spec`。

（内联平台：编辑前 `trellis-before-dev`，编辑后 `trellis-check`。）

### 护栏

- 创建任务许可 ≠ 实现许可；实现等产物评审后 `task.py start`。
- 只有 PRD 对轻量任务有效；复杂任务需要 `design.md` + `implement.md`。
- 规划必须落盘到任务产物；报告完成前必须先运行检查。

### 加载步骤详情

```bash
python3 ./.trellis/scripts/get_context.py --mode phase --step <step>
# 例如 python3 ./.trellis/scripts/get_context.py --mode phase --step 1.1
```

---

## Phase 1: Plan

目标：对请求分类，需要任务时取得创建任务许可，在实现前产出所需规划产物。

#### 1.0 创建任务 `[required · once]`

仅在获得任务创建许可后创建：

```bash
python3 ./.trellis/scripts/task.py create "<task title>" --slug <name>
```

`--slug` 只是可读名称，**不要**带 `MM-DD-` 前缀（`create` 自动加）。任务树先建父任务，再用 `--parent` 建子任务；不要因子任务存在就启动父任务，启动拥有下一份可独立验证交付物的子任务。

这里只运行 `create`，不要 `start`（`start` 会提前把 breadcrumb 切到实现阶段；留给 1.4）。若 `task.py current --source` 已指向任务则跳过。

#### 1.1 需求探索 `[required · repeatable]`

加载 `trellis-brainstorm` skill，按它的指引与用户交互探索需求：

- 一次只问一个问题；优先研究而非问用户；优先给选项而非开放式提问
- 每次回答后立即更新 `prd.md`；交付物可独立验证时拆成父/子任务
- `prd.md` 只放需求与验收标准；复杂任务在实现前产出 `design.md`、`implement.md`

父/子拆分判断：父任务 = 源需求 + 子任务映射 + 跨子任务验收 + 最终集成评审；子任务 = 可独立规划/实现/检查/归档的交付物；依赖写进子任务产物（而非结构暗示）；有下一份交付物就启动对应子任务，父任务除非本身有实现工作否则不启动。需求变化随时回到本步修订产物。

#### 1.2 研究 `[optional · repeatable]`

任何阶段都可做研究，不限本地代码（MCP、skills、web 等）。

派发研究子代理：
- **Agent 类型**：`trellis-research`
- **任务描述**：Research <具体问题>
- **关键要求**：输出必须持久化到 `{TASK_DIR}/research/`

产物约定：每个主题一个文件；记录第三方库用法、API 参考、版本约束；记下发现的相关 spec 路径。**关键原则：研究输出必须写入文件，对话会被压缩，文件不会。**

#### 1.3 配置上下文 `[required · once]`

策划 `{TASK_DIR}/implement.jsonl` 与 `{TASK_DIR}/check.jsonl`，让 Phase 2 子代理拿到正确的 spec/研究上下文。每行一个 JSON 对象 `{"file": "<path>", "reason": "<why>"}`，路径相对仓库根。

- **放**：相关 spec 文件（`.trellis/spec/<package>/<layer>/index.md` 及具体规范）、子代理需查阅的 `{TASK_DIR}/research/*.md`
- **不放**：代码文件、你即将修改的文件
- **分工**：`implement.jsonl` → 实现所需 spec+研究；`check.jsonl` → 检查所需 spec（质量规范等）
- 不替代 `implement.md`（那是人类可读的执行计划）

发现相关 spec 用 `python3 ./.trellis/scripts/get_context.py --mode packages`；追加条目直接编辑文件或用 `task.py add-context "$TASK_DIR" implement|check "<path>" "<reason>"`。

就绪门槛：两个文件在 `task.py start` 前各含至少一条真实条目（种子 `_example` 行不算）。

#### 1.4 激活任务 `[required · once]`

```bash
python3 ./.trellis/scripts/task.py start <task-dir>
```

轻量任务 `prd.md` 即可；复杂任务三件套必须存在并评审过；子代理分发平台两个 jsonl 必须有真实条目。若报会话身份错误，按提示设置会话身份后重试。

#### 1.5 完成标准

| 条件 | 是否必需 |
|------|:---:|
| 存在 `prd.md` | ✅ |
| 用户确认任务进入实现 | ✅ |
| 已运行 `task.py start`（status = in_progress） | ✅ |
| 两个 jsonl 各含至少一条真实条目（子代理分发平台） | ✅ |
| `research/` 有产物（复杂任务） | 建议 |
| 存在 `design.md`（复杂任务） | ✅ |
| 存在 `implement.md`（复杂任务） | ✅ |

---

## Phase 2: Execute

目标：把已评审的规划产物变成通过质量检查的代码。

#### 2.1 实现 `[required · repeatable]`

派发实现子代理：

- **Agent 类型**：`trellis-implement`
- **任务描述**：实现已评审的任务产物，查阅 `{TASK_DIR}/research/` 下的资料；最后运行项目 lint 与 type-check
- **分派 prompt 护栏**：prompt 必须以 `Active task: <task path>` 开头，并告知被派发代理它已是 `trellis-implement`，必须直接实现，不得再派发 `trellis-implement` / `trellis-check`。

平台 hook/plugin 自动处理：读取 `implement.jsonl` 注入引用的 spec/研究文件；注入 `prd.md`、`design.md`、`implement.md`。

#### 2.2 质量检查 `[required · repeatable]`

派发检查子代理：

- **Agent 类型**：`trellis-check`
- **任务描述**：对照 spec 与任务产物评审所有代码改动；直接修复发现的问题；确保 lint 与 type-check 通过
- **分派 prompt 护栏**：prompt 必须以 `Active task: <task path>` 开头，并告知被派发代理它已是 `trellis-check`，必须直接检查/修复，不得再派发 `trellis-check` / `trellis-implement`。

check 代理职责：对照 spec 与三份产物评审代码；自动修复；运行 lint 与 typecheck 验证。

**最后一轮（Phase 3.4 提交之前）**：最后一次 2.2 必须全范围运行。用 `get_context.py --mode packages` 列出受影响 package，加载各 spec index 的 Quality Check 一节，捕获跨层 / 多 package 问题。

#### 2.3 回滚 `[on demand]`

- `check` 暴露 prd 缺陷 → 回 Phase 1 修 `prd.md`，重做 2.1
- 实现出错 → 回退代码，重做 2.1
- 需要更多研究 → 研究（同 Phase 1.2），写入 `research/`

---

## Phase 3: Finish

目标：确保代码质量、沉淀经验、记录工作。

#### 3.2 Debug 复盘 `[on demand]`

反复调试（同一问题修复多次）时，加载 `trellis-break-loop`：分类根因、解释为何之前修复失败、提出预防。让同类问题不再复发。

#### 3.3 Spec 更新 `[required · once]`

加载 `trellis-update-spec`，评审本任务是否产出值得记录的新知识：新 pattern/约定、踩过的坑、新技术决策。据此更新 `.trellis/spec/`。即使结论是「没有要更新的」，也要走一遍判断。

#### 3.4 提交改动 `[required · once]`

**spec 同步前奏**：提交前先问：本任务是否修了 bug 或暴露了该落入 `.trellis/spec/` 的非显然知识？若是，先回 Phase 3.3 —— spec 写入属同一任务的提交批次，不要做成遗忘的后续补漏。

AI 驱动批量提交本次任务改动，让 `/finish-work` 之后可以干净执行。目标：先工作提交（work commits），后簿记提交（archive + journal），绝不穿插。

1. **检查脏状态**：`git status --porcelain`，快照每个脏路径；工作区干净则跳到 3.5。
2. **学习提交风格**：`git log --oneline -5`，注意前缀约定（`feat:` / `fix:` / `chore:` / `docs:` ...）、语言、长度风格。
3. **脏文件分两组**：本会话 AI 编辑过的 / 未识别（用户手工改动、遗留 WIP、无关工作 —— 不要静默纳入）。
4. **起草提交计划**：按逻辑提交分组（每个连贯变更单元一个提交，非每文件一个）；未识别文件单独列底。
5. **一次呈现、一次确认**。格式：
   ```
   Proposed commits (in order):
     1. <message>
        - <file>
        - <file>
     2. <message>
        - <file>

   Unrecognized dirty files (NOT in any commit — confirm include/exclude):
     - <file>
     - <file>

   Reply 'ok' / '行' to execute. Reply with edits, or '我自己来' / 'manual' to abort.
   ```
6. **确认后**按顺序 `git add <files>` + `git commit -m "<msg>"`；不 amend，不 push。
7. **被拒绝**（不行 / 我自己来 / manual / 任何异议）：停止，不再出第二份计划；用户手工提交，确认后跳到 3.5。

**规则**：禁止 `git commit --amend`（三阶段三提交）；本步绝不 push；只措辞不同则改消息再确认一次，分组被拒则退出手工模式；批量计划是一次 prompt，不逐个询问。

#### 3.5 收尾提醒

以上步骤后，提醒用户可运行 `/finish-work` 收尾（归档任务、记录会话）。
