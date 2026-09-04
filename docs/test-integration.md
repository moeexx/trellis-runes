# 接入测试体系

说明如何把项目自己的测试命令挂进 Central Gate，让"测试没过"和"task.json 缺失""context 未配置"一样，成为 `task.py` 拒绝状态翻转的确定性理由。不引入新机制，复用 [gates.md](./gates.md) 的 policy/engine 结构。

## 接入点选哪个

按你要卡住的时机选，不要都加：

| 想卡住什么 | 用哪个 gate | 为什么 |
|---|---|---|
| 进 `in_progress` 前先跑通测试 | `task_start` | 极少见；一般规划阶段还没代码可测，慎用 |
| 提交 / finish-work 前测试必须绿 | `task_archive` | 推荐：对应 workflow 3.4 提交改动，测试失败直接拒绝 archive |
| 平时随时自查，不卡状态翻转 | 新增一个独立 gate，命令侧只在 `task.py validate` 里调用 | 不阻塞流程，只做报告 |

多数团队只需要一个：**`task_archive` 加一条 `tests_passing` 规则**，测试不过不让归档。

## 三步接入

### 1. 在 `gate.py` 实现规则

规则是纯函数：不落盘、不改状态，只读取并返回 `None`（通过）或 `GateFailure`（失败）。

```python
import subprocess

def _tests_passing(ctx: GateContext) -> GateFailure | None:
    cmd = _test_command(ctx)  # 见下方"测试命令从哪来"
    if cmd is None:
        return None  # 未配置测试命令时不拦截，见"注意事项"

    result = subprocess.run(
        cmd, shell=True, cwd=ctx.repo_root,
        capture_output=True, text=True, timeout=600,
    )
    if result.returncode == 0:
        return None

    tail = "\n".join((result.stdout + result.stderr).splitlines()[-20:])
    return GateFailure(
        rule="tests_passing",
        code="tests_failed",
        message="测试未通过，先修复失败用例再重试",
        details={"command": cmd, "output_tail": tail},
    )
```

加入 `RULES` 注册表（`gate.py` 顶部或 `evaluate` 附近已有的 dict）：

```python
RULES: dict[str, Rule] = {
    ...
    "tests_passing": _tests_passing,
}
```

### 2. 在 `gates.yaml` 声明

```yaml
gates:
  task_archive:
    transition:
      from: in_progress
      to: completed
    require:
      - task_json_ready
      - archive_branch_metadata
      - archive_destination_available
      - tests_passing   # 新增这一行
```

### 3. 测试命令从哪来

不要硬编码命令，读配置：

```python
def _test_command(ctx: GateContext) -> str | None:
    from .trellis_config import read_trellis_config
    config = read_trellis_config(ctx.repo_root)
    return config.get("test_command")  # None 表示未配置
```

在 `.trellis/config.yaml` 里让用户自己填一行（monorepo 按 package 覆盖同理，参考文件里 `packages:` 块的写法）：

```yaml
test_command: "uv run pytest -q"
```

## 注意事项

- **未配置命令时不要 fail-closed 拦所有人**：`test_command` 缺省应放行（`return None`），否则每个新接入这套 workflow 的项目在没配好测试前会被卡死在归档，体验极差。等团队真正配好命令，规则自然开始生效。这是这条规则和 `task_json_ready` 等"结构性"规则的关键区别——后者永远 fail-closed，这条是可选项。
- **命令要快、要确定性**：gate 是同步阻塞的，跑一个几分钟的全量测试套件会让 `task.py archive` 变得很慢。建议 `test_command` 指向"改动相关的快测试"（unit + lint），全量回归留给 CI，不塞进 gate。
- **不要在 gate 里裁剪/重试测试逻辑**：规则只负责"跑一次、判断通过与否、截断输出"，测试框架本身的 flaky 重试、并发策略是测试命令自己的事，不要在 `gate.py` 里加重试循环。
- **超时要给够但要有上限**：本地全量测试可能超过默认超时，按你的测试套件实际耗时调整 `timeout=`，但一定要设一个上限——不设超时会让卡住的测试进程把整个 `task.py archive` 挂死。
- **补测试**：跟着 [gates.md「添加新 gate」](./gates.md#添加新-gate) 的清单走——`tests/test_gate.py` 补 pass/fail 路径（mock `subprocess.run`，不要在单测里真跑一遍项目测试套件），`tests/test_task_lifecycle.py` 补失败时状态不变、修好后可重试。
- **四平台文案同步**：改了 gate 行为，`docs/gates.md` 的规则清单表格、`workflow/steps/3.4.md`（提交改动）都要提一句"归档前会跑测试门禁"，同批改，不要留只有代码变了、文档没跟上的情况。
- **不要加绕过开关**：和其它 gate 规则一样，`tests_passing` 不允许有 `--skip-tests` 之类的 CLI flag。真要跳过，改 `test_command` 为空或调整 policy，这个决定需要留痕（改 `.trellis/config.yaml` 本身就是留痕）。

## 最小示例走查

1. `test_command: "uv run pytest -q"` 写进 `.trellis/config.yaml`。
2. 开发者跑 `python3 ./.trellis/scripts/task.py archive <name>`。
3. `task_archive` gate 依次跑完 `task_json_ready` / `archive_branch_metadata` / `archive_destination_available` / `tests_passing`；`tests_passing` 执行 `uv run pytest -q`，非 0 退出码即失败。
4. 失败信息（含命令与输出尾部 20 行）打到 stderr，archive 不执行，`task.json` 状态保持 `in_progress`。
5. 开发者本地修好测试，重跑 archive，规则重新求值，通过后正常归档。
