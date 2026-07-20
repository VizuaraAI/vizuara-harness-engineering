import unittest

from harness import OpenRouterClient, run_agent, run_tool, text_of


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return next(self.replies)


class HarnessTests(unittest.TestCase):
    def test_client_builds_openrouter_request(self):
        captured = {}

        def fake_transport(url, headers, payload):
            captured.update(url=url, headers=headers, payload=payload)
            return {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}

        client = OpenRouterClient(api_key="test-key", model="test/model", transport=fake_transport)
        reply = client.complete([{"role": "user", "content": "hi"}])

        self.assertEqual(reply["content"], "hello")
        self.assertEqual(captured["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(captured["payload"]["model"], "test/model")
        self.assertNotIn("tools", captured["payload"])

    def test_read_file_tool_reads_text(self):
        self.assertIn("Agentic Harness", run_tool("read_file", {"path": "README.md"}))

    def test_agent_runs_tool_and_feeds_result_back(self):
        client = FakeClient([
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "arguments": '{"path":"README.md"}',
                    },
                }],
            },
            {"role": "assistant", "content": "The file has been read."},
        ])

        answer = run_agent("Read README.md", client=client, max_turns=3)

        self.assertEqual(answer, "The file has been read.")
        second_messages = client.calls[1]["messages"]
        self.assertEqual(second_messages[-2]["role"], "assistant")
        self.assertEqual(second_messages[-1]["role"], "tool")
        self.assertEqual(second_messages[-1]["tool_call_id"], "call_1")
        self.assertIn("Agentic Harness", second_messages[-1]["content"])

    def test_agent_stops_on_plain_text(self):
        client = FakeClient([{"role": "assistant", "content": "Done."}])
        self.assertEqual(run_agent("Say done", client=client), "Done.")
        self.assertEqual(len(client.calls), 1)

    def test_text_of_handles_empty_content(self):
        self.assertEqual(text_of({"content": None}), "")


if __name__ == "__main__":
    unittest.main()
