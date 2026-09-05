# 从 trellis-marketplace 吸收证据门禁能力：Todo

## 原始项目参考清单

迁移来源为本机独立仓库 [`/home/moe/code/trellis-marketplace`](/home/moe/code/trellis-marketplace)，参考基线 `6526b23` 的 `workflows/ai-native-harness-dev/`。以下文件是行为和测试场景的来源；不得直接复制其 runtime，因为本仓库必须继续使用 Central Gate。

| 本次事项 | 必读原始文件 |
|---|---|
| 测试方案、激活和 hash | `workflow.md`、`contracts/test-design.md`、`scripts/evidence_activate.py` |
| baseline/diff | `scripts/evidence_plan.py`、`baseline.py`、`gate_result.py`、`tests/test_evidence_runtime.py` |
| findings | `scripts/findings_log.py`、`gate_findings.py`、`tests/test_findings_log.py` |
| 交付清单 | `scripts/delivery_checklist.py`、`gate_ac_checklist.py`、`readiness_check.py` |
| 回滚熔断 | `scripts/rollback_counter.py`、`contracts/e2e-environment.md` |
| review/verify | `agents/ai-native-harness-dev/{review,verify}.md`、`references/plan-review-dispatch.md`、`tests/test_gate_hardening_review.py` |

- [ ] 为每项迁移记录原始输入、产物、拒绝条件和本仓库对应的 Central Gate rule；确认没有把 source script 原样复制进本仓库。

## 阶段 1：测试方案与报告契约

- [x] 在 `.trellis/workflow/steps/1.1.md` 增加测试方案先行说明。
- [x] 参照原始 `contracts/test-design.md`，为完整档和普通档定义 `test-plan-unit.md` 的产出位置与最小内容。
- [x] 定义 PRD 风险触发 `test-plan-integration.md` 的条件和最小内容；确认不是所有普通档都被强制 API/E2E。
- [x] 定义 `task.json.meta.test_plan_sha256` 的字段、适用文件和交付复核契约；具体写入与强制校验在阶段 2 实现。
- [x] 确认极简档跳过测试方案和 hash 规则。
- [ ] 在 `.trellis/agents/implement.md` 增加统一交接状态：`DONE`、`DONE_WITH_CONCERNS`、`BLOCKED`、`NEEDS_CONTEXT`。
- [ ] 在 `.trellis/agents/check.md` 增加相同状态契约与结构化报告要求。
- [ ] 同步 `.claude/`、`.codex/`、`.kiro/`、`.qoder/`、`.agents/` 中的对应文件。
- [ ] 运行 `test_platform_parity.py`。

## 阶段 2：baseline/diff 与 findings ledger

- [ ] 阅读 `docs/gates.md`，确认新增 rule 的注册、fail-closed 与测试要求。
- [ ] 参照 `evidence_activate.py`，在 1.4 成功后把实际要求的测试计划 SHA-256 写入 `task.json.meta`；在交付 gate 重新计算并校验，防止事后修改。
- [ ] 定义 baseline 数据格式及验证命令的执行入口。
- [ ] 参照原始 `baseline.py`，实现生成 `baseline/before.json`、`baseline/after.json`、`baseline/diff.json` 的最小脚本，区分 new / known / resolved failures。
- [ ] 在 `gate.py` 实现 `baseline_diff_clean` 纯函数 rule。
- [ ] 在 `gate.py` 实现 `findings_resolved` 纯函数 rule。
- [ ] 在 `gates.yaml` 将 rule 接入 `context_validate` 或适合的新完成 gate。
- [ ] 参照原始 `findings_log.py`，扩展 check 报告：显式记录 P0/P1/P2 findings，零发现也需声明；每项必须有终态。
- [ ] 实现 P0/P1 未闭环阻断，P2 不阻断但必须有显式终态或接受记录。
- [ ] 更新 `docs/gates.md`。
- [ ] 为新增 rule 与生命周期补充 `tests/test_gate.py`、`tests/test_task_lifecycle.py`。

## 阶段 3：交付清单与回滚熔断

- [ ] 参照原始 `delivery_checklist.py`，定义最小 delivery checklist：Acceptance Criteria、测试证据、测试计划 hash、baseline diff、findings 终态及提交顺序。
- [ ] 明确本阶段不迁移原始覆盖率阈值、场景覆盖、SQL 审查路由与 report projection；这些能力以后按项目需要另立计划。
- [ ] 实现 `delivery_checklist_passed` rule 并注册到 `task_archive`。
- [ ] 参照原始 `rollback_counter.py`，实现按同一 phase 计数的回滚 meta（`phase`、`count`、`events`）。
- [ ] 实现连续回滚 3 次熔断的 `rollback_circuit_not_tripped` rule；仅人工介入后允许 reset。
- [ ] 在 `.trellis/workflow/steps/2.3.md` 说明回滚计数与熔断行为。
- [ ] 在 `.trellis/workflow/steps/3.4.md` 说明交付清单。
- [ ] 更新 `docs/gates.md` 和对应测试。

## 阶段 4：完整档可选 review/verify

- [ ] 参照原始 `review.md` 新增 `.trellis/agents/review.md`：只读、禁止文件/Git 写操作、输出 `APPROVED` / `CONDITIONAL` / `REJECTED` 与带证据的 blocking/advisory findings。
- [ ] 参照原始 `verify.md` 新增 `.trellis/agents/verify.md`：只读、禁止文件/Git 写操作、输出独立验收 verdict。
- [ ] 参照 `plan-review-dispatch.md`，要求主会话在 agent 返回后比较 `git status`；发现写入则本次 review 结果作废并重审。
- [ ] 同步新增 agent 文件至各平台并覆盖平台一致性测试。
- [ ] 在完整档说明中加入按 PRD 风险选择 `unit-only`、`unit+api`、`unit+api+e2e` 的规则。
- [ ] 在 1.4 前加入可选 `review` dispatch 说明。
- [ ] 在高风险任务的 2.2 后加入可选 `verify` dispatch 说明。
- [ ] 确认普通档和极简档没有新增强制路径。

## 每阶段验收

- [ ] 运行：`.venv/bin/python -m pytest tests/test_gate.py tests/test_task_lifecycle.py tests/test_platform_parity.py`
- [ ] 手工验证完整档：缺少所需证据时 gate 拒绝；补齐证据后放行。
- [ ] 手工验证极简档：不创建 task、不经过 Central Gate，原有行为不变。
- [ ] 检查各平台副本无漂移。
