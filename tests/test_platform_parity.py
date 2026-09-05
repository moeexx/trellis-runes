from __future__ import annotations

import ast
import json
import re
import unittest
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = ("claude", "codex", "kiro", "qoder")
HOOK_PATH = Path("hooks/inject-workflow-state.py")

WORKFLOW_ACTIVATION_SYMBOLS = frozenset(
    {
        "resolve_workflow_activation",
        "build_workflow_entry",
        "build_activation_error",
    }
)
CRITICAL_HELPERS = frozenset(
    {
        "find_trellis_root",
        "_detect_platform",
        "_resolve_active_task",
        "_resolve_workflow_activation",
        "_build_workflow_entry",
        "_build_activation_error",
        "get_active_task",
        "load_breadcrumbs",
        "_read_trellis_config",
        "_resolve_skip_keyword",
        "prompt_has_skip_keyword",
        "_resolve_codex_dispatch_mode",
        "_codex_mode_banner",
        "resolve_breadcrumb_key",
        "build_breadcrumb",
        "_load_hook_input",
        "main",
    }
)
WORKFLOW_CONSTANTS = frozenset(
    {
        r"\[workflow-state:([A-Za-z0-9_-]+)\]\s*\n(.*?)\n\s*\[/workflow-state:\1\]",
        "<workflow-state>\n",
        "\n</workflow-state>",
        "no_task",
        "task_error",
        "prompt_injection",
        "skip_keyword",
        "codex",
        "dispatch_mode",
    }
)
SESSION_START_PATH = Path("hooks/session-start.py")
SESSION_START_SYMBOLS = frozenset(
    {
        "_build_compact_current_state",
        "_build_first_reply_notice",
        "_build_workflow_overview",
        "_check_legacy_spec",
        "_collect_spec_index_paths",
        "_detect_platform",
        "_get_task_status",
        "_load_trellis_config",
        "_normalize_windows_shell_path",
        "_persist_context_key_for_bash",
        "_resolve_context_key",
        "_resolve_spec_scope",
        "_resolve_update_hint",
        "should_skip_injection",
    }
)
CODEX_SESSION_START_SYMBOLS = frozenset(
    {
        "FIRST_REPLY_NOTICE",
        "_build_compact_current_state",
        "_build_workflow_overview",
        "_collect_spec_index_paths",
        "_detect_platform",
        "_get_task_status",
        "_normalize_windows_shell_path",
        "should_skip_injection",
    }
)
EXTRACTED_SESSION_START_HELPERS = frozenset(
    {
        "_normalize_windows_shell_path",
        "_build_first_reply_notice",
        "should_skip_injection",
        "read_file",
        "_repo_relative",
        "_run_git",
        "_format_git_state",
        "_normalize_task_ref",
        "_resolve_task_dir",
        "_get_task_status",
        "_load_trellis_config",
        "_check_legacy_spec",
        "_resolve_spec_scope",
        "_collect_spec_index_paths",
        "_build_compact_current_state",
        "_extract_range",
        "_strip_breadcrumb_tag_blocks",
        "_build_workflow_overview",
    }
)


@dataclass(frozen=True)
class HookContract:
    imports: frozenset[str]
    calls: frozenset[str]
    helpers: frozenset[str]
    constants: frozenset[str]


@dataclass(frozen=True)
class SessionStartContract:
    imports: frozenset[str]
    local_helpers: frozenset[str]


def extract_contract(source: str, filename: str = "hook.py") -> HookContract:
    tree = ast.parse(source, filename=filename)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "common.workflow_activation"
        for alias in node.names
    }
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in WORKFLOW_ACTIVATION_SYMBOLS
    }
    helpers = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in CRITICAL_HELPERS
    }
    constants = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value in WORKFLOW_CONSTANTS
    }
    return HookContract(
        imports=frozenset(imports),
        calls=frozenset(calls),
        helpers=frozenset(helpers),
        constants=frozenset(constants),
    )


def extract_session_start_contract(
    source: str, filename: str = "session-start.py"
) -> SessionStartContract:
    tree = ast.parse(source, filename=filename)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "common.session_start"
        for alias in node.names
    }
    local_helpers = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in EXTRACTED_SESSION_START_HELPERS
    }
    return SessionStartContract(frozenset(imports), frozenset(local_helpers))


