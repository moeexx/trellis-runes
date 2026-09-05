"""Small, deterministic evidence artifacts used by Central Gate rules."""

from __future__ import annotations

import json
import subprocess
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
