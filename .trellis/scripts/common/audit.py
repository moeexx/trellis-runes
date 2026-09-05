"""Best-effort append-only audit records for task lifecycle operations."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUDIT_SCHEMA = 1
GATE_RESULT_FILE = "gate-result.jsonl"
LIFECYCLE_EVENTS_FILE = "lifecycle-events.jsonl"


def now() -> str:
    """Return a compact UTC timestamp shared by audit event writers."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_event(task_dir: Path, filename: str, event: dict[str, Any]) -> bool:
    """Append one JSON event, warning rather than raising on I/O failure."""
    path = task_dir / filename
    try:
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError) as exc:
        print(f"Warning: failed to append audit event to {path}: {exc}", file=sys.stderr)
        return False
    return True


def record_gate_result(task_dir: Path, gate_id: str, failures: tuple[Any, ...]) -> bool:
    """Project one completed Central Gate evaluation into its task ledger."""
    return append_event(
        task_dir,
        GATE_RESULT_FILE,
        {
            "schema": AUDIT_SCHEMA,
            "ts": now(),
            "kind": "gate-result",
            "task_id": task_dir.name,
            "gate_id": gate_id,
            "result": "pass" if not failures else "fail",
            "failed_rules": [failure.rule for failure in failures],
        },
    )
