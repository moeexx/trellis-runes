from __future__ import annotations

import ast
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


@dataclass(frozen=True)
class HookContract:
    imports: frozenset[str]
    calls: frozenset[str]
    helpers: frozenset[str]
    constants: frozenset[str]


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


class PlatformParityTests(unittest.TestCase):
    def hook_source(self, platform: str) -> str:
        return (ROOT / f".{platform}" / HOOK_PATH).read_text(encoding="utf-8")

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
                "resolve_workflow_activation(root, input_data.get(\"prompt\"), input_data, platform)",
                "resolve_workflow_activation_removed(root, input_data.get(\"prompt\"), input_data, platform)",
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


if __name__ == "__main__":
    unittest.main()
