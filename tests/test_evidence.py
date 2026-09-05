from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / ".trellis" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import evidence  # noqa: E402


class BaselineEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.task = self.root / ".trellis/tasks/example"
        self.task.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_diff_classifies_known_new_and_resolved_failures(self) -> None:
        command_file = self.root / "check.sh"
        command_file.write_text("printf 'ERROR old\\n'; exit 1\n", encoding="utf-8")
        evidence.snapshot(self.task, self.root, "before", {"test": "sh check.sh"})
        command_file.write_text("printf 'ERROR old\\nERROR new\\n'; exit 1\n", encoding="utf-8")
        evidence.snapshot(self.task, self.root, "after", {"test": "sh check.sh"})
        payload = json.loads(evidence.diff(self.task).read_text(encoding="utf-8"))
        self.assertEqual(payload["known"], ["[test] ERROR old"])
        self.assertEqual(payload["new"], ["[test] ERROR new"])
        self.assertEqual(payload["resolved"], [])

    def test_after_rejects_command_drift_and_invalid_artifacts_fail_closed(self) -> None:
        evidence.snapshot(self.task, self.root, "before", {"test": "true"})
        with self.assertRaises(evidence.EvidenceError):
            evidence.snapshot(self.task, self.root, "after", {"other": "true"})
        (self.task / "baseline/before.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(evidence.EvidenceError):
            evidence.diff(self.task)

    def test_findings_require_terminal_states_and_reject_corruption(self) -> None:
        evidence.append_finding(self.task, "add", severity="P0", title="broken")
        with self.assertRaises(evidence.EvidenceError):
            evidence.findings_closed(self.task)
        evidence.append_finding(self.task, "resolve", id="F-001", status="fixed", reason="test")
        evidence.append_finding(self.task, "add", severity="P2", title="note")
        evidence.append_finding(self.task, "resolve", id="F-002", status="accepted", reason="recorded")
        evidence.findings_closed(self.task)
        with (self.task / "findings.jsonl").open("a", encoding="utf-8") as output:
            output.write('{"kind":"status","id":"F-999","status":"fixed"}\n')
        with self.assertRaises(evidence.EvidenceError):
            evidence.findings_closed(self.task)

    def test_delivery_and_rollback_contracts(self) -> None:
        (self.task / "task.json").write_text('{"meta": {}}', encoding="utf-8")
        (self.task / "prd.md").write_text("- AC-1: works\n", encoding="utf-8")
        baseline = self.task / "baseline"
        baseline.mkdir()
        (baseline / "diff.json").write_text('{"schema":1,"new":[],"known":[],"resolved":[]}', encoding="utf-8")
        (self.task / "findings.jsonl").write_text('{"kind":"none","source":"check"}\n', encoding="utf-8")
        (self.task / "delivery-checklist.json").write_text(json.dumps({"schema": 1, "acceptance_criteria": [{"id": "AC-1", "status": "passed", "evidence": "test"}], "baseline_diff": "baseline/diff.json", "findings": "findings.jsonl"}), encoding="utf-8")
        evidence.delivery_checklist_valid(self.task)
        evidence.rollback_record(self.task, "2.2")
        evidence.rollback_record(self.task, "2.2")
        evidence.rollback_record(self.task, "2.2")
        with self.assertRaises(evidence.EvidenceError):
            evidence.rollback_not_tripped(self.task)
        evidence.rollback_reset(self.task, "developer reviewed the failure")
        evidence.rollback_not_tripped(self.task)


if __name__ == "__main__":
    unittest.main()
