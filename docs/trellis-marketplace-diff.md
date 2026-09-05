# trellis-runes 与 trellis-marketplace 的工作流差异说明

> 生成时间：2026-09-05 · 只对比**工作流及其直接相关部分**（激活、任务模型、步骤、测试模型、门禁、证据、agents），不展开项目结构/发布/技术栈。
> marketplace 参考包为 `workflows/ai-native-harness-dev/`（基线 `6526b23`）。

## 0. 关系一句话

marketplace 是「门禁能力/工作流」的**货源**，runes 是把它**重写进自己 Central Gate** 的采用方。runes 的 `.trellis/workflow.md` 是 198 行精简汉化版；marketplace 的 `workflow.md` 是 1243 行完整分发基准。

## 1. 激活机制（触发方式）

| | marketplace | runes |
|---|---|---|
| 原则 | **每轮请求分流**：无 active task 时，先对本 turn 做 Request Triage、征得建任务同意，才建任务 | **首字符前缀触发**：仅用户消息以 `创建任务` / `恢复任务` 开头时加载工作流，无每轮分流 |
| 语义 | 分流决定建哪种任务与档位 | 激活是判定，不自动建/改任务状态；无会话身份直接 CLI 调用降级放行 |
| runes 对应物 | — | workflow activation gate（`session_activated_for_create` / `session_activated_for_start`）|

## 2. 任务模型与档位

| | marketplace | runes |
|---|---|---|
| 任务分类 | 分流 + 多任务模式（计划文档口径为“四档”） | **三档**：完整 / 普通 / 极简 |
| 档位差异 | 不适用（runes 不照搬） | 完整=design/implement+manifest；普通=仅 prd；极简=不建任务、落盘 workspace、**不经过 Central Gate** |
| 档位记录 | 重编号步骤体现 | `task.json.meta.trellis_tier`（full/normal）供恢复时读回 |

## 3. 步骤编号

| marketplace | runes |
|---|---|
| 完整重编号：`1.1b` 测试方案、`2.1a` 测试基线门禁、`2.1b` Review、`2.1c` SQL、`2.2/2.3a/2.3b`（unit/API/E2E）、`2.4` 独立验收、`2.5` 回滚、`1.5/3.5` 完成/收尾 | 精简编号：`1.0`→`3.4`；缺号（1.5 并入 1.4、3.1 并入 2.2、3.5 并入 3.4）保留占位，避免破坏外部引用 |
| 单文件 1243 行内嵌 | 198 行骨架 + `workflow/steps/{1.0..3.4}.md` 分步详情 |

## 4. 测试模型（前置方案 vs 执行分层）

| | marketplace | runes |
|---|---|---|
| 方案 | 1.1b 产出**双 test-plan**（unit + integration），由 `contracts/test-design.md` 约束 | 1.1 产出 `test-plan-unit.md`；PRD 风险要求时再加 `test-plan-integration.md` |
| 分级字段 | 无显式字段（由步骤推进） | `meta.evidence_test_level ∈ {unit, unit+api, unit+api+e2e}`，完整档按风险动态选一层 |
| 执行链 | 2.2 unit → 2.3a API → 2.3b E2E → 2.4 **独立验收验证** | 2.2 质量检查（跑验证命令）、2.3 回滚按需；无独立验收/无 test-report 分层文件 |
| 防篡改 | `evidence_activate.py` 把测试方案 hash 写入 meta | `task_start` 冻结 `meta.test_plan_sha256`，归档重算比对（`test_plan_unchanged`），漂移即拒绝 |

## 5. 门禁实现（两者最大差别）

| | marketplace | runes |
|---|---|---|
| 载体 | **24 个独立 Python runtime 脚本**（约 7900 行）作为 workflow 资产：`evidence_activate/baseline/gate_result/findings_log/gate_findings/gate_ac_checklist/delivery_checklist/rollback_counter/report_store/lifecycle_log/…`，由 workflow.md 步骤内嵌命令逐个调用 | **单一声明式 policy** `.trellis/gates.yaml`（36 行）+ **纯函数引擎** `.trellis/scripts/common/gate.py`（601 行），`task.py start/validate/archive` 统一 `gate.require()` |
| 形态 | 脚本各自带参数/退出码，分散在步骤里 | 规则注册进 `gate.py` RULES，纯函数求值，fail-closed（未知 gate/规则/异常一律拒绝） |
| 绕过 | 依赖脚本行为 | 刻意无 `--skip-*` / `--allow-*` 开关 |
| task_archive 门禁 | 各 gate 脚本 + after_archive hook 组合 | `task_json_ready + archive_branch_metadata + archive_destination_available + test_plan_unchanged + baseline_diff_clean + findings_resolved + delivery_checklist_passed + rollback_circuit_not_tripped` |

## 6. 证据产物（落什么盘）

