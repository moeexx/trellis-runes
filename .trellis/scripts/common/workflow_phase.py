#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Workflow Phase Extraction.

Extracts workflow index content from .trellis/workflow.md and step-level
content from .trellis/workflow/steps/*.md.

Platform marker syntax in workflow.md and step contracts:

    [Claude Code, Cursor, ...]
    agent-capable content
    [/Claude Code, Cursor, ...]

Provides:
    get_phase_index   - Extract the Phase Index section (no --step)
    get_step          - Extract a complete step contract
    filter_platform   - Strip platform blocks that don't include the given name
"""

from __future__ import annotations

import re
from pathlib import Path

from .paths import DIR_WORKFLOW, get_repo_root


def _workflow_md_path():
    return get_repo_root() / DIR_WORKFLOW / "workflow.md"

# Match a line that *is* a platform marker: "[A, B, C]" or "[/A, B, C]"
_MARKER_RE = re.compile(r"^\[(/?)([A-Za-z][^\[\]]*)\]\s*$")

# Phase Index starts here; the compact index ends at the first phase body.
_PHASE_INDEX_HEADING = "## Phase Index"
_STEP_ID_RE = re.compile(r"^\d+\.\d+$")


def _read_workflow() -> str:
    path = _workflow_md_path()
    if not path.exists():
        raise FileNotFoundError(f"workflow.md not found: {path}")
    return path.read_text(encoding="utf-8")


def _workflow_step_path(step_id: object) -> Path | None:
    """Return the canonical path for one workflow step contract."""
    if not isinstance(step_id, str) or not _STEP_ID_RE.fullmatch(step_id):
        return None
    return get_repo_root() / DIR_WORKFLOW / "workflow" / "steps" / f"{step_id}.md"


def _parse_marker(line: str) -> tuple[bool, list[str]] | None:
    """Parse a platform marker line.

    Returns:
        (is_closing, [platform_names]) if line is a marker, else None.
    """
    m = _MARKER_RE.match(line)
    if not m:
        return None
    is_closing = m.group(1) == "/"
    names = [p.strip() for p in m.group(2).split(",") if p.strip()]
    return is_closing, names


def get_phase_index() -> str:
    """Return the compact Phase Index summary from workflow.md.

    SessionStart and no-step phase context use this small summary as their
    orientation payload. Detailed Phase 1/2/3 instructions are loaded with
    ``get_step`` on demand. ``[workflow-state:STATUS]`` tag blocks are
    consumed by the per-turn hook, so they're stripped from this output.
    """
    text = _read_workflow()
    lines = text.splitlines()

    start: int | None = None
    end: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start is None and stripped == _PHASE_INDEX_HEADING:
            start = i
            continue
        if start is not None and stripped == "## Phase 1: Plan":
            end = i
            break

    if start is None:
        return ""
    if end is None:
        end = len(lines)

    section = "\n".join(lines[start:end]).rstrip()
    # Strip [workflow-state:STATUS]...[/workflow-state:STATUS] blocks since
    # they're injected separately by inject-workflow-state.py per-turn.
    import re as _re
    tag_re = _re.compile(
        r"\[workflow-state:([A-Za-z0-9_-]+)\]\s*\n.*?\n\s*\[/workflow-state:\1\]\n?",
        _re.DOTALL,
    )
    return tag_re.sub("", section).rstrip() + "\n"


def get_step(step_id: str) -> str:
    """Return the complete step contract for ``step_id``."""
    path = _workflow_step_path(step_id)
    if path is None or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").rstrip() + "\n"
    except OSError:
        return ""


def _platform_matches(platform: str, block_names: list[str]) -> bool:
    """Case-insensitive fuzzy match: accept 'cursor', 'Cursor', 'claude-code', 'Claude Code'."""
    needle = platform.lower().replace("-", "").replace("_", "").replace(" ", "")
    for name in block_names:
        hay = name.lower().replace("-", "").replace("_", "").replace(" ", "")
        if needle == hay:
            return True
    return False


_PLATFORM_MARKER_LABELS: dict[str, str] = {
    # workflow.md marker blocks label platforms with their product names, but
    # every caller passes the stable id instead (`--platform {{CLI_FLAG}}` in
    # the start / continue commands). `_platform_matches` only strips
    # punctuation, so an id that is not its label-minus-spaces never matches and
    # `filter_platform` drops the block WITHOUT error — the section just comes
    # back empty. Four platforms shipped that way before this table existed.
    #
    # Add an entry whenever a platform's id is not its marker label with the
    # separators removed. `test/registry-invariants.test.ts` asserts every
    # registry id keeps a non-empty routing section, so a missing entry fails
    # there rather than silently blanking that platform's routing.
    "claude": "Claude Code",
    "kimi": "Kimi Code",
    "omp": "Oh My Pi",
    "dsh": "DeepSeek Harness",
}


def resolve_effective_platform(platform: str, config: dict) -> str:
    """Map ``codex`` to a dispatch-mode-namespaced virtual platform name.

    When ``--platform codex`` is passed, return ``"codex-sub-agent"`` by
    default or ``"codex-inline"`` when explicitly configured in
    ``.trellis/config.yaml``. ``sub-agent`` remains an alias for ``auto``.
    ``filter_platform`` then surfaces blocks whose marker lists include the
    namespaced name (e.g. ``[codex-sub-agent, ...]`` or ``[codex-inline, Kilo,
    Antigravity, Devin]``).

    Native Codex context injection supports the ``auto`` default. Invalid
    explicit values fall back to ``inline`` safely; this renderer deliberately
    does not warn because it can run in normal CLI output flows.

    Platforms whose marker label differs from their id resolve through
    ``_PLATFORM_MARKER_LABELS``. Everything else is returned unchanged.
    """
    label = _PLATFORM_MARKER_LABELS.get(platform.strip().lower())
    if label:
        return label
    if platform == "codex":
        mode = "auto"
        codex_cfg = config.get("codex") if isinstance(config, dict) else None
        if codex_cfg is not None:
            if not isinstance(codex_cfg, dict):
                mode = "inline"
            else:
                cfg_mode = str(codex_cfg.get("dispatch_mode", mode)).strip().lower()
                if cfg_mode == "inline":
                    mode = "inline"
                elif cfg_mode in ("auto", "sub-agent"):
                    mode = "auto"
                else:
                    mode = "inline"
        return "codex-sub-agent" if mode == "auto" else "codex-inline"
    return platform


def filter_platform(content: str, platform: str) -> str:
    """Keep lines outside any `[...]` block + lines inside blocks that include platform.

    Marker lines themselves are dropped from the output.
    """
    lines = content.splitlines()
    out: list[str] = []

    in_block = False
    keep_block = False

    for line in lines:
        marker = _parse_marker(line)
        if marker is not None:
            is_closing, names = marker
            if not is_closing:
                in_block = True
                keep_block = _platform_matches(platform, names)
            else:
                in_block = False
                keep_block = False
            continue  # drop the marker line itself

        if in_block:
            if keep_block:
                out.append(line)
            continue
        out.append(line)

    # Collapse runs of 3+ blank lines that may arise from dropped markers
    collapsed: list[str] = []
    blank_run = 0
    for line in out:
        if line.strip() == "":
            blank_run += 1
            if blank_run <= 2:
                collapsed.append(line)
        else:
            blank_run = 0
            collapsed.append(line)

    return "\n".join(collapsed).rstrip() + "\n"
