import tempfile
import unittest
from pathlib import Path

from safety import ApprovalMode, Decision, PermissionGate, SafeToolExecutor, WorkspaceSandbox


class PermissionGateTests(unittest.TestCase):
    def test_normal_mode_allows_reads_and_asks_for_writes(self):
        gate = PermissionGate(ApprovalMode.NORMAL)
        self.assertEqual(gate.decide("read", {"path": "a.txt"}), Decision.ALLOW)
        self.assertEqual(gate.decide("grep", {"pattern": "x"}), Decision.ALLOW)
        self.assertEqual(gate.decide("write", {"path": "a.txt", "content": "x"}), Decision.ASK)
        self.assertEqual(gate.decide("edit", {"path": "a.txt"}), Decision.ASK)

    def test_normal_mode_distinguishes_safe_and_risky_bash(self):
        gate = PermissionGate(ApprovalMode.NORMAL)
        self.assertEqual(gate.decide("bash", {"command": "python3 -m unittest"}), Decision.ALLOW)
        self.assertEqual(gate.decide("bash", {"command": "rm -rf build"}), Decision.ASK)
        self.assertEqual(gate.decide("bash", {"command": "git push origin main"}), Decision.ASK)

    def test_risky_bash_with_compound_command_still_asks(self):
        gate = PermissionGate(ApprovalMode.NORMAL)
        self.assertEqual(
            gate.decide("bash", {"command": "printf done && rm -rf build"}),
            Decision.ASK,
        )

    def test_find_delete_is_a_risky_shell_action(self):
        gate = PermissionGate(ApprovalMode.NORMAL)
        self.assertEqual(
            gate.decide("bash", {"command": "find . -name '*.tmp' -delete"}),
            Decision.ASK,
        )

    def test_strict_asks_and_auto_allows(self):
        self.assertEqual(PermissionGate(ApprovalMode.STRICT).decide("read", {"path": "a"}), Decision.ASK)
        self.assertEqual(PermissionGate(ApprovalMode.AUTO).decide("write", {"path": "a"}), Decision.ALLOW)

    def test_catastrophic_commands_are_always_denied(self):
        for mode in ApprovalMode:
            gate = PermissionGate(mode)
            self.assertEqual(gate.decide("bash", {"command": "sudo rm -rf /"}), Decision.DENY)

    def test_catastrophic_commands_are_denied_inside_compound_commands(self):
        gate = PermissionGate(ApprovalMode.AUTO)
        self.assertEqual(
            gate.decide("bash", {"command": "printf start; sudo rm -rf /"}),
            Decision.DENY,
        )


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.outside = self.root.parent / "outside-safety-test.txt"
        self.outside.unlink(missing_ok=True)

    def tearDown(self):
        self.outside.unlink(missing_ok=True)
        self.temp.cleanup()

    def test_filesystem_paths_cannot_escape_workspace(self):
        sandbox = WorkspaceSandbox(self.root)
        self.assertIsNone(sandbox.validate("write", {"path": "inside.txt"}))
        self.assertIn("SANDBOX DENIED", sandbox.validate("write", {"path": "../outside.txt"}))
        self.assertIn("SANDBOX DENIED", sandbox.validate("read", {"path": str(self.outside)}))

    def test_network_and_shell_escape_are_denied(self):
        sandbox = WorkspaceSandbox(self.root, allow_network=False)
        self.assertIn("network", sandbox.validate("bash", {"command": "curl https://example.com"}).lower())
        self.assertIn("workspace", sandbox.validate("bash", {"command": "cd .. && pwd"}).lower())

    def test_shell_is_disabled_by_default_because_string_matching_is_not_isolation(self):
        executor = SafeToolExecutor(self.root, mode=ApprovalMode.AUTO, approve=lambda *_: True)
        result = executor.execute("bash", {"command": "printf hello"})
        self.assertIn("SANDBOX DENIED", result)
        self.assertIn("disabled", result.lower())

    def test_nested_interpreters_and_environment_paths_are_denied(self):
        sandbox = WorkspaceSandbox(self.root, allow_network=False)
        commands = [
            "python3 -c 'open(\"../escaped.txt\", \"w\").write(\"bad\")'",
            "bash -c 'echo bad > /tmp/escaped.txt'",
            "printf bad > $HOME/escaped.txt",
            "printf bad > ~/escaped.txt",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("SANDBOX DENIED", sandbox.validate("bash", {"command": command}) or "")

    def test_executor_asks_before_risky_action(self):
        (self.root / "trash.txt").write_text("temporary")
        approvals = []

        def approve(tool, arguments, reason):
            approvals.append((tool, arguments, reason))
            return True

        executor = SafeToolExecutor(
            self.root,
            mode=ApprovalMode.NORMAL,
            approve=approve,
            allow_unsafe_shell=True,
        )
        result = executor.execute("bash", {"command": "rm trash.txt"})

        self.assertEqual(len(approvals), 1)
        self.assertIn("APPROVED", result)
        self.assertFalse((self.root / "trash.txt").exists())

    def test_refusal_is_returned_to_model_and_action_does_not_run(self):
        target = self.root / "keep.txt"
        target.write_text("keep")
        executor = SafeToolExecutor(
            self.root,
            mode=ApprovalMode.NORMAL,
            approve=lambda *_: False,
            allow_unsafe_shell=True,
        )

        result = executor.execute("bash", {"command": "rm keep.txt"})

        self.assertIn("PERMISSION DENIED BY USER", result)
        self.assertTrue(target.exists())

    def test_sandbox_blocks_escape_even_in_auto_mode(self):
        executor = SafeToolExecutor(self.root, mode=ApprovalMode.AUTO, approve=lambda *_: True)
        result = executor.execute("write", {"path": "../outside-safety-test.txt", "content": "bad"})
        self.assertIn("SANDBOX DENIED", result)
        self.assertFalse(self.outside.exists())


if __name__ == "__main__":
    unittest.main()