class PlatformParityTests(unittest.TestCase):
    def hook_source(self, platform: str) -> str:
        return (ROOT / f".{platform}" / HOOK_PATH).read_text(encoding="utf-8")

    def session_start_source(self, platform: str) -> str:
        return (ROOT / f".{platform}" / SESSION_START_PATH).read_text(encoding="utf-8")

    def assert_shared_contract(self, contract: HookContract) -> None:
        self.assertEqual(contract.imports, WORKFLOW_ACTIVATION_SYMBOLS)
        self.assertEqual(contract.calls, WORKFLOW_ACTIVATION_SYMBOLS)
        self.assertEqual(contract.helpers, CRITICAL_HELPERS)
        self.assertEqual(contract.constants, WORKFLOW_CONSTANTS)

    def test_all_platform_hooks_keep_the_shared_workflow_contract(self) -> None:
        for platform in PLATFORMS:
            with self.subTest(platform=platform):
                self.assert_shared_contract(
                    extract_contract(self.hook_source(platform), platform)
                )

    def test_checker_rejects_missing_shared_contract_members(self) -> None:
        source = self.hook_source("claude")
        mutations = {
            "workflow activation call": source.replace(
                "return resolve_workflow_activation(",
                "return resolve_workflow_activation_removed(",
                1,
            ),
            "critical helper": source.replace(
                "def build_breadcrumb(", "def build_breadcrumb_removed(", 1
            ),
            "workflow-state marker": source.replace(
                "<workflow-state>\\n", "<workflow_state>\\n", 1
            ),
        }

        for member, mutated_source in mutations.items():
            with self.subTest(member=member):
                with self.assertRaises(AssertionError):
                    self.assert_shared_contract(extract_contract(mutated_source, member))

    def test_agents_keep_evidence_report_contract(self) -> None:
        statuses = {"DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT"}
        paths = (
            ".trellis/agents/implement.md", ".trellis/agents/check.md",
            ".claude/agents/trellis-implement.md", ".claude/agents/trellis-check.md",
            ".qoder/agents/trellis-implement.md", ".qoder/agents/trellis-check.md",
            ".codex/agents/trellis-implement.toml", ".codex/agents/trellis-check.toml",
        )
        for relative in paths:
            with self.subTest(relative=relative):
                self.assertTrue(statuses <= set(re.findall(r"DONE(?:_WITH_CONCERNS)?|BLOCKED|NEEDS_CONTEXT", (ROOT / relative).read_text(encoding="utf-8"))))
        for name in ("trellis-implement", "trellis-check"):
            data = json.loads((ROOT / f".kiro/agents/{name}.json").read_text(encoding="utf-8"))
            self.assertTrue(statuses <= set(re.findall(r"DONE(?:_WITH_CONCERNS)?|BLOCKED|NEEDS_CONTEXT", data["evidenceReportContract"])))
        for relative in (".trellis/agents/check.md", ".claude/agents/trellis-check.md", ".qoder/agents/trellis-check.md", ".codex/agents/trellis-check.toml"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            for severity in ("P0", "P1", "P2"):
                self.assertIn(severity, source)

    def test_read_only_review_and_verify_agents_keep_verdicts(self) -> None:
        expected = {"review": ("APPROVED", "CONDITIONAL", "REJECTED"), "verify": ("PASS", "FAIL")}
        paths = {
            "review": (".trellis/agents/review.md", ".claude/agents/trellis-review.md", ".qoder/agents/trellis-review.md", ".codex/agents/trellis-review.toml", ".kiro/agents/trellis-review.json"),
            "verify": (".trellis/agents/verify.md", ".claude/agents/trellis-verify.md", ".qoder/agents/trellis-verify.md", ".codex/agents/trellis-verify.toml", ".kiro/agents/trellis-verify.json"),
        }
        for role, relatives in paths.items():
            for relative in relatives:
                with self.subTest(role=role, relative=relative):
                    source = (ROOT / relative).read_text(encoding="utf-8")
                    self.assertIn("read-only", source.lower())
                    self.assertRegex(source, r"git\s+write")
                    for verdict in expected[role]:
                        self.assertIn(verdict, source)

    def assert_session_start_contract(
        self, contract: SessionStartContract, expected_imports: frozenset[str]
    ) -> None:
        self.assertEqual(contract.imports, expected_imports)
        self.assertFalse(contract.local_helpers)

    def test_session_start_hooks_import_shared_logic_without_local_copies(self) -> None:
        for platform in ("claude", "kiro", "qoder"):
            with self.subTest(platform=platform):
                self.assert_session_start_contract(
                    extract_session_start_contract(self.session_start_source(platform), platform),
                    SESSION_START_SYMBOLS,
                )
        self.assert_session_start_contract(
            extract_session_start_contract(self.session_start_source("codex"), "codex"),
            CODEX_SESSION_START_SYMBOLS,
        )

    def test_checker_rejects_reintroduced_session_start_helper(self) -> None:
        source = self.session_start_source("claude")
        mutated = source + "\n\ndef _normalize_windows_shell_path(path_str):\n    return path_str\n"
        with self.assertRaises(AssertionError):
            self.assert_session_start_contract(
                extract_session_start_contract(mutated), SESSION_START_SYMBOLS
            )


if __name__ == "__main__":
    unittest.main()
