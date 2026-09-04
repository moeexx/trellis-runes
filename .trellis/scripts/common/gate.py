#!/usr/bin/env python3
"""Central deterministic gate engine for Trellis lifecycle operations.

The policy is intentionally small and declarative. Rule implementations live
here so task commands, validation commands, hooks, and skills do not carry
their own copies of lifecycle enforcement.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .git import branch_exists_locally, has_git_remote
from .io import describe_json_read_failure, read_json_checked
from .paths import DIR_WORKFLOW, FILE_TASK_JSON
from .task_utils import archive_destination_for
from .trellis_config import parse_simple_yaml
from .active_task import resolve_context_key
from .workflow_activation import activation_entry


POLICY_FILE = "gates.yaml"


@dataclass
class GateContext:
    """Facts needed to evaluate a gate.

    ``task_data`` is optional so the engine can own loading and validation of
    task.json. Callers may provide already-loaded data to avoid a second read.
    """

    repo_root: Path
    task_dir: Path
    task_data: dict[str, Any] | None = None
    policy_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GateFailure:
    """One deterministic reason a gate was denied."""

    rule: str
    code: str
    message: str
    details: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GateResult:
    """Structured result returned by :func:`evaluate`."""

    gate: str
    failures: tuple[GateFailure, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failures

    def __bool__(self) -> bool:
        return self.ok


class _PolicyError(Exception):
    """Raised internally when the central policy cannot be trusted."""


RuleResult = GateFailure | tuple[GateFailure, ...] | None
Rule = Callable[[GateContext], RuleResult]


def _policy_path(ctx: GateContext) -> Path:
    return ctx.policy_path or (ctx.repo_root / DIR_WORKFLOW / POLICY_FILE)


def _load_policy(ctx: GateContext) -> dict[str, Any]:
    path = _policy_path(ctx)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise _PolicyError(f"policy_unreadable: {path.name}: {exc}") from exc

    try:
        policy = parse_simple_yaml(content, source=str(path), strict=True)
    except Exception as exc:  # pragma: no cover - parser errors are normalized
        raise _PolicyError(f"policy_invalid: {type(exc).__name__}") from exc

    if not isinstance(policy, dict) or str(policy.get("version", "")) != "1":
        raise _PolicyError("policy_invalid: version must be 1")

    gates = policy.get("gates")
    if not isinstance(gates, dict) or not gates:
        raise _PolicyError("policy_invalid: gates mapping is required")

    for gate_id, spec in gates.items():
        if not isinstance(gate_id, str) or not gate_id:
            raise _PolicyError("policy_invalid: gate id must be a non-empty string")
        if not isinstance(spec, dict):
            raise _PolicyError(f"policy_invalid: gate {gate_id} must be a mapping")
        if "require" not in spec:
            raise _PolicyError(f"policy_invalid: gate {gate_id}.require is required")
        required = spec["require"]
        if not isinstance(required, list) or not all(
            isinstance(rule_id, str) and rule_id for rule_id in required
        ):
            raise _PolicyError(f"policy_invalid: gate {gate_id}.require must be a list")
        if not required:
            raise _PolicyError(
                f"policy_invalid: gate {gate_id}.require cannot be empty"
            )
        transition = spec.get("transition")
        if transition is not None:
            if not isinstance(transition, dict):
                raise _PolicyError(
                    f"policy_invalid: gate {gate_id}.transition must be a mapping"
                )
            if not isinstance(transition.get("to"), str) or not transition.get("to"):
                raise _PolicyError(
                    f"policy_invalid: gate {gate_id}.transition.to is required"
                )
            if "from" in transition and not isinstance(transition["from"], str):
                raise _PolicyError(
                    f"policy_invalid: gate {gate_id}.transition.from must be a string"
                )
            if "from" in transition and not transition["from"]:
                raise _PolicyError(
                    f"policy_invalid: gate {gate_id}.transition.from cannot be empty"
                )
            if "idempotent" in transition:
                idempotent = transition["idempotent"]
                if not isinstance(idempotent, str) or idempotent.lower() not in {
                    "true",
                    "false",
                }:
                    raise _PolicyError(
                        f"policy_invalid: gate {gate_id}.transition.idempotent must be true or false"
                    )
        elif "idempotent" in spec:
            raise _PolicyError(
                f"policy_invalid: gate {gate_id}.idempotent requires a transition"
            )

    return policy


def _task_json(ctx: GateContext) -> tuple[dict[str, Any] | None, str | None]:
    if ctx.task_data is not None:
        return ctx.task_data, None
    data, reason = read_json_checked(ctx.task_dir / FILE_TASK_JSON)
    if data is not None:
        ctx.task_data = data
    return data, reason


def _task_json_ready(ctx: GateContext) -> GateFailure | None:
    data, reason = _task_json(ctx)
    if data is not None:
        return None
    path = ctx.task_dir / FILE_TASK_JSON
    _problem, repair = describe_json_read_failure(path, reason)
    return GateFailure(
        rule="task_json_ready",
        code=f"task_json_{reason or 'unreadable'}",
        message="task.json is missing or invalid",
        details={
            "path": str(path),
            "repair": f"{repair} Archive has no bypass; restore task.json, then retry.",
        },
    )


def _planning_artifacts_ready(ctx: GateContext) -> GateFailure | None:
    path = ctx.task_dir / "prd.md"
    if not path.is_file():
        return GateFailure(
            rule="planning_artifacts_ready",
            code="missing_prd",
            message="prd.md is required",
            details={"path": str(path)},
        )
    try:
        path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return GateFailure(
            rule="planning_artifacts_ready",
            code="unreadable_prd",
            message="prd.md cannot be read",
            details={"path": str(path)},
        )
    return None


def _resolve_context_path(file_path: str, ctx: GateContext) -> Path | None:
    """Use task_context's archived self-reference handling without a cycle."""
    from .task_context import _resolve_context_entry_path

    return _resolve_context_entry_path(file_path, ctx.repo_root, ctx.task_dir)


