#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SessionStart hook protocol glue for Claude-family hosts."""
from __future__ import annotations

import json
import os
import sys
import warnings
from io import StringIO
from pathlib import Path

warnings.filterwarnings("ignore")

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / ".trellis" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.session_start import (
    _build_compact_current_state,
    _build_first_reply_notice,
    _build_workflow_overview,
    _check_legacy_spec,
    _collect_spec_index_paths,
    _detect_platform,
    _get_task_status,
    _load_trellis_config,
    _normalize_windows_shell_path,
    _persist_context_key_for_bash,
    _resolve_context_key,
    _resolve_spec_scope,
    _resolve_update_hint,
    should_skip_injection,
)


def main() -> None:
    if should_skip_injection():
        return
    try:
        hook_input = json.loads(sys.stdin.read())
        if not isinstance(hook_input, dict):
            hook_input = {}
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    project_dir = None
    for variable in (
        "CLAUDE_PROJECT_DIR", "QODER_PROJECT_DIR", "CODEBUDDY_PROJECT_DIR",
        "FACTORY_PROJECT_DIR", "CURSOR_PROJECT_DIR", "GEMINI_PROJECT_DIR",
        "KIRO_PROJECT_DIR", "COPILOT_PROJECT_DIR", "TRAE_PROJECT_DIR", "ZCODE_PROJECT_DIR",
    ):
        if value := os.environ.get(variable):
            project_dir = Path(_normalize_windows_shell_path(value)).resolve()
            break
    if project_dir is None:
        project_dir = Path(_normalize_windows_shell_path(hook_input.get("cwd", "."))).resolve()

    platform_hint = next(
        (
            name
            for variable, name in (
                ("ZCODE_PROJECT_DIR", "zcode"),
                ("CURSOR_PROJECT_DIR", "cursor"),
                ("CODEBUDDY_PROJECT_DIR", "codebuddy"),
                ("FACTORY_PROJECT_DIR", "droid"),
                ("GEMINI_PROJECT_DIR", "gemini"),
                ("QODER_PROJECT_DIR", "qoder"),
                ("KIRO_PROJECT_DIR", "kiro"),
                ("COPILOT_PROJECT_DIR", "copilot"),
                ("TRAE_PROJECT_DIR", "trae"),
                ("CLAUDE_PROJECT_DIR", "claude"),
            )
            if os.environ.get(variable)
        ),
        Path(__file__).resolve().parents[1].name,
    )
    platform = _detect_platform(
        hook_input,
        None if isinstance(hook_input.get("cursor_version"), str) else platform_hint,
    )
    trellis_dir = project_dir / ".trellis"
    context_key = _resolve_context_key(hook_input, platform)
    _persist_context_key_for_bash(context_key)
    is_mono, packages, scope_config, task_pkg, default_pkg = _load_trellis_config(
        trellis_dir, hook_input, platform
    )
    allowed_pkgs = _resolve_spec_scope(is_mono, packages, scope_config, task_pkg, default_pkg)
    spec_index_paths = _collect_spec_index_paths(trellis_dir, allowed_pkgs)

    output = StringIO()
    output.write("<session-context>\nTrellis compact SessionStart context. Use it to orient the session; load details on demand.\n</session-context>\n\n")
    output.write(_build_first_reply_notice(_resolve_update_hint(trellis_dir, context_key)))
    output.write("\n\n")
    if legacy_warning := _check_legacy_spec(trellis_dir, is_mono, packages):
        output.write(f"<migration-warning>\n{legacy_warning}\n</migration-warning>\n\n")
    output.write("<current-state>\n")
    output.write(_build_compact_current_state(trellis_dir, hook_input, spec_index_paths, platform))
    output.write("\n</current-state>\n\n<trellis-workflow>\n")
    output.write(_build_workflow_overview(trellis_dir / "workflow.md"))
    output.write("\n</trellis-workflow>\n\n<guidelines>\n")
    output.write("Task context order for implementation/check: jsonl entries -> `prd.md` -> `design.md if present` -> `implement.md if present`. Missing optional artifacts are skipped for lightweight tasks.\n\n")
    if spec_index_paths:
        output.write("## Available indexes (read on demand)\n")
        output.writelines(f"- {path}\n" for path in spec_index_paths)
        output.write("\n")
    output.write("Discover more via: `python3 ./.trellis/scripts/get_context.py --mode packages`\n</guidelines>\n\n")
    output.write(f"<task-status>\n{_get_task_status(trellis_dir, hook_input, platform)}\n</task-status>\n\n")
    output.write("<ready>\nContext loaded. Follow <task-status>. Load workflow/spec/task details only when needed.\n</ready>")
    context_text = output.getvalue()

    if platform == "kiro":
        print(context_text, flush=True)
        return
    result: dict[str, object] = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context_text}}
    if platform != "zcode":
        result["additional_context"] = context_text
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
