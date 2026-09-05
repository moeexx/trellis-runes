# 从 trellis-marketplace 吸收证据门禁能力：实施计划

## 目标

在不改变既有 Central Gate、`创建任务` / `恢复任务` 触发短语和三档任务分级的前提下，吸收 `trellis-marketplace` 中独立于触发机制的证据可信度能力。新增内容必须以 Central Gate 的规则或可选工作流步骤接入，不引入平行脚本体系。

## 原始项目基线与迁移方式

本计划的原始项目是本机独立仓库 [`/home/moe/code/trellis-marketplace`](/home/moe/code/trellis-marketplace)，基线提交为 `6526b23`。参考对象是其可安装工作流包 `workflows/ai-native-harness-dev/`，而不是根目录的 marketplace 打包、发布或技术栈 spec。

原始包将完整工作流、契约、24 个 Python runtime scripts 和其测试安装至目标项目的 `.trellis/workflows/ai-native-harness-dev/`；它还单独提供 `agents/ai-native-harness-dev/{review,verify}.md`。本仓库不直接复制或安装该工作流包：现有 `.trellis/gates.yaml` + `scripts/common/gate.py` 是唯一门禁实现。迁移方式是逐项提炼其**可验证的不变量**，以当前 Central Gate 的 policy/rule/meta 形式重新实现。

| 要吸收的能力 | 原始项目的具体实现 | 本仓库的落点与差异 |
|---|---|---|
| 测试先行与防篡改 | `workflow.md` 1.1b/1.4；`contracts/test-design.md`；`scripts/evidence_activate.py` 对双测试方案写入 `meta.test_plan_sha256` | 在当前 1.1/1.4 中加入按风险产出的测试方案和 hash；保持三档模型，不照搬原始四档与完整重编号 |
| 仅阻断新增失败的 baseline | `scripts/evidence_plan.py`、`evidence_activate.py`、`baseline.py`、`gate_result.py`；`specs/.../baseline-and-gate-result-protocol.md` | 实现最小 before/after/diff 证据和 rule；不引入原项目的完整 evidence-plan、JSONL 指标投影体系 |
| Findings 闭环 | `scripts/findings_log.py`、`gate_findings.py`；`references/quality-metrics.md` | 采用 P0/P1/P2、零发现显式声明和终态校验；P0/P1 阻断、P2 仅记录，规则注册到 Central Gate |
| 交付校验 | `scripts/delivery_checklist.py`、`gate_ac_checklist.py`、`readiness_check.py` | 收敛为当前 `task_archive` 的 checklist rule；不复制覆盖率、场景覆盖、SQL 路由等项目特定子系统 |
| 回滚熔断 | `scripts/rollback_counter.py`；`contracts/e2e-environment.md` | 复用同相位连续回滚计数、阈值 3、人工干预后 reset 的语义，持久化在当前 task meta |
| 只读审查 | `agents/ai-native-harness-dev/{review,verify}.md`；`references/plan-review-dispatch.md` | 仅完整档可选；保留 `APPROVED/CONDITIONAL/REJECTED` 与 PASS/FAIL 类 verdict，不把 agent 输出直接等同于人工批准 |

原始代码和测试仅用作行为参考。每一项迁移应先从上述源文件提取输入、输出、失败条件和测试案例，再按本仓库的 `docs/gates.md` 契约重写；禁止把 source script 直接拷入 `.trellis/scripts/`。

## 保持不变的基座

- 保留前缀触发与双层激活门禁；不采用原始项目的每轮请求分流。
- 保留完整、普通、极简三档；完整档内按风险动态选择测试层级，不新增档位。
- 保留 `gates.yaml`（policy）与 `gate.py`（pure-function engine）的分层，以及 fail-closed 约定。
- 不引入 marketplace 的分发打包层、技术栈专属 spec、`builder.md` / `teacher.md` 角色拆分、SQL 专项路由和原始项目的完整步骤重编号。

## 设计原则

- 每项能力以新增 rule、meta 字段或可选步骤叠加，不能改变已有 gate 的语义。
- rule 的 policy 写入 `.trellis/gates.yaml`，判断逻辑写入 `.trellis/scripts/common/gate.py`；未知或缺失证据默认拒绝。
- 新增 gate/rule 必须同步更新 `docs/gates.md`，并补充生命周期与 gate 单元测试。
- 极简档不创建 task、不经过 Central Gate，行为必须保持不变。
- 多平台的同源 agent 文件必须同步，受 `tests/test_platform_parity.py` 约束。

## v1 实施决策