def _context_ready(ctx: GateContext) -> RuleResult:
    failures: list[GateFailure] = []
    for name in ("implement.jsonl", "check.jsonl"):
        path = ctx.task_dir / name
        if not path.is_file():
            # Missing manifests are valid for inline / agent-less platforms.
            continue

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            failures.append(
                GateFailure(
                    rule="context_ready",
                    code="unreadable_manifest",
                    message=f"{name} cannot be read",
                    details={"path": str(path)},
                )
            )
            continue

        file_has_failure = False
        real_entries = 0
        for line_number, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                file_has_failure = True
                failures.append(
                    GateFailure(
                        rule="context_ready",
                        code="invalid_manifest_json",
                        message=f"{name} contains invalid JSON",
                        details={"path": str(path), "line": str(line_number)},
                    )
                )
                continue
            if not isinstance(row, dict):
                file_has_failure = True
                failures.append(
                    GateFailure(
                        rule="context_ready",
                        code="manifest_row_not_object",
                        message=f"{name} rows must be JSON objects",
                        details={"path": str(path), "line": str(line_number)},
                    )
                )
                continue
            if "_example" in row:
                file_has_failure = True
                failures.append(
                    GateFailure(
                        rule="context_ready",
                        code="placeholder_manifest_row",
                        message=f"{name} contains a legacy _example row",
                        details={"path": str(path), "line": str(line_number)},
                    )
                )
                continue

            file_path = row.get("file") or row.get("path")
            if not file_path:
                continue
            real_entries += 1
            if not isinstance(file_path, str):
                file_has_failure = True
                failures.append(
                    GateFailure(
                        rule="context_ready",
                        code="manifest_path_not_string",
                        message=f"{name} file path must be a string",
                        details={"path": str(path), "line": str(line_number)},
                    )
                )
                continue

            target = _resolve_context_path(file_path, ctx)
            entry_type = row.get("type", "file")
            if (
                target is None
                or (target.is_dir() if entry_type == "directory" else target.is_file())
                is False
            ):
                file_has_failure = True
                failures.append(
                    GateFailure(
                        rule="context_ready",
                        code="context_target_missing",
                        message=f"{name} references a missing path",
                        details={
                            "path": str(path),
                            "line": str(line_number),
                            "target": file_path,
                        },
                    )
                )

        if real_entries == 0 and not file_has_failure:
            failures.append(
                GateFailure(
                    rule="context_ready",
                    code="missing_curated_context",
                    message=f"{name} has no curated entries",
                    details={"path": str(path)},
                )
            )

    return tuple(failures) if failures else None


def _archive_branch_metadata(ctx: GateContext) -> GateFailure | None:
    data, _reason = _task_json(ctx)
    if data is None:
        return None

    branch = data.get("branch")
    base_branch = data.get("base_branch")
    branch = branch.strip() if isinstance(branch, str) else ""
    base_branch = base_branch.strip() if isinstance(base_branch, str) else ""

    if branch and not branch_exists_locally(branch, ctx.repo_root):
        print(
            f"Warning: recorded branch '{branch}' no longer exists locally "
            "(likely merged and deleted).",
            file=sys.stderr,
        )

    if branch and base_branch and branch == base_branch:
        return GateFailure(
            rule="archive_branch_metadata",
            code="branch_equals_base_branch",
            message="branch and base_branch must differ",
            details={"branch": branch},
        )
    if not branch and base_branch and has_git_remote(ctx.repo_root):
        return GateFailure(
            rule="archive_branch_metadata",
            code="missing_task_branch",
            message="task branch is required when a remote-backed base branch exists",
            details={"base_branch": base_branch},
        )
    return None


