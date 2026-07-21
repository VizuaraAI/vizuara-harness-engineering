import tempfile
import unittest
from pathlib import Path

from tools import TOOLBOX, Tool, execute_tool, openrouter_tools


class ToolContractTests(unittest.TestCase):
    def test_tool_has_contract_and_execution_halves(self):
        tool = TOOLBOX["read"]
        self.assertIsInstance(tool, Tool)
        self.assertEqual(tool.name, "read")
        self.assertEqual(tool.label, "Read")
        self.assertTrue(tool.description)
        self.assertEqual(tool.parameters["type"], "object")
        self.assertTrue(callable(tool.execute))

    def test_openrouter_sees_only_contract_half(self):
        definitions = openrouter_tools()
        self.assertEqual(
            [definition["function"]["name"] for definition in definitions],
            ["read", "write", "edit", "bash", "grep", "find", "ls"],
        )
        self.assertNotIn("execute", definitions[0]["function"])
        self.assertIn("parameters", definitions[0]["function"])


class ToolExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def run_tool(self, name, **arguments):
        return execute_tool(name, arguments, cwd=self.root)

    def test_write_read_and_edit(self):
        self.assertIn("Wrote", self.run_tool("write", path="notes/a.txt", content="alpha\nbeta\n"))
        self.assertEqual(self.run_tool("read", path="notes/a.txt"), "1|alpha\n2|beta")
        self.assertIn(
            "Edited",
            self.run_tool("edit", path="notes/a.txt", old_string="beta", new_string="gamma"),
        )
        self.assertEqual((self.root / "notes/a.txt").read_text(), "alpha\ngamma\n")

    def test_read_supports_paging(self):
        (self.root / "large.txt").write_text("\n".join(f"line {n}" for n in range(1, 7)))
        output = self.run_tool("read", path="large.txt", offset=3, limit=2)
        self.assertIn("3|line 3", output)
        self.assertIn("4|line 4", output)
        self.assertIn("Use offset=5 to continue", output)

    def test_ls_find_and_grep(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("print('needle')\n")
        (self.root / "src" / "other.txt").write_text("nothing\n")

        self.assertIn("src/", self.run_tool("ls"))
        self.assertEqual(self.run_tool("find", pattern="**/*.py"), "src/app.py")
        self.assertIn("src/app.py:1:print('needle')", self.run_tool("grep", pattern="needle"))

    def test_bash_runs_in_workspace(self):
        output = self.run_tool("bash", command="pwd && printf hello")
        self.assertIn(str(self.root), output)
        self.assertTrue(output.endswith("hello"))

    def test_errors_are_results_not_crashes(self):
        self.assertIn("ERROR:", self.run_tool("read", path="missing.txt"))
        self.assertIn("Use ls or find", self.run_tool("read", path="missing.txt"))
        self.assertIn("ERROR:", self.run_tool("edit", path="missing.txt", old_string="a", new_string="b"))
        self.assertIn("Unknown tool", self.run_tool("nope"))

    def test_edit_rejects_ambiguous_match(self):
        (self.root / "same.txt").write_text("x x")
        output = self.run_tool("edit", path="same.txt", old_string="x", new_string="y")
        self.assertIn("matched 2 times", output)
        self.assertEqual((self.root / "same.txt").read_text(), "x x")


if __name__ == "__main__":
    unittest.main()
