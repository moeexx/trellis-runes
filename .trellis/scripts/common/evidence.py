"""Small, deterministic evidence artifacts used by Central Gate rules."""

from __future__ import annotations

import json
import subprocess
import re
from datetime import datetime, timezone
from pathlib import Path


BASELINE_SCHEMA = 1


class EvidenceError(ValueError):
    """An evidence artifact is absent, malformed, or incompatible."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _artifact(task_dir: Path, name: str) -> Path:
    return task_dir / "baseline" / f"{name}.json"


def _read_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{path.name} is unreadable") from exc
    if not isinstance(data, dict):
        raise EvidenceError(f"{path.name} must be a JSON object")
    return data


def parse_commands(values: list[str]) -> dict[str, str]:
    commands: dict[str, str] = {}
    for value in values:
        key, separator, command = value.partition("=")
        if not separator or not key.strip() or not command.strip() or key in commands:
            raise EvidenceError("--command must be unique id=command")
        commands[key.strip()] = command.strip()
    if not commands:
        raise EvidenceError("at least one --command id=command is required")
    return commands


def _failures(stdout: str, stderr: str, exit_code: int) -> list[str]:
    if exit_code == 0:
        return []
    lines = [
        line.strip()[:200]
        for line in f"{stdout}\n{stderr}".splitlines()
        if "fail" in line.lower() or "error" in line.lower()
    ]
    return list(dict.fromkeys(lines)) or [f"exit_code={exit_code}"]


def snapshot(task_dir: Path, repo_root: Path, phase: str, commands: dict[str, str]) -> Path:
    if phase not in {"before", "after"}:
        raise EvidenceError("phase must be before or after")
    if phase == "after":
        before = read_snapshot(task_dir, "before")
        expected = command_contract(before)
        if commands and commands != expected:
            raise EvidenceError("after commands must exactly match before commands")
        commands = expected
    results: dict[str, dict[str, object]] = {}
    for key, command in commands.items():
        completed = subprocess.run(command, cwd=repo_root, shell=True, capture_output=True, text=True)
        results[key] = {
            "command": command,
            "exit_code": completed.returncode,
            "failures": _failures(completed.stdout, completed.stderr, completed.returncode),
        }
    payload = {"schema": BASELINE_SCHEMA, "phase": phase, "created_at": _now(), "commands": results}
    target = _artifact(task_dir, phase)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def command_contract(payload: dict) -> dict[str, str]:
    if payload.get("schema") != BASELINE_SCHEMA or not isinstance(payload.get("commands"), dict):
        raise EvidenceError("baseline schema is invalid")
    result: dict[str, str] = {}
    for key, item in payload["commands"].items():
        if not isinstance(key, str) or not isinstance(item, dict) or not isinstance(item.get("command"), str):
            raise EvidenceError("baseline command contract is invalid")
        if not isinstance(item.get("exit_code"), int) or not isinstance(item.get("failures"), list) or not all(isinstance(x, str) for x in item["failures"]):
            raise EvidenceError("baseline command result is invalid")
        result[key] = item["command"]
    if not result:
        raise EvidenceError("baseline has no commands")
    return result


def read_snapshot(task_dir: Path, phase: str) -> dict:
    payload = _read_object(_artifact(task_dir, phase))
    if payload.get("phase") != phase:
        raise EvidenceError(f"{phase}.json has the wrong phase")
    command_contract(payload)
    return payload


def diff(task_dir: Path) -> Path:
    before, after = read_snapshot(task_dir, "before"), read_snapshot(task_dir, "after")
    before_contract, after_contract = command_contract(before), command_contract(after)
    if before_contract != after_contract:
        raise EvidenceError("before and after command contracts differ")
    new: list[str] = []
    known: list[str] = []
    resolved: list[str] = []
    for key in before_contract:
        old = set(before["commands"][key]["failures"])
        current = set(after["commands"][key]["failures"])
        new.extend(f"[{key}] {item}" for item in sorted(current - old))
        known.extend(f"[{key}] {item}" for item in sorted(current & old))
        resolved.extend(f"[{key}] {item}" for item in sorted(old - current))
    payload = {"schema": BASELINE_SCHEMA, "new": new, "known": known, "resolved": resolved}
    target = _artifact(task_dir, "diff")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def read_clean_diff(task_dir: Path) -> dict:
    payload = _read_object(_artifact(task_dir, "diff"))
    if payload.get("schema") != BASELINE_SCHEMA or not all(isinstance(payload.get(key), list) and all(isinstance(value, str) for value in payload[key]) for key in ("new", "known", "resolved")):
        raise EvidenceError("diff.json schema is invalid")
    return payload


FINDING_SEVERITIES = {"P0", "P1", "P2"}
FINDING_STATUSES = {"fixed", "wont-fix", "accepted", "reopened"}


def _ledger_path(task_dir: Path) -> Path:
    return task_dir / "findings.jsonl"


def read_findings(task_dir: Path) -> list[dict]:
    path = _ledger_path(task_dir)
    if not path.is_file():
        raise EvidenceError("findings.jsonl is missing")
    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvidenceError(f"findings.jsonl line {number} is invalid") from exc
        if not isinstance(row, dict):
            raise EvidenceError(f"findings.jsonl line {number} is not an object")
        rows.append(row)
    return rows


def append_finding(task_dir: Path, kind: str, **values: str) -> None:
    events = [] if not _ledger_path(task_dir).exists() else read_findings(task_dir)
    if kind == "add":
        severity, title = values.get("severity", ""), values.get("title", "").strip()
        if severity not in FINDING_SEVERITIES or not title:
            raise EvidenceError("finding requires severity P0/P1/P2 and title")
        identifiers = [int(row["id"][2:]) for row in events if row.get("kind") == "finding" and isinstance(row.get("id"), str) and row["id"].startswith("F-") and row["id"][2:].isdigit()]
        event = {"kind": "finding", "id": f"F-{max(identifiers, default=0) + 1:03d}", "severity": severity, "title": title}
    elif kind == "none":
        event = {"kind": "none", "source": values.get("source", "check")}
    else:
        status, identifier, reason = values.get("status", ""), values.get("id", ""), values.get("reason", "").strip()
        if status not in FINDING_STATUSES or not identifier or (status in {"wont-fix", "accepted"} and not reason):
            raise EvidenceError("resolution requires id, valid status, and reason for wont-fix/accepted")
        event = {"kind": "status", "id": identifier, "status": status, "reason": reason}
    with _ledger_path(task_dir).open("a", encoding="utf-8") as output:
        output.write(json.dumps(event, ensure_ascii=False) + "\n")


def findings_closed(task_dir: Path) -> None:
    rows = read_findings(task_dir)
    findings: dict[str, str] = {}
    states: dict[str, str] = {}
    for row in rows:
        if row.get("kind") == "finding":
            identifier, severity = row.get("id"), row.get("severity")
            if not isinstance(identifier, str) or identifier in findings or severity not in FINDING_SEVERITIES:
                raise EvidenceError("findings ledger has invalid or duplicate finding")
            findings[identifier] = severity
            states[identifier] = "open"
        elif row.get("kind") == "status":
            identifier, status = row.get("id"), row.get("status")
            if identifier not in findings or status not in FINDING_STATUSES:
                raise EvidenceError("findings ledger has orphan or invalid status")
            states[identifier] = status
        elif row.get("kind") != "none":
            raise EvidenceError("findings ledger has unknown event")
    for identifier, severity in findings.items():
        permitted = {"fixed", "wont-fix"} if severity in {"P0", "P1"} else {"fixed", "wont-fix", "accepted"}
        if states[identifier] not in permitted:
            raise EvidenceError(f"{severity} finding {identifier} is unresolved")


def delivery_checklist_valid(task_dir: Path) -> None:
    path = task_dir / "delivery-checklist.json"
    payload = _read_object(path)
    criteria = payload.get("acceptance_criteria")
    if payload.get("schema") != 1 or not isinstance(criteria, list):
        raise EvidenceError("delivery checklist schema is invalid")
    prd = (task_dir / "prd.md").read_text(encoding="utf-8")
    expected = set(re.findall(r"\b(AC-\d+)\b", prd))
    actual: set[str] = set()
    for item in criteria:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item.get("status") != "passed" or not isinstance(item.get("evidence"), str) or not item["evidence"].strip():
            raise EvidenceError("delivery checklist has invalid acceptance criterion")
        actual.add(item["id"])
    if expected != actual:
        raise EvidenceError("delivery checklist AC ids do not match prd")
    for key, expected_path in (("baseline_diff", "baseline/diff.json"), ("findings", "findings.jsonl")):
        if payload.get(key) != expected_path or not (task_dir / expected_path).is_file():
            raise EvidenceError(f"delivery checklist lacks {key} evidence")


def rollback_record(task_dir: Path, phase: str) -> dict:
    task_json = task_dir / "task.json"
    data = _read_object(task_json)
    meta = data.setdefault("meta", {})
    if not isinstance(meta, dict):
        raise EvidenceError("task meta is invalid")
    current = meta.get("rollbacks")
    if not isinstance(current, dict) or current.get("phase") != phase:
        current = {"phase": phase, "count": 0, "events": []}
    current["count"] = int(current.get("count", 0)) + 1
    current.setdefault("events", []).append({"at": _now(), "action": "rollback", "phase": phase})
    meta["rollbacks"] = current
    task_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current


def rollback_reset(task_dir: Path, intervention: str) -> None:
    if not intervention.strip():
        raise EvidenceError("rollback reset requires human intervention detail")
    task_json = task_dir / "task.json"
    data = _read_object(task_json)
    meta = data.setdefault("meta", {})
    meta["rollbacks"] = {"phase": None, "count": 0, "events": [{"at": _now(), "action": "reset", "intervention": intervention.strip()}]}
    task_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rollback_not_tripped(task_dir: Path) -> None:
    data = _read_object(task_dir / "task.json")
    state = (data.get("meta") or {}).get("rollbacks")
    if isinstance(state, dict) and state.get("count", 0) >= 3:
        raise EvidenceError("rollback circuit breaker is tripped")