def _archive_destination_available(ctx: GateContext) -> GateFailure | None:
    destination = archive_destination_for(ctx.task_dir)
    if destination.exists():
        return GateFailure(
            rule="archive_destination_available",
            code="archive_destination_exists",
            message="archive destination already exists",
            details={"path": str(destination)},
        )
    return None


def _session_activated_for_create(ctx: GateContext) -> GateFailure | None:
    context_key = resolve_context_key()
    if not context_key:
        return None
    if activation_entry(ctx.repo_root, context_key) == "start":
        return None
    return GateFailure(
        rule="session_activated_for_create",
        code="workflow_not_started",
        message="start this session with 『创建任务』 before creating a task",
    )


def _session_activated_for_start(ctx: GateContext) -> GateFailure | None:
    context_key = resolve_context_key()
    if not context_key:
        return None
    if activation_entry(ctx.repo_root, context_key) in {"start", "resume"}:
        return None
    return GateFailure(
        rule="session_activated_for_start",
        code="workflow_not_activated",
        message="start this session with 『创建任务』 or 『恢复任务』 before starting a task",
    )


RULES: dict[str, Rule] = {
    "task_json_ready": _task_json_ready,
    "planning_artifacts_ready": _planning_artifacts_ready,
    "context_ready": _context_ready,
    "archive_branch_metadata": _archive_branch_metadata,
    "archive_destination_available": _archive_destination_available,
    "session_activated_for_create": _session_activated_for_create,
    "session_activated_for_start": _session_activated_for_start,
}


def _transition_failure(
    transition: dict[str, Any], ctx: GateContext
) -> GateFailure | None:
    data, _reason = _task_json(ctx)
    if data is None:
        return None
    current = data.get("status")
    target = transition.get("to")
    expected = transition.get("from")
    idempotent = str(transition.get("idempotent", "false")).lower() == "true"
    if idempotent and current == target:
        # A policy-declared idempotent transition may already be at its target.
        return None
    if expected and current != expected:
        return GateFailure(
            rule="transition",
            code="invalid_status_transition",
            message=f"task status must be {expected}",
            details={"current": str(current or ""), "expected": str(expected)},
        )
    return None


def evaluate(gate_id: str, ctx: GateContext) -> GateResult:
    """Evaluate one gate without mutating task or session state."""
    try:
        policy = _load_policy(ctx)
    except _PolicyError as exc:
        return GateResult(
            gate=gate_id,
            failures=(
                GateFailure(
                    rule="policy",
                    code="malformed_policy",
                    message=str(exc),
                    details={"path": str(_policy_path(ctx))},
                ),
            ),
        )

    gates = policy["gates"]
    spec = gates.get(gate_id)
    if not isinstance(spec, dict):
        return GateResult(
            gate=gate_id,
            failures=(
                GateFailure(
                    rule="policy",
                    code="unknown_gate",
                    message="gate is not defined by the central policy",
                    details={"gate": gate_id},
                ),
            ),
        )

    failures: list[GateFailure] = []
    transition = spec.get("transition")
    if isinstance(transition, dict):
        failure = _transition_failure(transition, ctx)
        if failure is not None:
            failures.append(failure)

    for rule_id in spec.get("require", []):
        rule = RULES.get(rule_id)
        if rule is None:
            failures.append(
                GateFailure(
                    rule=rule_id,
                    code="unknown_rule",
                    message="rule is not implemented by the central engine",
                )
            )
            continue
        try:
            failure = rule(ctx)
        except Exception as exc:
            failure = GateFailure(
                rule=rule_id,
                code="rule_error",
                message="rule could not be evaluated",
                details={"error": type(exc).__name__},
            )
        if failure is None:
            continue
        if isinstance(failure, GateFailure):
            failures.append(failure)
        else:
            failures.extend(failure)

    return GateResult(gate=gate_id, failures=tuple(failures))


def _render_failure(failure: GateFailure) -> list[str]:
    lines = [f"- {failure.rule}:", f"  {failure.code}: {failure.message}"]
    for key, value in failure.details.items():
        lines.append(f"  {key}: {value}")
    return lines


def require(gate_id: str, ctx: GateContext) -> GateResult:
    """Evaluate a gate and print only actionable failures."""
    result = evaluate(gate_id, ctx)
    if result.ok:
        return result
    print(f"GATE FAILED: {gate_id}", file=sys.stderr)
    for failure in result.failures:
        for line in _render_failure(failure):
            print(line, file=sys.stderr)
    return result
