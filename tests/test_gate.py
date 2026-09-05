from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / ".trellis" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import gate  # noqa: E402
from common.gate import GateContext  # noqa: E402


POLICY = Path(__file__).resolve().parents[1] / ".trellis" / "gates.yaml"


class GateEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workflow = self.root / ".trellis"
        self.task = self.workflow / "tasks" / "01-01-example"
        self.task.mkdir(parents=True)
        (self.workflow / "gates.yaml").write_text(
            POLICY.read_text(encoding="utf-8"), encoding="utf-8"
        )
        self.context_key = patch.object(gate, "resolve_context_key", return_value=None)
        self.context_key.start()
        self.addCleanup(self.context_key.stop)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_task(self, status: str = "planning") -> None:
        (self.task / "task.json").write_text(
            json.dumps({"status": status, "branch": None, "base_branch": None}),
            encoding="utf-8",
        )

    def write_manifest(self, name: str, target: str = "context.md") -> None:
        (self.root / target).write_text("context", encoding="utf-8")
        (self.task / name).write_text(
            json.dumps({"file": target, "reason": "test"}) + "\n",
            encoding="utf-8",
        )

    def context(self, **kwargs: object) -> GateContext:
        return GateContext(repo_root=self.root, task_dir=self.task, **kwargs)

    def test_unknown_gate_fails_closed(self) -> None:
        self.write_task()
        result = gate.evaluate("does_not_exist", self.context())
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "unknown_gate")

    def test_pass(self) -> None:
        self.write_task()
        (self.task / "prd.md").write_text("# Plan\n", encoding="utf-8")
        self.write_manifest("implement.jsonl")
        self.write_manifest("check.jsonl", "check.md")
        result = gate.evaluate("task_start", self.context())
        self.assertTrue(result.ok)

    def write_activation(self, entry: str) -> None:
        marker = self.workflow / ".runtime" / "workflow-activations" / "test-session.json"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps({"enabled": True, "entry": entry}), encoding="utf-8"
        )

    def test_session_activation_rules_enforce_entries_and_keep_degraded_mode(self) -> None:
        self.write_task()
        (self.task / "prd.md").write_text("# Plan\n", encoding="utf-8")

        # No stable identity is the documented direct-CLI compatibility mode.
        self.assertTrue(gate.evaluate("task_create", self.context()).ok)
        self.assertTrue(gate.evaluate("task_start", self.context()).ok)

        with patch.object(gate, "resolve_context_key", return_value="test-session"):
            create_denied = gate.evaluate("task_create", self.context())
            start_denied = gate.evaluate("task_start", self.context())
        self.assertEqual(create_denied.failures[-1].code, "workflow_not_started")
        self.assertEqual(start_denied.failures[-1].code, "workflow_not_activated")

        self.write_activation("resume")
        with patch.object(gate, "resolve_context_key", return_value="test-session"):
            self.assertEqual(
                gate.evaluate("task_create", self.context()).failures[-1].code,
                "workflow_not_started",
            )
            self.assertTrue(gate.evaluate("task_start", self.context()).ok)

        self.write_activation("start")
        with patch.object(gate, "resolve_context_key", return_value="test-session"):
            self.assertTrue(gate.evaluate("task_create", self.context()).ok)
            self.assertTrue(gate.evaluate("task_start", self.context()).ok)

    def test_single_failure(self) -> None:
        self.write_task()
        result = gate.evaluate("task_start", self.context())
        self.assertFalse(result.ok)
        self.assertEqual([failure.rule for failure in result.failures], [
            "planning_artifacts_ready",
        ])

    def test_multiple_failures(self) -> None:
        self.write_task()
        (self.task / "implement.jsonl").write_text("", encoding="utf-8")
        (self.task / "check.jsonl").write_text("", encoding="utf-8")
        result = gate.evaluate("task_start", self.context())
        self.assertFalse(result.ok)
        self.assertEqual(
            {failure.rule for failure in result.failures},
            {"planning_artifacts_ready", "context_ready"},
        )

    def test_context_gate_reports_failures_from_both_manifests(self) -> None:
        self.write_task()
        (self.task / "implement.jsonl").write_text("{broken\n", encoding="utf-8")
        (self.task / "check.jsonl").write_text(
            json.dumps({"file": "missing.md"}) + "\n", encoding="utf-8"
        )
        result = gate.evaluate("context_validate", self.context())
        self.assertEqual(
            [failure.code for failure in result.failures],
            ["invalid_manifest_json", "context_target_missing"],
        )

    def test_task_json_failure_includes_repair_hint(self) -> None:
        (self.task / "task.json").write_text("{broken\n", encoding="utf-8")
        result = gate.evaluate("task_archive", self.context())
        self.assertFalse(result.ok)
        failure = result.failures[0]
        self.assertEqual(failure.code, "task_json_invalid")
        self.assertIn("json.tool", failure.details["repair"])

    def test_transition_idempotence_is_policy_driven(self) -> None:
        self.write_task(status="in_progress")
        (self.task / "prd.md").write_text("# Plan\n", encoding="utf-8")
        self.write_manifest("implement.jsonl")
        self.write_manifest("check.jsonl", "check.md")
        result = gate.evaluate("task_start", self.context())
        self.assertTrue(result.ok)

        policy = self.workflow / "non_idempotent.yaml"
        policy.write_text(
            "version: 1\n\ngates:\n"
            "  task_start:\n"
            "    transition:\n"
            "      from: planning\n"
            "      to: in_progress\n"
            "    require:\n"
            "      - task_json_ready\n",
            encoding="utf-8",
        )
        result = gate.evaluate(
            "task_start", self.context(policy_path=policy)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "invalid_status_transition")

    def test_malformed_policy_fails_closed(self) -> None:
        self.write_task()
        policy = self.workflow / "broken.yaml"
        policy.write_text("version: 2\n", encoding="utf-8")
        result = gate.evaluate(
            "task_start", self.context(policy_path=policy)
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "malformed_policy")

    def test_policy_requires_non_empty_require_list(self) -> None:
        self.write_task()
        policy = self.workflow / "empty-require.yaml"
        policy.write_text(
            "version: 1\n\ngates:\n  task_start:\n    require:\n",
            encoding="utf-8",
        )
        result = gate.evaluate("task_start", self.context(policy_path=policy))
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "malformed_policy")

    def test_unsupported_policy_yaml_fails_closed(self) -> None:
        self.write_task()
        policy = self.workflow / "flow-policy.yaml"
        policy.write_text(
            "version: 1\n\ngates:\n  task_start:\n"
            "    require: [task_json_ready]\n",
            encoding="utf-8",
        )
        result = gate.evaluate("task_start", self.context(policy_path=policy))
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "malformed_policy")

    def test_unknown_policy_line_fails_closed(self) -> None:
        self.write_task()
        policy = self.workflow / "unknown-line.yaml"
        policy.write_text(
            "version: 1\n\ngates:\n  task_start:\n"
            "    require:\n"
            "      - task_json_ready\n"
            "    unexpected syntax\n",
            encoding="utf-8",
        )
        result = gate.evaluate("task_start", self.context(policy_path=policy))
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "malformed_policy")

    def test_invalid_idempotent_value_fails_closed(self) -> None:
        self.write_task()
        policy = self.workflow / "bad-idempotent.yaml"
        policy.write_text(
            "version: 1\n\ngates:\n  task_start:\n"
            "    transition:\n"
            "      from: planning\n"
            "      to: in_progress\n"
            "      idempotent: yes\n"
            "    require:\n"
            "      - task_json_ready\n",
            encoding="utf-8",
        )
        result = gate.evaluate("task_start", self.context(policy_path=policy))
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "malformed_policy")

    def test_unknown_rule_fails_closed(self) -> None:
        self.write_task()
        policy = self.workflow / "unknown-rule.yaml"
        policy.write_text(
            "version: 1\n\ngates:\n  task_start:\n    require:\n      - no_such_rule\n",
            encoding="utf-8",
        )
        result = gate.evaluate("task_start", self.context(policy_path=policy))
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "unknown_rule")

    def test_missing_required_context_fails(self) -> None:
        self.write_task()
        (self.task / "prd.md").write_text("# Plan\n", encoding="utf-8")
        (self.task / "implement.jsonl").write_text(
            json.dumps({"file": "missing.md"}) + "\n", encoding="utf-8"
        )
        result = gate.evaluate("task_start", self.context())
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "context_target_missing")

    def test_invalid_jsonl_fails_closed(self) -> None:
        self.write_task()
        (self.task / "prd.md").write_text("# Plan\n", encoding="utf-8")
        (self.task / "implement.jsonl").write_text("{broken\n", encoding="utf-8")
        result = gate.evaluate("task_start", self.context())
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "invalid_manifest_json")

    def test_legacy_example_row_fails_closed(self) -> None:
        self.write_task()
        (self.task / "prd.md").write_text("# Plan\n", encoding="utf-8")
        (self.task / "implement.jsonl").write_text(
            json.dumps({"_example": "replace me"}) + "\n", encoding="utf-8"
        )
        result = gate.evaluate("task_start", self.context())
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "placeholder_manifest_row")

    def test_archive_branch_metadata_failure(self) -> None:
        self.write_task(status="in_progress")
        (self.task / "task.json").write_text(
            json.dumps({"status": "in_progress", "branch": "main", "base_branch": "main"}),
            encoding="utf-8",
        )
        result = gate.evaluate("task_archive", self.context())
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "branch_equals_base_branch")

    def test_archive_destination_collision_fails_closed(self) -> None:
        self.write_task(status="in_progress")
        from common.task_utils import archive_destination_for

        archive_destination_for(self.task).mkdir(parents=True)
        result = gate.evaluate("task_archive", self.context())
        self.assertFalse(result.ok)
        self.assertEqual(result.failures[0].code, "archive_destination_exists")

    def test_archive_warns_for_missing_local_branch(self) -> None:
        self.write_task(status="in_progress")
        (self.task / "task.json").write_text(
            json.dumps(
                {
                    "status": "in_progress",
                    "branch": "feature/missing",
                    "base_branch": "main",
                }
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with patch.object(gate, "branch_exists_locally", return_value=False), patch(
            "common.gate.sys.stderr", stderr
        ):
            result = gate.evaluate("task_archive", self.context())
        self.assertTrue(result.ok)
        self.assertIn("no longer exists locally", stderr.getvalue())

    def test_evidence_task_requires_plans_unchanged_hash_and_clean_diff(self) -> None:
        self.write_task()
        (self.task / "task.json").write_text(json.dumps({"status": "planning", "meta": {"evidence_gates_version": "1", "evidence_test_level": "unit"}}), encoding="utf-8")
        (self.task / "prd.md").write_text("# Plan\n", encoding="utf-8")
        result = gate.evaluate("task_start", self.context())
        self.assertEqual(result.failures[-1].code, "missing_test_plan")
        plan = self.task / "test-plan-unit.md"
        plan.write_text("# unit\n", encoding="utf-8")
        self.assertTrue(gate.evaluate("task_start", self.context()).ok)
        data = json.loads((self.task / "task.json").read_text(encoding="utf-8"))
        data["status"] = "in_progress"
        data["meta"]["test_plan_sha256"] = {"test-plan-unit.md": "wrong"}
        (self.task / "task.json").write_text(json.dumps(data), encoding="utf-8")
        result = gate.evaluate("task_archive", self.context())
        self.assertIn("test_plan_hash_mismatch", [failure.code for failure in result.failures])


if __name__ == "__main__":
    unittest.main()
