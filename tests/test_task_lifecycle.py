from __future__ import annotations

import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".trellis" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import task  # noqa: E402
from common import task_store  # noqa: E402
from common import task_context  # noqa: E402
from common import gate  # noqa: E402


class TaskLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workflow = self.root / ".trellis"
        self.task_dir = self.workflow / "tasks" / "01-01-example"
        self.task_dir.mkdir(parents=True)
        (self.workflow / "gates.yaml").write_text(
            (ROOT / ".trellis" / "gates.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.context_key = patch.object(gate, "resolve_context_key", return_value=None)
        self.context_key.start()
        self.addCleanup(self.context_key.stop)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_task(self, status: str = "planning") -> Path:
        task_json = self.task_dir / "task.json"
        task_json.write_text(
            json.dumps({
                "id": "example",
                "status": status,
                "branch": None,
                "base_branch": None,
                "children": [],
            }),
            encoding="utf-8",
        )
        return task_json

    def write_prd(self) -> None:
        (self.task_dir / "prd.md").write_text("# Plan\n", encoding="utf-8")

    def start_args(self) -> Namespace:
        return Namespace(dir=str(self.task_dir))

    def archive_args(self) -> Namespace:
        return Namespace(name=str(self.task_dir), no_commit=True)

    def create_args(self) -> Namespace:
        return Namespace(
            title="New task",
            description="Create lifecycle test task",
            slug="new-task",
            assignee="runes",
            priority="P2",
            parent=None,
            package=None,
            base_branch=None,
            meta=None,
            no_start=True,
            force=False,
        )

    def write_activation(self, root: Path, entry: str) -> None:
        marker = root / ".trellis" / ".runtime" / "workflow-activations" / "test-session.json"
        marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({"enabled": True, "entry": entry}), encoding="utf-8")

    def test_start_gate_failure_leaves_planning_status(self) -> None:
        task_json = self.write_task()
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            task, "resolve_task_dir", return_value=self.task_dir
        ):
            result = task.cmd_start(self.start_args())
        self.assertNotEqual(result, 0)
        data = json.loads(task_json.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "planning")

    def test_identified_session_requires_activation_before_start(self) -> None:
        task_json = self.write_task()
        self.write_prd()
        with patch.object(gate, "resolve_context_key", return_value="test-session"), patch.object(
            task, "get_repo_root", return_value=self.root
        ), patch.object(task, "resolve_task_dir", return_value=self.task_dir):
            result = task.cmd_start(self.start_args())
        self.assertNotEqual(result, 0)
        self.assertEqual(json.loads(task_json.read_text(encoding="utf-8"))["status"], "planning")

        self.write_activation(self.root, "resume")
        with patch.object(gate, "resolve_context_key", return_value="test-session"), patch.object(
            task, "get_repo_root", return_value=self.root
        ), patch.object(task, "resolve_task_dir", return_value=self.task_dir), patch.object(
            task, "resolve_context_key", return_value=None
        ), patch.object(task, "run_task_hooks"):
            result = task.cmd_start(self.start_args())
        self.assertEqual(result, 0)

    def test_identified_session_requires_start_activation_before_create(self) -> None:
        create_root = self.root / "create-root"
        create_workflow = create_root / ".trellis"
        create_workflow.mkdir(parents=True)
        (create_workflow / "gates.yaml").write_text(
            (ROOT / ".trellis" / "gates.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )

        with patch.object(gate, "resolve_context_key", return_value="test-session"), patch.object(
            task_store, "get_repo_root", return_value=create_root
        ):
            denied = task_store.cmd_create(self.create_args())
        self.assertNotEqual(denied, 0)
        self.assertFalse((create_workflow / "tasks").exists())

        self.write_activation(create_root, "start")
        with patch.object(gate, "resolve_context_key", return_value="test-session"), patch.object(
            task_store, "get_repo_root", return_value=create_root
        ), patch.object(task_store, "resolve_default_branch", return_value="main"):
            created = task_store.cmd_create(self.create_args())
        self.assertEqual(created, 0)
        task_json = next((create_workflow / "tasks").glob("*-new-task/task.json"))
        self.assertTrue(task_json.is_file())
        gate_rows = [
            json.loads(line)
            for line in (task_json.parent / "gate-result.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(gate_rows[-1]["gate_id"], "task_create")
        self.assertEqual(gate_rows[-1]["result"], "pass")

    def test_valid_start_transitions_to_in_progress(self) -> None:
        task_json = self.write_task()
        self.write_prd()
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            task, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task, "resolve_context_key", return_value=None), patch.object(
            task, "run_task_hooks"
        ):
            result = task.cmd_start(self.start_args())
        self.assertEqual(result, 0)
        data = json.loads(task_json.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "in_progress")
        events = [
            json.loads(line)
            for line in (self.task_dir / "lifecycle-events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(events[-1]["kind"], "phase-transition")
        self.assertEqual(events[-1]["from"], "planning")
        self.assertEqual(events[-1]["to"], "in_progress")

    def test_start_audit_write_failure_does_not_block_transition(self) -> None:
        task_json = self.write_task()
        self.write_prd()
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            task, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task, "resolve_context_key", return_value=None), patch.object(
            task, "run_task_hooks"
        ), patch.object(task.audit, "record_lifecycle_event", return_value=False):
            result = task.cmd_start(self.start_args())
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(task_json.read_text(encoding="utf-8"))["status"], "in_progress")

    def test_invalid_context_start_leaves_planning_status(self) -> None:
        task_json = self.write_task()
        self.write_prd()
        (self.task_dir / "implement.jsonl").write_text("{broken\n", encoding="utf-8")
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            task, "resolve_task_dir", return_value=self.task_dir
        ):
            result = task.cmd_start(self.start_args())
        self.assertNotEqual(result, 0)
        self.assertEqual(json.loads(task_json.read_text(encoding="utf-8"))["status"], "planning")

    def test_start_write_failure_returns_nonzero(self) -> None:
        task_json = self.write_task()
        self.write_prd()
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            task, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task, "write_json", return_value=False):
            result = task.cmd_start(self.start_args())
        self.assertNotEqual(result, 0)
        self.assertEqual(json.loads(task_json.read_text(encoding="utf-8"))["status"], "planning")

    def test_validate_uses_central_context_gate(self) -> None:
        self.write_task()
        self.write_prd()
        (self.task_dir / "check.jsonl").write_text("{broken\n", encoding="utf-8")
        args = Namespace(dir=str(self.task_dir))
        with patch.object(task_context, "get_repo_root", return_value=self.root), patch.object(
            task_context, "resolve_task_dir", return_value=self.task_dir
        ):
            result = task_context.cmd_validate(args)
        self.assertNotEqual(result, 0)

    def test_archive_gate_failure_leaves_task_in_place(self) -> None:
        task_json = self.write_task(status="planning")
        self.write_prd()
        with patch.object(task_store, "get_repo_root", return_value=self.root), patch.object(
            task_store, "resolve_task_dir", return_value=self.task_dir
        ):
            result = task_store.cmd_archive(self.archive_args())
        self.assertNotEqual(result, 0)
        self.assertTrue(self.task_dir.is_dir())
        data = json.loads(task_json.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "planning")

    def test_valid_archive_completes_and_moves_task(self) -> None:
        self.write_task(status="in_progress")
        self.write_prd()
        with patch.object(task_store, "get_repo_root", return_value=self.root), patch.object(
            task_store, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task_store, "run_task_hooks"):
            result = task_store.cmd_archive(self.archive_args())
        self.assertEqual(result, 0)
        self.assertFalse(self.task_dir.exists())
        archived = list((self.workflow / "tasks" / "archive").glob("*/01-01-example/task.json"))
        self.assertEqual(len(archived), 1)
        data = json.loads(archived[0].read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "completed")
        events = [
            json.loads(line)
            for line in (archived[0].parent / "lifecycle-events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(events[-1]["kind"], "phase-transition")
        self.assertEqual(events[-1]["from"], "in_progress")
        self.assertEqual(events[-1]["to"], "completed")

    def test_rollback_and_human_gate_events(self) -> None:
        self.write_task(status="in_progress")
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            task, "resolve_task_dir", return_value=self.task_dir
        ):
            rollback_result = task.cmd_rollback(
                Namespace(dir=str(self.task_dir), rollback_action="record", phase="check")
            )
            reset_result = task.cmd_rollback(
                Namespace(
                    dir=str(self.task_dir),
                    rollback_action="reset",
                    intervention="reviewed the failed check manually",
                )
            )
            audit_result = task.cmd_audit(
                Namespace(
                    dir=str(self.task_dir),
                    audit_action="human-gate",
                    kind="commit-confirmed",
                    detail="developer approved commit plan",
                )
            )
        self.assertEqual(rollback_result, 0)
        self.assertEqual(reset_result, 0)
        self.assertEqual(audit_result, 0)
        events = [
            json.loads(line)
            for line in (self.task_dir / "lifecycle-events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(events[0]["kind"], "rollback")
        self.assertEqual(events[0]["count"], 1)
        self.assertEqual(events[1]["kind"], "rollback")
        self.assertEqual(events[1]["action"], "reset")
        self.assertEqual(events[2]["kind"], "human-gate")
        self.assertEqual(events[2]["gate_kind"], "commit-confirmed")

    def test_human_gate_rejects_invalid_input_and_write_failure(self) -> None:
        self.write_task(status="in_progress")
        base = {
            "dir": str(self.task_dir),
            "audit_action": "human-gate",
            "kind": "unknown",
            "detail": "detail",
        }
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            task, "resolve_task_dir", return_value=self.task_dir
        ):
            self.assertNotEqual(task.cmd_audit(Namespace(**base)), 0)
            base["kind"] = "prd-confirmed"
            base["detail"] = " "
            self.assertNotEqual(task.cmd_audit(Namespace(**base)), 0)
            base["detail"] = "approved"
            with patch.object(task.audit, "record_lifecycle_event", return_value=False):
                self.assertNotEqual(task.cmd_audit(Namespace(**base)), 0)

    def test_audit_cli_parses_human_gate_arguments(self) -> None:
        with patch.object(task, "cmd_audit", return_value=0) as cmd_audit, patch.object(
            sys,
            "argv",
            [
                "task.py",
                "audit",
                "example",
                "human-gate",
                "--kind",
                "prd-confirmed",
                "--detail",
                "developer approved PRD",
            ],
        ):
            self.assertEqual(task.main(), 0)
        self.assertEqual(cmd_audit.call_args.args[0].kind, "prd-confirmed")

    def test_archive_child_write_failure_can_be_retried(self) -> None:
        parent_json = self.write_task(status="in_progress")
        child_dir = self.workflow / "tasks" / "01-02-child"
        child_dir.mkdir()
        child_json = child_dir / "task.json"
        child_json.write_text(
            json.dumps({"status": "in_progress", "parent": self.task_dir.name}),
            encoding="utf-8",
        )
        parent_json.write_text(
            json.dumps({
                "id": "example",
                "status": "in_progress",
                "branch": None,
                "base_branch": None,
                "children": [child_dir.name],
            }),
            encoding="utf-8",
        )

        real_write_json = task_store.write_json
        failed_once = False

        def fail_child_once(path: Path, data: dict) -> bool:
            nonlocal failed_once
            if path == child_json and not failed_once:
                failed_once = True
                return False
            return real_write_json(path, data)

        with patch.object(task_store, "get_repo_root", return_value=self.root), patch.object(
            task_store, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task_store, "write_json", side_effect=fail_child_once), patch.object(
            task_store, "run_task_hooks"
        ):
            first = task_store.cmd_archive(self.archive_args())

        self.assertNotEqual(first, 0)
        self.assertTrue(self.task_dir.is_dir())
        self.assertEqual(json.loads(parent_json.read_text())["status"], "in_progress")

        with patch.object(task_store, "get_repo_root", return_value=self.root), patch.object(
            task_store, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task_store, "run_task_hooks"):
            second = task_store.cmd_archive(self.archive_args())

        self.assertEqual(second, 0)
        self.assertFalse(self.task_dir.exists())
        self.assertIsNone(json.loads(child_json.read_text())["parent"])

    def test_archive_move_failure_rolls_back_status_and_keeps_session(self) -> None:
        task_json = self.write_task(status="in_progress")
        self.write_prd()
        sessions = self.workflow / ".runtime" / "sessions"
        sessions.mkdir(parents=True)
        session_file = sessions / "session.json"
        session_file.write_text(
            json.dumps({"current_task": str(self.task_dir)}), encoding="utf-8"
        )

        with patch.object(task_store, "get_repo_root", return_value=self.root), patch.object(
            task_store, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task_store, "archive_task_complete", return_value={}), patch.object(
            task_store, "run_task_hooks"
        ):
            result = task_store.cmd_archive(self.archive_args())

        self.assertNotEqual(result, 0)
        self.assertTrue(self.task_dir.is_dir())
        self.assertEqual(
            json.loads(task_json.read_text(encoding="utf-8"))["status"],
            "in_progress",
        )
        self.assertTrue(session_file.exists())

        with patch.object(task_store, "get_repo_root", return_value=self.root), patch.object(
            task_store, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task_store, "run_task_hooks"):
            retry = task_store.cmd_archive(self.archive_args())

        self.assertEqual(retry, 0)
        self.assertFalse(self.task_dir.exists())
        self.assertFalse(session_file.exists())

    def test_lifecycle_entrypoints_call_canonical_gate(self) -> None:
        self.assertIn("task_create", inspect.getsource(task_store.cmd_create))
        self.assertIn("gate.require", inspect.getsource(task.cmd_start))
        self.assertIn("gate.require", inspect.getsource(task_store.cmd_archive))

    def test_removed_bypass_flags_are_not_accepted(self) -> None:
        for command, flag in (
            ("start", "--allow-empty-context"),
            ("archive", "--skip-branch-validation"),
        ):
            completed = subprocess.run(
                [sys.executable, str(ROOT / ".trellis/scripts/task.py"), command, flag],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(completed.returncode, 0)

    def test_baseline_cli_does_not_shadow_top_level_command(self) -> None:
        self.write_task()
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            sys, "argv", ["task.py", "baseline", str(self.task_dir), "snapshot", "--phase", "before", "--command", "smoke=true"]
        ):
            result = task.main()
        self.assertEqual(result, 0)
        self.assertTrue((self.task_dir / "baseline/before.json").is_file())

    def test_idempotent_start_does_not_refreeze_evidence_hash(self) -> None:
        task_json = self.write_task(status="in_progress")
        self.write_prd()
        plan = self.task_dir / "test-plan-unit.md"
        plan.write_text("old", encoding="utf-8")
        data = json.loads(task_json.read_text(encoding="utf-8"))
        data["meta"] = {"evidence_gates_version": "1", "evidence_test_level": "unit", "test_plan_sha256": {"test-plan-unit.md": "frozen"}}
        task_json.write_text(json.dumps(data), encoding="utf-8")
        with patch.object(task, "get_repo_root", return_value=self.root), patch.object(
            task, "resolve_task_dir", return_value=self.task_dir
        ), patch.object(task, "resolve_context_key", return_value=None), patch.object(task, "run_task_hooks"):
            self.assertEqual(task.cmd_start(self.start_args()), 0)
        self.assertEqual(json.loads(task_json.read_text(encoding="utf-8"))["meta"]["test_plan_sha256"]["test-plan-unit.md"], "frozen")

    def test_default_prd_uses_documented_six_section_contract(self) -> None:
        content = task_store._default_prd_content("Example", "Goal")
        for heading in (
            "## Overview",
            "## User Stories & AC",
            "## NFR",
            "## Constraints & Boundaries",
            "## Data Model",
            "## Open Questions",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, content)


if __name__ == "__main__":
    unittest.main()
