"""The smallest useful agentic harness, built without an agent framework."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from context_engine import ContextEngine, count_tokens
from safety import SafeToolExecutor
from tools import execute_tool, openrouter_tools

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


TOOLS = openrouter_tools()


def run_tool(name: str, arguments: dict[str, Any]) -> str:
    """The harness—not the model—performs the requested real-world action."""
    legacy_name = "read" if name == "read_file" else name
    return execute_tool(legacy_name, arguments)


def text_of(message: dict[str, Any]) -> str:
    return message.get("content") or ""


def run_agent(
    user_request: str,
    client: OpenRouterClient | None = None,
    max_turns: int = 20,
    cwd: str | Path = ".",
    show_state: bool = False,
    executor: SafeToolExecutor | None = None,
    context_engine: ContextEngine | None = None,
    system_prompt: str = "You are a coding agent. Use tools to finish the job.",
) -> str:
    """Call → append → act → observe → repeat, until the model answers."""
    model = client or OpenRouterClient()
    if context_engine:
        context_engine.use_workspace(cwd)
    messages = (
        context_engine.start_messages(system_prompt, user_request)
        if context_engine
        else [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request},
        ]
    )

    for turn in range(1, max_turns + 1):
        raw_tokens = count_tokens(messages)
        if context_engine:
            compacted = context_engine.maybe_compact(messages)
            if compacted is not messages:
                print(
                    f"COMPACTION: {raw_tokens:,} → {count_tokens(compacted):,} estimated tokens; "
                    f"recent {context_engine.keep_recent} messages kept verbatim"
                )
                messages = compacted
        print(f"CONTEXT: sending ~{count_tokens(messages):,} tokens in {len(messages)} messages")
        reply = model.complete(messages, tools=TOOLS)
        messages.append(reply)
        tool_calls = reply.get("tool_calls") or []
        print(f"\n{'=' * 72}\nTURN {turn}: {'tool call' if tool_calls else 'final answer'}\n{'=' * 72}")

        if show_state:
            print(f"STATE: {len(messages)} messages after appending assistant")
            _print_messages(messages)

        if not tool_calls:
            return text_of(reply)

        for call in tool_calls:
            function = call["function"]
            arguments = json.loads(function["arguments"])
            print(f"MODEL CHOSE: {function['name']}({json.dumps(arguments, ensure_ascii=False)})")
            tool_name = "read" if function["name"] == "read_file" else function["name"]
            output = (
                executor.execute(tool_name, arguments)
                if executor
                else execute_tool(tool_name, arguments, cwd=cwd)
            )
            result = {"role": "tool", "tool_call_id": call["id"], "content": output}
            messages.append(result)
            print(f"HARNESS APPENDED: tool result ({len(output)} chars)")

        if show_state:
            print(f"STATE: {len(messages)} messages after appending tool result(s)")
            _print_messages(messages)

    raise RuntimeError(f"Agent exceeded max_turns={max_turns}.")


def _print_messages(messages: list[dict[str, Any]]) -> None:
    """Render the model's complete memory after each append for teaching."""
    for index, message in enumerate(messages):
        role = message["role"].upper()
        if message.get("tool_calls"):
            calls = [call["function"]["name"] for call in message["tool_calls"]]
            summary = f"tool_calls={calls}"
        else:
            content = message.get("content") or ""
            summary = content if len(content) <= 160 else content[:157] + "..."
            summary = summary.replace("\n", "\\n")
        print(f"  messages[{index}] {role:<9} {summary}")