| marketplace | runes |
|---|---|
| `baseline/{before,after,diff}.json`、findings | `baseline/{before,after,diff}.json`（只拦截 `new` 失败）、`findings.jsonl`（P0/P1/P2，零发现也显式声明） |
| 额外投影链：`report.json`（统计）、`gate-result.jsonl`（门禁事件）、`lifecycle-events.jsonl`（过程事实：human-gate/dispatch/review-verdict/phase-transition/consult/sql-review）、`dispatch-evidence.jsonl`、scar / test_metrics / scenario_coverage / spec_freshness | **部分吸收**：task-local `gate-result.jsonl` 与 `lifecycle-events.jsonl`（phase-transition、human-gate、rollback）；其余投影不引入。 |

## 7. Agents 与契约

| | marketplace | runes |
|---|---|---|
| channel agents | `builder.md` / `review.md` / `teacher.md` / `verify.md`（多模型角色：planner+builder+teacher） | `check.md` / `implement.md` / `review.md` / `verify.md`（**无 builder/teacher**） |
| 接口/实现分离 | 工作流只引用 `.trellis/contracts/*.md`（prd-format / test-design / check / e2e-environment），项目自填 | **无 contracts 目录**；任务变体小 |
| review/verify 角色 | plan review + code review + execute-based | 只读、禁止写文件/Git、输出 APPROVED/CONDITIONAL/REJECTED，完整档可选 |

## 8. 吸收 vs 未吸收（工作流相关）

**吸收（落地，todo 四阶段全勾）**：测试方案先写 + hash 防篡改；baseline 只拦新失败；findings 闭环；交付清单；回滚 3 次熔断；只读 review/verify。

**没吸收**：每轮请求分流与四档模型（保留三档 + 前缀激活）；完整步骤重编号；contracts 接口/实现分离；report.json、dispatch-evidence、test_metrics/scar/scenario_coverage/spec_freshness 指标投影；SQL 专项审核路由；builder/teacher 角色。

> 迁移纪律：禁止把 marketplace 的 source script 原样拷进 `.trellis/scripts/`；每项按「输入/产物/失败条件/测试」重写为 `gates.yaml` 规则 + `gate.py` 纯函数（见 `docs/trellis-marketplace-evidence-gates-plan.md`）。
## 9. 未吸收项：再评估与建议（2026-09-05）

> 基准：runes 保留前缀激活 + 三档 + 单一 gates.yaml/gate.py + fail-closed + 极简档不介入 + 多平台同步（test_platform_parity.py）。以下按「是否值得、怎么吸收、优先级」逐项评。

| 未吸收项 | 建议 | 落点（若吸收） | 优先级/触发 |
|---|---|---|---|
| 每轮请求分流 | **不吸收** | — | runes 以 `创建任务`/`恢复任务` 前缀 + 双层激活门禁显式触发，吸收＝推翻激活模型；三档单选已覆盖同档位选择 |
| 四档任务模型 | **不吸收** | — | 三档（完整/普通/极简）已覆盖；极简档不建任务的设计保留 |
| 完整步骤重编号 | **不吸收** | — | 纯命名 churn，会破坏外部引用（workflow-backup、hooks、skills）；门禁语义已由 gate 名承接 |
| contracts 接口/实现分离 | **半吸收（可选）** | 先做「文档化格式契约」：把现有步骤隐含的 prd-format / test-design / check 报告格式 / 结论模板固化成 .trellis/spec/ 或 workflow 契约小节；**暂不引入**独立 .trellis/contracts/ 目录与工厂校验 gate | 低·等出现复用/多项目需求再机制化 |
| report / gate-result / lifecycle-events 投影体系 | **部分吸收（已完成）** | `evaluate()` 单次投影 task-local `gate-result.jsonl`；`lifecycle-events.jsonl` 记录 phase-transition、rollback 与通过 `task.py audit … human-gate` 显式提交的 PRD/commit/rollback 人工确认。自动写入失败只 warning，显式 audit 写入失败可重试。**不引入** report.json 统计投影、dispatch-evidence、test_metrics/scar/scenario_coverage/spec_freshness——runes 暂无消费端，吸收即死数据 | 已完成 |
| SQL 专项审核 | **不吸收（条件保留）** | 不引入 gate_sql_review.py / sql-engineer；若未来 PRD 涉核心 DB/schema，用「完整档 PRD 风险 → findings(P1) 承载 SQL 复核要求」的方式轻量覆盖 | 低·有真实 SQL 场景再启用 |
| builder/teacher 角色 | **可选吸收（渐进增强）** | 新增 .trellis/agents/{builder,teacher}.md 作为**可选 channel agent**：builder 供复杂完整档实现派发，teacher 只答疑不落盘；沿用 marketplace「存在即派发、缺失即回落平台原生」语义，不新增档位依赖；多平台副本受 test_platform_parity.py 约束。runes 已有 channel 基础（config.yaml channel.worker_guard + implement/check 均为 channel agent） | 中·有多模型/大任务需求再启用 |

**一句话**：真正值得补的是 **gate-result + lifecycle-events 两个审计账本**（补上 runes 目前「只记门禁结果、不记过程事实」的空白，且成本最低）；contracts 与 builder/teacher 属于「可选、渐进增强」；其余（分流/四档/重编号/SQL）维持不吸收。
