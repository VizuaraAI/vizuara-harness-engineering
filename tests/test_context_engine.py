import tempfile
import unittest
from pathlib import Path

from context_engine import ContextEngine, count_tokens, load_memory, remember
from harness import run_agent


class SummaryClient:
    def __init__(self, summary="goal preserved; tests pass; next: document"):
        self.summary = summary
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append(messages)
        return {"role": "assistant", "content": self.summary}


class TokenCountingTests(unittest.TestCase):
    def test_count_tokens_is_deterministic_and_nonzero(self):
        messages = [{"role": "user", "content": "one two three four"}]
        self.assertGreaterEqual(count_tokens(messages), 4)
        self.assertEqual(count_tokens(messages), count_tokens(messages))


class CompactionTests(unittest.TestCase):
    def make_messages(self):
        return [
            {"role": "system", "content": "SYSTEM RULES"},
            {"role": "user", "content": "ORIGINAL GOAL " + "x " * 80},
            {"role": "assistant", "content": "old analysis " + "y " * 80},
            {"role": "user", "content": "old observation " + "z " * 80},
            {"role": "assistant", "content": "recent assistant"},
            {"role": "user", "content": "recent user"},
        ]

    def test_compaction_keeps_system_and_recent_messages_verbatim(self):
        client = SummaryClient()
        engine = ContextEngine(compact_at=20, keep_recent=2, summary_client=client)
        original = self.make_messages()

        compacted = engine.compact(original)

        self.assertEqual(compacted[0], original[0])
        self.assertEqual(compacted[-2:], original[-2:])
        self.assertIn("Summary of earlier work", compacted[1]["content"])
        self.assertIn(client.summary, compacted[1]["content"])

    def test_compaction_reduces_estimated_tokens(self):
        client = SummaryClient("short summary")
        engine = ContextEngine(compact_at=20, keep_recent=2, summary_client=client)
        original = self.make_messages()
        compacted = engine.compact(original)
        self.assertLess(count_tokens(compacted), count_tokens(original))

    def test_compaction_never_orphans_a_tool_result(self):
        client = SummaryClient("tool work preserved")
        engine = ContextEngine(compact_at=20, keep_recent=2, summary_client=client)
        messages = [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "old " * 100},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read", "arguments": '{"path":"a.txt"}'},
                }],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
            {"role": "assistant", "content": "recent conclusion"},
        ]

        compacted = engine.compact(messages)

        tool_index = next(i for i, message in enumerate(compacted) if message["role"] == "tool")
        self.assertEqual(compacted[tool_index - 1]["role"], "assistant")
        self.assertEqual(compacted[tool_index - 1]["tool_calls"][0]["id"], "call_1")

    def test_maybe_compact_only_runs_over_budget(self):
        client = SummaryClient()
        engine = ContextEngine(compact_at=10_000, keep_recent=2, summary_client=client)
        messages = self.make_messages()
        self.assertIs(engine.maybe_compact(messages), messages)
        self.assertEqual(client.calls, [])

    def test_unbounded_model_summary_is_truncated(self):
        client = SummaryClient("summary " * 5_000)
        engine = ContextEngine(compact_at=100, keep_recent=2, summary_client=client)
        compacted = engine.compact(self.make_messages())
        self.assertLess(len(compacted[1]["content"]), 2_100)


class PersistentMemoryTests(unittest.TestCase):
    def test_remember_persists_and_load_memory_reads_next_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AGENT_MEMORY.md"
            result = remember("Tests use unittest discovery.", path)
            self.assertIn("saved", result.lower())
            self.assertIn("Tests use unittest discovery.", load_memory(path))

    def test_remember_deduplicates_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AGENT_MEMORY.md"
            remember("Use Python 3.11+.", path)
            remember("Use Python 3.11+.", path)
            self.assertEqual(path.read_text().count("Use Python 3.11+."), 1)

    def test_context_engine_seeds_system_message_with_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AGENT_MEMORY.md"
            remember("Never touch production.", path)
            engine = ContextEngine(memory_path=path, summary_client=SummaryClient())
            messages = engine.start_messages("BASE PROMPT", "Do work")
            self.assertEqual(messages[0]["role"], "system")
            self.assertIn("Never touch production.", messages[0]["content"])
            self.assertEqual(messages[1], {"role": "user", "content": "Do work"})

    def test_run_agent_resolves_default_memory_inside_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AGENT_MEMORY.md"
            remember("Workspace memory is loaded.", path)
            client = RecordingClient([{"role": "assistant", "content": "done"}])
            engine = ContextEngine(summary_client=client)

            run_agent("new task", client=client, cwd=directory, context_engine=engine)

            self.assertIn("Workspace memory is loaded.", client.calls[0][0]["content"])


class RecordingClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append([dict(message) for message in messages])
        return next(self.replies)


if __name__ == "__main__":
    unittest.main()
