from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".trellis" / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import workflow_phase  # noqa: E402


class WorkflowPhaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        trellis = self.root / ".trellis"
        (trellis / "workflow" / "steps").mkdir(parents=True)
        (trellis / "workflow.md").write_text(
            """# Workflow

## Phase Index

Phase 1: Plan

[workflow-state:no_task]
No active task.
[/workflow-state:no_task]

## Phase 1: Plan
""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_phase_index_stays_in_workflow_entry_and_strips_state_blocks(self) -> None:
        with patch.object(workflow_phase, "get_repo_root", return_value=self.root):
            content = workflow_phase.get_phase_index()

        self.assertIn("## Phase Index", content)
        self.assertIn("Phase 1: Plan", content)
        self.assertNotIn("workflow-state", content)

    def test_step_is_loaded_from_canonical_step_file(self) -> None:
        (self.root / ".trellis/workflow/steps/2.1.md").write_text(
            "# 2.1 Implement\n\nImplement details.\n",
            encoding="utf-8",
        )

        with patch.object(workflow_phase, "get_repo_root", return_value=self.root):
            content = workflow_phase.get_step("2.1")

        self.assertEqual(content, "# 2.1 Implement\n\nImplement details.\n")

    def test_platform_filter_applies_to_step_file(self) -> None:
        (self.root / ".trellis/workflow/steps/2.1.md").write_text(
            """# 2.1 Implement

[Claude Code]
Claude instructions.
[/Claude Code]

[Cursor]
Cursor instructions.
[/Cursor]
""",
            encoding="utf-8",
        )

        with patch.object(workflow_phase, "get_repo_root", return_value=self.root):
            content = workflow_phase.filter_platform(workflow_phase.get_step("2.1"), "Claude Code")

        self.assertIn("Claude instructions.", content)
        self.assertNotIn("Cursor instructions.", content)

    def test_missing_or_invalid_step_returns_empty_content(self) -> None:
        with patch.object(workflow_phase, "get_repo_root", return_value=self.root):
            self.assertEqual(workflow_phase.get_step("9.9"), "")
            self.assertEqual(workflow_phase.get_step("../workflow.md"), "")

    def test_cli_reports_missing_step_explicitly(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "get_context.py"),
                "--mode",
                "phase",
                "--step",
                "9.9",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("Step not found: 9.9", completed.stderr)


if __name__ == "__main__":
    unittest.main()
