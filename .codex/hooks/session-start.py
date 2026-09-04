#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SessionStart hook protocol glue for Codex.

Codex requires its context inside ``hookSpecificOutput.additionalContext``.
"""
from __future__ import annotations

import json
import sys
import warnings
from io import StringIO
from pathlib import Path

warnings.filterwarnings("ignore")

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / ".trellis" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from common.session_start import (
    FIRST_REPLY_NOTICE,
    _build_compact_current_state,
    _build_workflow_overview,
    _collect_spec_index_paths,
    _detect_platform,
    _get_task_status,
    _normalize_windows_shell_path,
    should_skip_injection,
)


def main() -> None:
    if should_skip_injection(("CODEX_NON_INTERACTIVE",)):
        return
    try:
        hook_input = json.loads(sys.stdin.read())
        if not isinstance(hook_input, dict):
            hook_input = {}
        project_dir = Path(_normalize_windows_shell_path(hook_input.get("cwd", "."))).resolve()
    except (json.JSONDecodeError, KeyError):
        hook_input = {}
        project_dir = Path(".").resolve()

    platform = _detect_platform(hook_input, "codex")
    trellis_dir = project_dir / ".trellis"
    spec_index_paths = _collect_spec_index_paths(trellis_dir)
    output = StringIO()
    output.write("<session-context>\nTrellis compact SessionStart context. Use it to orient the session; load details on demand.\n</session-context>\n\n")
    output.write(FIRST_REPLY_NOTICE)
    output.write("\n\n<current-state>\n")
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
    result = {
        "suppressOutput": True,
        "systemMessage": f"Trellis context injected ({len(context_text)} chars)",
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context_text,
        },
    }
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
