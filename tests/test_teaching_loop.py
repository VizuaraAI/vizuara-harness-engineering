import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from harness import run_agent


class RecordingClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.snapshots = []

    def complete(self, messages, tools=None):
        self.snapshots.append([dict(message) for message in messages])
        return next(self.replies)


class TeachingLoopTests(unittest.TestCase):
    def test_state_display_shows_each_append(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "note.txt").write_text("hello")
            client = RecordingClient(
                [
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read",
                                    "arguments": '{"path":"note.txt"}',
                                },
                            }
                        ],
                    },
                    {"role": "assistant", "content": "done"},
                ]
            )
            output = io.StringIO()

            with redirect_stdout(output):
                answer = run_agent("read note", client=client, cwd=directory, show_state=True)

        self.assertEqual(answer, "done")
        self.assertEqual([len(snapshot) for snapshot in client.snapshots], [1, 3])
        transcript = output.getvalue()
        self.assertIn("TURN 1: tool call", transcript)
        self.assertIn("MODEL CHOSE: read", transcript)
        self.assertIn("messages[0] USER", transcript)
        self.assertIn("messages[1] ASSISTANT", transcript)
        self.assertIn("messages[2] TOOL", transcript)


if __name__ == "__main__":
    unittest.main()
