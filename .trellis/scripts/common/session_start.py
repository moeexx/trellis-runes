"""Shared, protocol-independent helpers for SessionStart hooks."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from .active_task import _detect_platform, resolve_active_task, resolve_context_key


_FIRST_REPLY_NOTICE_HEAD = """<first-reply-notice>
On the first visible assistant reply in this session, briefly acknowledge that Trellis SessionStart context loaded."""

_FIRST_REPLY_NOTICE_TAIL = """Choose the acknowledgment language in this order:
1. Use the language of the user's current request (the user message that triggered this reply).
2. If that request has no clear natural language, use an explicitly established project communication language.
3. If neither provides a language, output the language-neutral fallback exactly: `Trellis SessionStart ✓`.
Continue directly with the user's request after the acknowledgment.
The acknowledgment must not alter the language used for the remainder of the response.
This notice is one-shot: do not repeat it after the first visible assistant reply in this session.
</first-reply-notice>"""

FIRST_REPLY_NOTICE = f"{_FIRST_REPLY_NOTICE_HEAD}\n{_FIRST_REPLY_NOTICE_TAIL}"

_BREADCRUMB_TAG_RE = re.compile(
    r"\[workflow-state:([A-Za-z0-9_-]+)\]\s*\n.*?\n\s*\[/workflow-state:\1\]",
    re.DOTALL,
)

_STANDARD_NON_INTERACTIVE_VARS = (
    "CLAUDE_NON_INTERACTIVE",
    "QODER_NON_INTERACTIVE",
    "CODEBUDDY_NON_INTERACTIVE",
    "FACTORY_NON_INTERACTIVE",
    "CURSOR_NON_INTERACTIVE",
    "GEMINI_NON_INTERACTIVE",
    "KIRO_NON_INTERACTIVE",
    "COPILOT_NON_INTERACTIVE",
    "TRAE_NON_INTERACTIVE",
    "ZCODE_NON_INTERACTIVE",
)


def _normalize_windows_shell_path(path_str: str) -> str:
    """Translate unambiguous Unix-style Windows drive mounts."""
    if not isinstance(path_str, str) or not path_str:
        return path_str
    if not sys.platform.startswith("win"):
        return path_str

    path = path_str.strip()
    if re.match(r"^[A-Za-z]:[\\/]", path):
        return path

    for pattern in (r"^/([A-Za-z])/(.*)", r"^/cygdrive/([A-Za-z])/(.*)", r"^/mnt/([A-Za-z])/(.*)"):
        match = re.match(pattern, path)
        if match:
            drive, rest = match.group(1).upper(), match.group(2)
            return f"{drive}:\\{rest.replace('/', '\\')}"
    return path_str


def _build_first_reply_notice(update_hint: str | None) -> str:
    """Build the user-visible first-reply notice, optionally with an update hint."""
    if not update_hint:
        return FIRST_REPLY_NOTICE
    return (
        f"{_FIRST_REPLY_NOTICE_HEAD}\n"
        f"Also relay this Trellis maintenance notice on its own line in that same reply: {update_hint}\n"
        f"{_FIRST_REPLY_NOTICE_TAIL}"
    )


def should_skip_injection(non_interactive_vars: tuple[str, ...] = _STANDARD_NON_INTERACTIVE_VARS) -> bool:
    if os.environ.get("TRELLIS_HOOKS") == "0":
        return True
    if os.environ.get("TRELLIS_DISABLE_HOOKS") == "1":
        return True
    return any(os.environ.get(variable) == "1" for variable in non_interactive_vars)


def read_file(path: Path, fallback: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return fallback


def _repo_relative(repo_root: Path, path: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def _run_git(repo_root: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            cwd=str(repo_root),
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _format_git_state(repo_root: Path) -> str:
    branch = _run_git(repo_root, ["branch", "--show-current"]) or "(detached)"
    dirty_lines = [line for line in _run_git(repo_root, ["status", "--porcelain"]).splitlines() if line.strip()]
    dirty_text = "clean" if not dirty_lines else f"dirty {len(dirty_lines)} paths"
    return f"Git: branch {branch}; {dirty_text}."


def _resolve_context_key(input_data: dict[str, Any], platform: str) -> str | None:
    return resolve_context_key(input_data, platform=_detect_platform(input_data, platform))


def _persist_context_key_for_bash(context_key: str | None) -> None:
    """Append a deduplicated context export to Claude-compatible env files."""
    if not context_key:
        return
    env_file = os.environ.get("CLAUDE_ENV_FILE")
    if not env_file:
        return
    export_line = f"export TRELLIS_CONTEXT_ID={shlex.quote(context_key)}"
    try:
        if _last_context_key_export(env_file) == export_line:
            return
        with open(env_file, "a", encoding="utf-8") as handle:
            handle.write(f"{export_line}\n")
    except OSError:
        pass


def _last_context_key_export(env_file: str) -> str | None:
    last_export = None
    try:
        with open(env_file, "r", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                stripped = raw_line.strip()
                if stripped.startswith("export TRELLIS_CONTEXT_ID="):
                    last_export = stripped
    except FileNotFoundError:
        return None
    return last_export


def _resolve_update_hint(trellis_dir: Path, context_key: str | None) -> str | None:
    try:
        from .session_context import get_update_hint

        return get_update_hint(trellis_dir.parent, context_key)
    except Exception:
        return None


def _resolve_active_task(trellis_dir: Path, input_data: dict[str, Any], platform: str):
    return resolve_active_task(
        trellis_dir.parent,
        input_data,
        platform=_detect_platform(input_data, platform),
    )


def run_script(script_path: Path, context_key: str | None = None, *, allow_non_python: bool = True) -> str:
    try:
        env = os.environ.copy()
        if context_key:
            env["TRELLIS_CONTEXT_ID"] = context_key
        if script_path.suffix == ".py":
            env["PYTHONIOENCODING"] = "utf-8"
            command = [sys.executable, "-W", "ignore", str(script_path)]
        elif allow_non_python:
            command = [str(script_path)]
        else:
            return "No context available"
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            cwd=script_path.parent.parent.parent,
            env=env,
        )
        return result.stdout if result.returncode == 0 else "No context available"
    except (subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        return "No context available"


def _normalize_task_ref(task_ref: str) -> str:
    normalized = task_ref.strip()
    if not normalized:
        return ""
    path_obj = Path(normalized)
    if path_obj.is_absolute():
        return str(path_obj)
    normalized = normalized.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return f".trellis/{normalized}" if normalized.startswith("tasks/") else normalized


def _resolve_task_dir(trellis_dir: Path, task_ref: str) -> Path:
    normalized = _normalize_task_ref(task_ref)
    path_obj = Path(normalized)
    if path_obj.is_absolute():
        return path_obj
    if normalized.startswith(".trellis/"):
        return trellis_dir.parent / path_obj
    return trellis_dir / "tasks" / path_obj


def _get_task_status(trellis_dir: Path, input_data: dict[str, Any], platform: str) -> str:
    active = _resolve_active_task(trellis_dir, input_data, platform)
    is_codex = platform == "codex"
    if not active.task_path:
        next_label = "Next" if is_codex else "Next-Action"
        next_action = (
            "Classify the current turn and ask for task-creation consent before creating any Trellis task."
            if is_codex
            else "Classify the current turn before creating any Trellis task. Simple conversation / small task asks only whether this turn should create a Trellis task. Complex task asks whether task creation and planning are allowed."
        )
        return f"Status: NO ACTIVE TASK\n{next_label}: {next_action}"

    task_ref = active.task_path
    task_dir = _resolve_task_dir(trellis_dir, task_ref)
    if active.stale or not task_dir.is_dir():
        if is_codex:
            return f"Status: STALE POINTER\nTask: {task_ref}\nNext: Task directory not found. Run: python3 ./.trellis/scripts/task.py finish"
        return f"Status: STALE POINTER\nTask: {task_ref}\nNext-Action: Run `python3 ./.trellis/scripts/task.py finish` to clear the stale pointer, then ask the user what to work on next."

    task_data: dict[str, Any] = {}
    task_json_path = task_dir / "task.json"
    if task_json_path.is_file():
        try:
            data = json.loads(task_json_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                task_data = data
        except (json.JSONDecodeError, PermissionError):
            pass
    task_title = task_data.get("title", task_ref)
    task_status = task_data.get("status", "unknown")
    if task_status == "completed":
        next_label = "Next" if is_codex else "Next-Action"
        next_action = "Run `/trellis:finish-work`; archive uses the central completion gate." if is_codex else "Run `/trellis:finish-work`. If the working tree is dirty, return to Phase 3.4 first."
        return f"Status: COMPLETED\nTask: {task_title}\n{next_label}: {next_action}"
    if task_status == "planning":
        next_label = "Next" if is_codex else "Next-Action"
        next_action = "Complete planning and request review, then run `python3 ./.trellis/scripts/task.py start <task-dir>`; its gate reports failures to fix and retry."
        return f"Status: PLANNING\nTask: {task_title}\n{next_label}: {next_action}"
    next_action = (
        "Follow the matching per-turn workflow-state. Context order is jsonl entries, prd.md, design.md if present, implement.md if present."
        if is_codex
        else "Follow the matching per-turn workflow-state. Implementation/check context order is jsonl entries -> `prd.md` -> `design.md if present` -> `implement.md if present`."
    )
    next_label = "Next" if is_codex else "Next-Action"
    return f"Status: {str(task_status).upper()}\nTask: {task_title}\n{next_label}: {next_action}"


def _load_trellis_config(trellis_dir: Path, input_data: dict[str, Any], platform: str) -> tuple:
    try:
        from .config import get_default_package, get_packages, get_spec_scope, is_monorepo
        from .paths import get_current_task

        repo_root = trellis_dir.parent
        is_mono = is_monorepo(repo_root)
        packages = get_packages(repo_root) or {}
        scope = get_spec_scope(repo_root)
        task_pkg = None
        current = get_current_task(repo_root, input_data, platform=_detect_platform(input_data, platform))
        if current:
            task_json = repo_root / current / "task.json"
            if task_json.is_file():
                try:
                    data = json.loads(task_json.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and isinstance(data.get("package"), str) and data["package"]:
                        task_pkg = data["package"]
                except (json.JSONDecodeError, OSError):
                    pass
        return is_mono, packages, scope, task_pkg, get_default_package(repo_root)
    except Exception:
        return False, {}, None, None, None


def _check_legacy_spec(trellis_dir: Path, is_mono: bool, packages: dict) -> str | None:
    if not is_mono or not packages:
        return None
    spec_dir = trellis_dir / "spec"
    if not spec_dir.is_dir():
        return None
    if not any((spec_dir / name / "index.md").is_file() for name in ("backend", "frontend")):
        return None
    missing = [name for name in sorted(packages) if not (spec_dir / name).is_dir()]
    if not missing:
        return None
    if len(missing) == len(packages):
        return "[!] Legacy spec structure detected: found `spec/backend/` or `spec/frontend/` but no package-scoped `spec/<package>/` directories.\nMonorepo packages: " + ", ".join(sorted(packages)) + "\nPlease reorganize: `spec/backend/` -> `spec/<package>/backend/`"
    return f"[!] Partial spec migration detected: packages {', '.join(missing)} still missing `spec/<pkg>/` directory.\nPlease complete migration for all packages."


def _resolve_spec_scope(is_mono: bool, packages: dict, scope: Any, task_pkg: str | None, default_pkg: str | None) -> set[str] | None:
    if not is_mono or not packages or scope is None:
        return None
    if scope == "active_task":
        if task_pkg and task_pkg in packages:
            return {task_pkg}
        return {default_pkg} if default_pkg and default_pkg in packages else None
    if isinstance(scope, list):
        valid = {entry for entry in scope if entry in packages}
        for entry in scope:
            if entry not in packages:
                print(f"Warning: spec_scope contains unknown package: {entry}, ignoring", file=sys.stderr)
        if valid:
            if task_pkg and task_pkg not in valid:
                print(f"Warning: active task package '{task_pkg}' is out of configured spec_scope", file=sys.stderr)
            return valid
        print("Warning: all spec_scope entries invalid, falling back to task/default/full", file=sys.stderr)
        if task_pkg and task_pkg in packages:
            return {task_pkg}
        return {default_pkg} if default_pkg and default_pkg in packages else None
    return None


def _collect_spec_index_paths(trellis_dir: Path, allowed_pkgs: set[str] | None = None) -> list[str]:
    paths: list[str] = []
    if (trellis_dir / "spec" / "guides" / "index.md").is_file():
        paths.append(".trellis/spec/guides/index.md")
    spec_dir = trellis_dir / "spec"
    if not spec_dir.is_dir():
        return paths
    for subdirectory in sorted(spec_dir.iterdir()):
        if not subdirectory.is_dir() or subdirectory.name.startswith(".") or subdirectory.name == "guides":
            continue
        if (subdirectory / "index.md").is_file():
            paths.append(f".trellis/spec/{subdirectory.name}/index.md")
            continue
        if allowed_pkgs is not None and subdirectory.name not in allowed_pkgs:
            continue
        for nested in sorted(subdirectory.iterdir()):
            if nested.is_dir() and (nested / "index.md").is_file():
                paths.append(f".trellis/spec/{subdirectory.name}/{nested.name}/index.md")
    return paths


def _build_compact_current_state(trellis_dir: Path, input_data: dict[str, Any], spec_index_paths: list[str], platform: str) -> str:
    from .paths import count_lines, get_active_journal_file, get_developer, get_tasks_dir
    from .tasks import iter_active_tasks

    repo_root = trellis_dir.parent
    lines = [f"Developer: {get_developer(repo_root) or '(not initialized)'}", _format_git_state(repo_root)]
    active = _resolve_active_task(trellis_dir, input_data, platform)
    if active.task_path:
        task_dir = _resolve_task_dir(trellis_dir, active.task_path)
        status = "unknown"
        task_json = task_dir / "task.json"
        if task_json.is_file():
            try:
                data = json.loads(task_json.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    status = str(data.get("status") or "unknown")
            except (json.JSONDecodeError, OSError):
                pass
        lines.append(f"Current task: {_repo_relative(repo_root, task_dir)}; status={status}.")
    else:
        lines.append("Current task: none.")
    try:
        task_count = sum(1 for _ in iter_active_tasks(get_tasks_dir(repo_root)))
        lines.append(f"Active tasks: {task_count} total. Use `python3 ./.trellis/scripts/task.py list --mine` only if needed.")
    except Exception:
        pass
    journal = get_active_journal_file(repo_root)
    if journal:
        lines.append(f"Journal: {_repo_relative(repo_root, journal)}, {count_lines(journal)} / 2000 lines.")
    if spec_index_paths:
        lines.append(f"Spec indexes: {len(spec_index_paths)} available.")
    return "\n".join(lines)


def _extract_range(content: str, start_header: str, end_header: str) -> str:
    lines = content.splitlines()
    start = None
    end = len(lines)
    for index, line in enumerate(lines):
        if start is None and line.strip() == f"## {start_header}":
            start = index
        elif start is not None and line.strip() == f"## {end_header}":
            end = index
            break
    return "" if start is None else "\n".join(lines[start:end]).rstrip()


def _strip_breadcrumb_tag_blocks(content: str) -> str:
    stripped = _BREADCRUMB_TAG_RE.sub("", content)
    stripped = re.sub(r"<!--.*?-->", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"^\[(?!/?workflow-state:)/?[^\]\n]+\]\s*\n?", "", stripped, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def _build_workflow_overview(workflow_path: Path) -> str:
    content = read_file(workflow_path)
    if not content:
        return "No workflow.md found"
    lines = [
        "# Development Workflow - Session Summary",
        "Workflow entry: .trellis/workflow.md. Step detail: `python3 ./.trellis/scripts/get_context.py --mode phase --step <X.Y>`.",
        "",
    ]
    phases = _extract_range(content, "Phase Index", "Phase 1: Plan")
    if phases:
        lines.append(_strip_breadcrumb_tag_blocks(phases).rstrip())
    return "\n".join(lines).rstrip()
