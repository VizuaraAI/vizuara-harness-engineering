"""The smallest useful agentic harness, built without an agent framework."""

from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b:free"

Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenRouter returned HTTP {error.code}: {detail}") from error


class OpenRouterClient:
    """One small model client: messages in, the model's next message out."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        transport: Transport = _post_json,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("Set OPENROUTER_API_KEY before running the demos.")
        self.model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.transport = transport

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if tools:
            payload["tools"] = tools
        response = self.transport(
            OPENROUTER_URL,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload,
        )
        return response["choices"][0]["message"]


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file and return its contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    }
]


def run_tool(name: str, arguments: dict[str, Any]) -> str:
    """The harness—not the model—performs the requested real-world action."""
    if name == "read_file":
        return pathlib.Path(arguments["path"]).read_text(encoding="utf-8")
    return f"Unknown tool: {name}"


def text_of(message: dict[str, Any]) -> str:
    return message.get("content") or ""


def run_agent(
    user_request: str,
    client: OpenRouterClient | None = None,
    max_turns: int = 8,
) -> str:
    """Call → append → act → observe → repeat, until the model answers."""
    model = client or OpenRouterClient()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_request}]

    for turn in range(1, max_turns + 1):
        reply = model.complete(messages, tools=TOOLS)
        messages.append(reply)
        tool_calls = reply.get("tool_calls") or []
        print(f"TURN {turn}: {'tool call' if tool_calls else 'final answer'}")

        if not tool_calls:
            return text_of(reply)

        for call in tool_calls:
            function = call["function"]
            arguments = json.loads(function["arguments"])
            output = run_tool(function["name"], arguments)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": output,
                }
            )

    raise RuntimeError(f"Agent exceeded max_turns={max_turns}.")
