"""Session-scoped activation for opt-in Trellis workflow injection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .active_task import resolve_context_key
from .io import read_json, write_json


START_PREFIX = "开始任务"
RESUME_PREFIX = "恢复任务"
ACTIVATION_DIR = "workflow-activations"


@dataclass(frozen=True)
class WorkflowActivation:
    """The activation decision for one user prompt."""

    enabled: bool
    entry: str | None = None
    error: str | None = None


def entry_for_prompt(prompt: object) -> str | None:
    """Return the requested workflow entry for an exact prompt prefix."""
    if not isinstance(prompt, str):
        return None
    if prompt.startswith(START_PREFIX):
        return "start"
    if prompt.startswith(RESUME_PREFIX):
        return "resume"
    return None


def _marker_path(repo_root: Path, context_key: str) -> Path:
    return repo_root / ".trellis" / ".runtime" / ACTIVATION_DIR / f"{context_key}.json"


def _is_enabled(repo_root: Path, context_key: str) -> bool:
    return activation_entry(repo_root, context_key) is not None


def activation_entry(repo_root: Path, context_key: str) -> str | None:
    """Return the valid workflow entry activated for a session, if any."""
    data = read_json(_marker_path(repo_root, context_key))
    if isinstance(data, dict) and data.get("enabled") is True:
        entry = data.get("entry")
        if entry in {"start", "resume"}:
            return entry
    return None


def _enable(repo_root: Path, context_key: str, entry: str) -> bool:
    marker = _marker_path(repo_root, context_key)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return write_json(marker, {"enabled": True, "entry": entry})


def resolve_workflow_activation(
    repo_root: Path,
    prompt: object,
    platform_input: dict[str, Any] | None = None,
    platform: str | None = None,
) -> WorkflowActivation:
    """Resolve whether a prompt may receive workflow context.

    A trigger activates only the resolved AI session. Non-trigger prompts do
    not infer activation from active-task state, keeping ordinary conversation
    completely outside the Trellis workflow until explicitly opted in.
    """
    entry = entry_for_prompt(prompt)
    context_key = resolve_context_key(platform_input, platform)
    if not context_key:
        if entry:
            return WorkflowActivation(
                enabled=False,
                entry=entry,
                error="未获取到稳定的会话标识，无法建立会话级工作流状态；请在当前会话重试。",
            )
        return WorkflowActivation(enabled=False)

    if entry:
        if not _enable(repo_root, context_key, entry):
            return WorkflowActivation(
                enabled=False,
                entry=entry,
                error="无法写入会话级工作流状态；请检查 .trellis/.runtime 的访问权限后重试。",
            )
        return WorkflowActivation(enabled=True, entry=entry)

    return WorkflowActivation(enabled=_is_enabled(repo_root, context_key))


def build_workflow_entry(entry: str) -> str:
    """Build the one-turn instruction that loads the selected workflow entry."""
    if entry == "resume":
        body = (
            "由“恢复任务”启用本会话的 Trellis workflow。先运行 "
            "`python3 ./.trellis/scripts/get_context.py` 与 "
            "`python3 ./.trellis/scripts/get_context.py --mode phase`，再读取 "
            "`.trellis/workflow.md`，并按需读取 `.trellis/workflow/steps/<step>.md`；"
            "根据 active task 的 status 与已有产物定位下一步，"
            "不要自动改变任务状态。"
        )
    else:
        body = (
            "由“开始任务”启用本会话的 Trellis workflow。先运行 "
            "`python3 ./.trellis/scripts/get_context.py` 与 "
            "`python3 ./.trellis/scripts/get_context.py --mode phase`，再读取 "
            "`.trellis/workflow.md`，并按需读取 `.trellis/workflow/steps/<step>.md`；"
            "按 Phase 1 分类当前请求，未经用户明确同意不要创建或启动任务。"
        )
    return f"<trellis-workflow-entry>\n{body}\n</trellis-workflow-entry>"


def build_activation_error(error: str) -> str:
    """Return a visible diagnostic for a trigger that cannot be persisted."""
    return f"<trellis-workflow-activation-error>\n{error}\n</trellis-workflow-activation-error>"