- 仅创建后带 `meta.evidence_gates_version = "1"` 的完整/普通档任务启用证据 gate；既有 task 不迁移、不阻断 archive。
- 测试层级写入 `meta.evidence_test_level`，只接受 `unit`、`unit+api`、`unit+api+e2e`；冻结 hash 只覆盖该层级实际要求的方案文件。
- baseline、findings 和 rollback 由 `task.py` 子命令调用 `common/` 实现，不新增独立 workflow runtime。

## 分阶段方案

### 阶段 1：测试方案与报告契约

参考原始项目 `workflow.md` 1.1b、`contracts/test-design.md` 和 `scripts/evidence_activate.py`。在步骤 1.1 增加“测试方案先行”说明：完整档和普通档至少产出 `test-plan-unit.md`；当 PRD 的风险分级要求 API/E2E 时，同时产出 `test-plan-integration.md`。极简档跳过。本阶段只定义计划文件、`task.json.meta.test_plan_sha256` 和交付复核的契约；实际 hash 写入与 fail-closed 校验留待阶段 2，避免“纯文档阶段”暗含生命周期代码改动。

参考原始项目 `agents/ai-native-harness-dev/builder.md` 和 `specs/ai-native-harness-dev/guides/lifecycle-events-protocol.md`，统一 `implement.md` 与 `check.md` 的交接状态为 `DONE`、`DONE_WITH_CONCERNS`、`BLOCKED`、`NEEDS_CONTEXT`，并同步各平台副本。

本阶段仅修改文档和报告契约，不修改 `gate.py`。

### 阶段 2：baseline/diff 与 findings ledger

以原始 `baseline.py` 的 before/after/diff 三文件和“new / known / resolved failures”分类为语义参考。实现 1.4 成功激活后的测试计划 SHA-256 冻结及交付时复核；再增加最小化 baseline 工具，在质量检查前后分别写入 `baseline/before.json`、`baseline/after.json` 和 `baseline/diff.json`；只将新增失败视为失败。不要引入原始 `gate-result.jsonl`、report projection 或所有指标解析功能。

以原始 `findings_log.py` / `gate_findings.py` 的 append-only ledger 和完整性校验为语义参考。`trellis-check` 的报告须列出 P0/P1/P2 findings；即使零发现也要显式声明。归档前 P0/P1 必须为 `fixed` 或带理由的 `wont-fix`，P2 必须有显式终态或接受记录。

### 阶段 3：交付清单与回滚熔断

以原始 `delivery_checklist.py` 的“交付时重新检查证据链”作为设计约束：在 `task_archive` 增加 `delivery_checklist_passed` 与 `rollback_circuit_not_tripped`，不能只相信 agent 自报。步骤 3.4 描述清单，步骤 2.3 记录回滚次数。遵循原始 `rollback_counter.py` 的语义：同一 phase 连续回滚达到 3 次时熔断，暂停并要求人工介入；仅在人工介入后才能 reset。

### 阶段 4：完整档可选只读 review/verify

以原始 `review.md`、`verify.md` 和 `references/plan-review-dispatch.md` 为模板新增只读 agent 契约，禁止文件/Git 写操作，并要求主会话在派发后用 `git status` 做只读后验。完整档可在 1.4 前可选 dispatch `review`，高风险任务在 2.2 后可选 dispatch `verify`。review 的 `APPROVED`、`CONDITIONAL`、`REJECTED` 仅是人工终审的前置过滤，不拥有任务激活权。完整档依据 PRD 风险动态使用 `unit-only`、`unit+api` 或 `unit+api+e2e`；普通档和极简档不变。

## 关键改动位置

- 工作流：`.trellis/workflow.md`、`.trellis/workflow/steps/{1.1,1.4,2.2,2.3,3.4}.md`
- Gate：`.trellis/gates.yaml`、`.trellis/scripts/common/gate.py`、必要时 `.trellis/scripts/task.py` 与 `common/task_store.py`
- Agent：`.trellis/agents/{implement,check}.md`，以及新增的 `review.md`、`verify.md`
- 文档与测试：`docs/gates.md`、`tests/test_gate.py`、`tests/test_task_lifecycle.py`、`tests/test_platform_parity.py`

## 原始实现的验证参考

迁移时可定向阅读原始项目的 `workflows/ai-native-harness-dev/tests/`：`test_evidence_runtime.py` 覆盖 baseline/evidence activation，`test_findings_log.py` 覆盖 findings 账本，`test_gate_hardening_review.py` 覆盖 review 激活前置，`test_workflow_runtime.py` 覆盖 runtime 协作。它们是测试场景来源，不应原样搬迁；本仓库的断言需围绕 `gates.yaml` 与 `gate.py` 的公开契约重写。
