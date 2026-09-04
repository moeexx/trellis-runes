from __future__ import annotations

import os
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".trellis" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common import session_start  # noqa: E402


class SessionStartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.trellis = self.root / ".trellis"
        (self.trellis / "spec" / "guides").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_normalize_windows_shell_path_handles_mounts_and_non_windows(self) -> None:
        with patch.object(session_start.sys, "platform", "win32"):
            self.assertEqual(session_start._normalize_windows_shell_path("/d/Work/a"), r"D:\Work\a")
            self.assertEqual(session_start._normalize_windows_shell_path("/cygdrive/c/Users/a"), r"C:\Users\a")
            self.assertEqual(session_start._normalize_windows_shell_path("/mnt/e/repo"), r"E:\repo")
            self.assertEqual(session_start._normalize_windows_shell_path(r"C:\repo"), r"C:\repo")
        with patch.object(session_start.sys, "platform", "linux"):
            self.assertEqual(session_start._normalize_windows_shell_path("/d/Work/a"), "/d/Work/a")
        self.assertEqual(session_start._normalize_windows_shell_path(""), "")

    def test_skip_notice_and_file_helpers_cover_present_and_missing_inputs(self) -> None:
        with patch.dict(os.environ, {"TRELLIS_HOOKS": "0"}, clear=True):
            self.assertTrue(session_start.should_skip_injection())
        with patch.dict(os.environ, {"CODEX_NON_INTERACTIVE": "1"}, clear=True):
            self.assertTrue(session_start.should_skip_injection(("CODEX_NON_INTERACTIVE",)))
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(session_start.should_skip_injection(("CODEX_NON_INTERACTIVE",)))
        file_path = self.root / "content.md"
        file_path.write_text("ok", encoding="utf-8")
        self.assertEqual(session_start.read_file(file_path), "ok")
        self.assertEqual(session_start.read_file(self.root / "missing", "fallback"), "fallback")
        self.assertEqual(session_start._build_first_reply_notice(None), session_start.FIRST_REPLY_NOTICE)
        self.assertIn("version 1.2", session_start._build_first_reply_notice("version 1.2"))

    def test_path_and_git_helpers_handle_normal_and_boundary_cases(self) -> None:
        self.assertEqual(session_start._repo_relative(self.root, self.root / "a"), "a")
        self.assertEqual(session_start._repo_relative(self.root, Path("/outside")), "/outside")
        with patch.object(session_start, "_run_git", side_effect=["main", " M one\n?? two"]):
            self.assertEqual(session_start._format_git_state(self.root), "Git: branch main; dirty 2 paths.")
        with patch.object(session_start, "_run_git", side_effect=["", ""]):
            self.assertEqual(session_start._format_git_state(self.root), "Git: branch (detached); clean.")
        completed = SimpleNamespace(returncode=0, stdout="value\n")
        with patch.object(session_start.subprocess, "run", return_value=completed):
            self.assertEqual(session_start._run_git(self.root, ["status"]), "value")
        with patch.object(session_start.subprocess, "run", side_effect=FileNotFoundError):
            self.assertEqual(session_start._run_git(self.root, ["status"]), "")

    def test_task_reference_helpers_normalize_and_resolve_boundaries(self) -> None:
        self.assertEqual(session_start._normalize_task_ref(" ./tasks/a "), ".trellis/tasks/a")
        self.assertEqual(session_start._normalize_task_ref(".\\a"), "a")
        self.assertEqual(session_start._normalize_task_ref("   "), "")
        self.assertEqual(session_start._resolve_task_dir(self.trellis, "tasks/a"), self.trellis / "tasks" / "a")
        absolute = self.root / "external"
        self.assertEqual(session_start._resolve_task_dir(self.trellis, str(absolute)), absolute)

    def test_task_status_keeps_codex_and_standard_messages(self) -> None:
        with patch.object(session_start, "_resolve_active_task", return_value=SimpleNamespace(task_path=None)):
            self.assertIn("Next-Action:", session_start._get_task_status(self.trellis, {}, "claude"))
            self.assertIn("Next:", session_start._get_task_status(self.trellis, {}, "codex"))
        task_dir = self.trellis / "tasks" / "a"
        task_dir.mkdir(parents=True)
        (task_dir / "task.json").write_text('{"title":"A", "status":"planning"}', encoding="utf-8")
        active = SimpleNamespace(task_path="a", stale=False)
        with patch.object(session_start, "_resolve_active_task", return_value=active):
            self.assertIn("Status: PLANNING", session_start._get_task_status(self.trellis, {}, "claude"))
        with patch.object(session_start, "_resolve_active_task", return_value=SimpleNamespace(task_path="gone", stale=True)):
            self.assertIn("STALE POINTER", session_start._get_task_status(self.trellis, {}, "codex"))

    def test_context_and_bash_helpers_delegate_and_deduplicate(self) -> None:
        with patch.object(session_start, "resolve_context_key", return_value="claude_s1") as resolver:
            self.assertEqual(session_start._resolve_context_key({"session_id": "s1"}, "claude"), "claude_s1")
            resolver.assert_called_once()
        with patch.object(session_start, "resolve_active_task", return_value=SimpleNamespace(task_path="a")) as resolver:
            self.assertEqual(session_start._resolve_active_task(self.trellis, {}, "codex").task_path, "a")
            resolver.assert_called_once()
        env_file = self.root / "env"
        with patch.dict(os.environ, {"CLAUDE_ENV_FILE": str(env_file)}, clear=True):
            session_start._persist_context_key_for_bash("claude_a")
            session_start._persist_context_key_for_bash("claude_a")
        self.assertEqual(env_file.read_text(encoding="utf-8"), "export TRELLIS_CONTEXT_ID=claude_a\n")
        self.assertEqual(session_start._last_context_key_export(str(env_file)), "export TRELLIS_CONTEXT_ID=claude_a")
        self.assertIsNone(session_start._last_context_key_export(str(self.root / "missing-env")))

    def test_update_hint_and_script_runner_are_best_effort(self) -> None:
        from common import session_context

        with patch.object(session_context, "get_update_hint", return_value="upgrade"):
            self.assertEqual(session_start._resolve_update_hint(self.trellis, "key"), "upgrade")
        script = self.root / "echo.py"
        script.write_text("print('context')\n", encoding="utf-8")
        self.assertEqual(session_start.run_script(script), "context\n")
        self.assertEqual(session_start.run_script(self.root / "missing.py"), "No context available")

    def test_spec_scope_and_legacy_detection_cover_valid_and_invalid_values(self) -> None:
        packages = {"api": {}, "web": {}}
        self.assertEqual(session_start._resolve_spec_scope(True, packages, "active_task", "api", None), {"api"})
        self.assertEqual(session_start._resolve_spec_scope(True, packages, ["web"], None, None), {"web"})
        self.assertIsNone(session_start._resolve_spec_scope(False, packages, ["web"], None, None))
        self.assertIsNone(session_start._check_legacy_spec(self.trellis, True, packages))
        (self.trellis / "spec" / "backend").mkdir()
        (self.trellis / "spec" / "backend" / "index.md").touch()
        warning = session_start._check_legacy_spec(self.trellis, True, packages)
        self.assertIn("Legacy spec structure", warning or "")

    def test_load_trellis_config_handles_available_and_failing_dependencies(self) -> None:
        from common import config, paths

        with (
            patch.object(config, "is_monorepo", return_value=True),
            patch.object(config, "get_packages", return_value={"api": {}}),
            patch.object(config, "get_spec_scope", return_value="active_task"),
            patch.object(config, "get_default_package", return_value="api"),
            patch.object(paths, "get_current_task", return_value=None),
        ):
            self.assertEqual(
                session_start._load_trellis_config(self.trellis, {}, "claude"),
                (True, {"api": {}}, "active_task", None, "api"),
            )
        with patch.object(config, "is_monorepo", side_effect=RuntimeError):
            self.assertEqual(
                session_start._load_trellis_config(self.trellis, {}, "claude"),
                (False, {}, None, None, None),
            )

    def test_claude_family_hook_keeps_compatibility_host_platform_mapping(self) -> None:
        task_dir = self.trellis / "tasks" / "a"
        task_dir.mkdir(parents=True)
        (task_dir / "task.json").write_text(
            '{"title":"A", "status":"in_progress"}', encoding="utf-8"
        )
        session_dir = self.trellis / ".runtime" / "sessions"
        session_dir.mkdir(parents=True)
        (session_dir / "codebuddy_s1.json").write_text(
            '{"current_task":".trellis/tasks/a"}', encoding="utf-8"
        )
        environment = os.environ | {"CODEBUDDY_PROJECT_DIR": str(self.root)}
        completed = subprocess.run(
            [sys.executable, str(ROOT / ".claude/hooks/session-start.py")],
            input=json.dumps({"cwd": str(self.root), "session_id": "s1"}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            check=True,
        )
        payload = json.loads(completed.stdout)
        context = payload["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Current task: .trellis/tasks/a; status=in_progress.", context)

    def test_spec_indexes_current_state_and_workflow_helpers(self) -> None:
        (self.trellis / "spec" / "guides" / "index.md").touch()
        (self.trellis / "spec" / "backend").mkdir()
        (self.trellis / "spec" / "backend" / "index.md").touch()
        (self.trellis / "spec" / "pkg" / "frontend").mkdir(parents=True)
        (self.trellis / "spec" / "pkg" / "frontend" / "index.md").touch()
        self.assertEqual(
            session_start._collect_spec_index_paths(self.trellis, {"pkg"}),
            [".trellis/spec/guides/index.md", ".trellis/spec/backend/index.md", ".trellis/spec/pkg/frontend/index.md"],
        )
        with patch.object(session_start, "_resolve_active_task", return_value=SimpleNamespace(task_path=None)):
            state = session_start._build_compact_current_state(self.trellis, {}, ["a"], "claude")
        self.assertIn("Current task: none.", state)
        self.assertIn("Spec indexes: 1 available.", state)
        content = "## Phase Index\nA\n[workflow-state:no_task]\nB\n[/workflow-state:no_task]\n\n## Phase 1: Plan\nC"
        self.assertEqual(session_start._extract_range(content, "Missing", "Phase 1: Plan"), "")
        self.assertNotIn("workflow-state", session_start._strip_breadcrumb_tag_blocks(content))
        workflow = self.trellis / "workflow.md"
        workflow.write_text(content, encoding="utf-8")
        self.assertIn("# Development Workflow", session_start._build_workflow_overview(workflow))
        self.assertEqual(session_start._build_workflow_overview(self.trellis / "none.md"), "No workflow.md found")


if __name__ == "__main__":
    unittest.main()
