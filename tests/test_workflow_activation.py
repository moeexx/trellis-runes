from __future__ import annotations

import json
import os
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

from common import workflow_activation  # noqa: E402


class WorkflowActivationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        trellis = self.root / ".trellis"
        trellis.mkdir()
        os.symlink(SCRIPTS, trellis / "scripts", target_is_directory=True)
        (trellis / "workflow.md").write_text(
            "[workflow-state:no_task]\nNo active task.\n[/workflow-state:no_task]\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def activation(self, prompt: str, session_id: str = "one"):
        with patch.dict(os.environ, {"TRELLIS_CONTEXT_ID": ""}):
            return workflow_activation.resolve_workflow_activation(
                self.root,
                prompt,
                {"session_id": session_id},
                "claude",
            )

    def run_hook(self, platform: str, prompt: str, session_id: str = "one") -> str:
        env = os.environ.copy()
        env.pop("TRELLIS_CONTEXT_ID", None)
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / f".{platform}" / "hooks" / "inject-workflow-state.py"),
            ],
            cwd=self.root,
            input=json.dumps(
                {
                    "cwd": str(self.root),
                    "prompt": prompt,
                    "session_id": session_id,
                }
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def hook_context(self, platform: str, output: str) -> str:
        if platform == "kiro":
            return output
        return json.loads(output)["hookSpecificOutput"]["additionalContext"]

    def test_entry_prefix_requires_the_first_character(self) -> None:
        self.assertEqual(
            workflow_activation.entry_for_prompt("创建任务实现登录"), "start"
        )
        self.assertEqual(
            workflow_activation.entry_for_prompt("恢复任务继续检查"), "resume"
        )
        self.assertIsNone(workflow_activation.entry_for_prompt(" 创建任务实现登录"))
        self.assertIsNone(workflow_activation.entry_for_prompt("请创建任务实现登录"))
        self.assertIsNone(workflow_activation.entry_for_prompt("开始"))
        self.assertIsNone(workflow_activation.entry_for_prompt(None))

    def test_activation_is_session_scoped_and_corrupt_marker_fails_closed(self) -> None:
        first = self.activation("创建任务实现登录", "first")
        self.assertTrue(first.enabled)
        self.assertEqual(first.entry, "start")

        marker = (
            self.root
            / ".trellis"
            / ".runtime"
            / "workflow-activations"
            / "claude_first.json"
        )
        self.assertEqual(
            json.loads(marker.read_text(encoding="utf-8")),
            {
                "enabled": True,
                "entry": "start",
            },
        )
        self.assertTrue(self.activation("继续实现", "first").enabled)
        self.assertFalse(self.activation("继续实现", "second").enabled)

        marker.write_text("{broken", encoding="utf-8")
        self.assertFalse(self.activation("继续实现", "first").enabled)

        marker.write_text('{"enabled": true}', encoding="utf-8")
        self.assertFalse(self.activation("继续实现", "first").enabled)

    def test_activation_entry_reads_only_valid_marker_schema(self) -> None:
        runtime = self.root / ".trellis" / ".runtime" / "workflow-activations"
        runtime.mkdir(parents=True)
        marker = runtime / "claude_entry.json"

        marker.write_text('{"enabled": true, "entry": "start"}', encoding="utf-8")
        self.assertEqual(
            workflow_activation.activation_entry(self.root, "claude_entry"), "start"
        )

        marker.write_text('{"enabled": true, "entry": "invalid"}', encoding="utf-8")
        self.assertIsNone(
            workflow_activation.activation_entry(self.root, "claude_entry")
        )

    def test_resume_reactivates_the_same_session(self) -> None:
        result = self.activation("恢复任务继续", "resume")
        self.assertTrue(result.enabled)
        self.assertEqual(result.entry, "resume")
        self.assertIn("恢复任务", workflow_activation.build_workflow_entry("resume"))

    def test_trigger_without_session_identity_returns_a_visible_error(self) -> None:
        with patch.object(
            workflow_activation, "resolve_context_key", return_value=None
        ):
            result = workflow_activation.resolve_workflow_activation(
                self.root,
                "创建任务实现登录",
                {},
                "claude",
            )
        self.assertFalse(result.enabled)
        self.assertEqual(result.entry, "start")
        self.assertIn("稳定的会话标识", result.error or "")

    def test_all_platform_hooks_require_activation_and_keep_session_scope(self) -> None:
        for platform in ("claude", "codex", "kiro", "qoder"):
            with self.subTest(platform=platform):
                self.assertEqual(self.run_hook(platform, "解释这个文件", "plain"), "")

                started = self.hook_context(
                    platform,
                    self.run_hook(platform, "创建任务实现登录", "active"),
                )
                self.assertIn("<trellis-workflow-entry>", started)
                self.assertIn("创建任务", started)
                self.assertIn("<workflow-state>", started)
                if platform == "codex":
                    self.assertIn("<codex-mode>", started)

                follow_up = self.hook_context(
                    platform,
                    self.run_hook(platform, "继续实现", "active"),
                )
                self.assertNotIn("<trellis-workflow-entry>", follow_up)
                self.assertIn("<workflow-state>", follow_up)
                self.assertEqual(self.run_hook(platform, "继续实现", "other"), "")

    def test_resume_entry_and_skip_keyword_behavior(self) -> None:
        for platform in ("claude", "codex", "kiro", "qoder"):
            with self.subTest(platform=platform):
                resumed = self.hook_context(
                    platform,
                    self.run_hook(platform, "恢复任务继续", "resume"),
                )
                self.assertIn("恢复任务", resumed)
                self.assertIn("<workflow-state>", resumed)

                started_with_skip = self.hook_context(
                    platform,
                    self.run_hook(platform, "创建任务 no-trellis", "skip"),
                )
                self.assertIn("<trellis-workflow-entry>", started_with_skip)
                self.assertEqual(self.run_hook(platform, "no-trellis", "skip"), "")
                self.assertIn(
                    "<workflow-state>",
                    self.hook_context(
                        platform, self.run_hook(platform, "继续", "skip")
                    ),
                )

    def test_platform_configs_have_no_automatic_workflow_entry(self) -> None:
        for config_path in (
            ROOT / ".claude" / "settings.json",
            ROOT / ".qoder" / "settings.json",
        ):
            config = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertNotIn("SessionStart", config["hooks"])

        kiro = json.loads(
            (ROOT / ".kiro" / "agents" / "trellis.json").read_text(encoding="utf-8")
        )
        self.assertNotIn("resources", kiro)
        self.assertNotIn("agentSpawn", kiro["hooks"])
        self.assertIn("创建任务", kiro["prompt"])

        instructions = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn(
            "仅当用户消息首字符以 `创建任务` 或 `恢复任务` 开头", instructions
        )


if __name__ == "__main__":
    unittest.main()
