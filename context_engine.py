"""A tiny context engine: estimated token budget, compaction, and disk memory."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol

DEFAULT_MEMORY_PATH = "AGENT_MEMORY.md"
MAX_SUMMARY_CHARS = 2_000
SUMMARY_INSTRUCTIONS = """Summarize the earlier work into terse meeting minutes.
Preserve the user's goal, decisions, file paths, commands, errors, facts learned,
work completed, and exact next steps. Drop raw file dumps and dead ends. Return
only the summary."""


class ModelClient(Protocol):
    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...


def count_tokens(messages: list[dict[str, Any]]) -> int:
    """Dependency-free estimate for teaching, not provider billing telemetry."""
    serialized = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    pieces = re.findall(r"\w+|[^\w\s]", serialized, flags=re.UNICODE)
    return max(1, int(len(pieces) * 1.15))


def load_memory(path: str | Path = DEFAULT_MEMORY_PATH) -> str:
    memory_path = Path(path)
    if not memory_path.is_file():
        return ""
    try:
        return memory_path.read_text(encoding="utf-8").strip()
    except OSError as error:
        return f"[Memory could not be loaded: {error}]"


def remember(fact: str, path: str | Path = DEFAULT_MEMORY_PATH) -> str:
    memory_path = Path(path)
    clean = " ".join(fact.strip().split())
    if not clean:
        return "ERROR: memory fact cannot be empty."
    current = load_memory(memory_path)
    existing = {
        line.removeprefix("- ").strip()
        for line in current.splitlines()
        if line.strip() and not line.startswith("#")
    }
    if clean in existing:
        return f"Already saved to memory: {clean}"
    try:
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        if not memory_path.exists():
            memory_path.write_text("# Agent Memory\n\n", encoding="utf-8")
        with memory_path.open("a", encoding="utf-8") as handle:
            handle.write(f"- {clean}\n")
    except OSError as error:
        return f"ERROR: could not save memory: {error}"
    return f"Saved to memory: {clean}"


class ContextEngine:
    """Build bounded model context from memory, summaries, and recent messages."""

    def __init__(
        self,
        compact_at: int = 40_000,
        keep_recent: int = 6,
        memory_path: str | Path = DEFAULT_MEMORY_PATH,
        summary_client: ModelClient | None = None,
    ) -> None:
        if keep_recent < 1:
            raise ValueError("keep_recent must be at least 1")
        self.compact_at = compact_at
        self.keep_recent = keep_recent
        self.memory_path = Path(memory_path)
        self.summary_client = summary_client

    def use_workspace(self, workspace: str | Path) -> None:
        if self.memory_path == Path(DEFAULT_MEMORY_PATH):
            self.memory_path = Path(workspace).resolve() / DEFAULT_MEMORY_PATH

    def start_messages(self, base_prompt: str, user_request: str) -> list[dict[str, Any]]:
        memory = load_memory(self.memory_path)
        system = base_prompt.strip()
        if memory:
            system += "\n\nPROJECT MEMORY — durable facts, not a transcript:\n" + memory
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_request},
        ]

    def should_compact(self, messages: list[dict[str, Any]]) -> bool:
        return count_tokens(messages) > self.compact_at and len(messages) > self.keep_recent + 2

    def maybe_compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.compact(messages) if self.should_compact(messages) else messages

    def compact(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.summary_client is None:
            raise RuntimeError("Compaction requires a summary_client.")
        system = messages[0]
        split = len(messages) - self.keep_recent
        # Tool results are protocol-coupled to the preceding assistant tool call.
        # Move the boundary left rather than sending an orphaned tool message.
        while split > 1 and messages[split].get("role") == "tool":
            split -= 1
        recent = messages[split:]
        old = messages[1:split]
        if not old:
            return messages
        prompt = SUMMARY_INSTRUCTIONS + "\n\nEARLIER MESSAGES:\n" + json.dumps(old, ensure_ascii=False, indent=2)
        reply = self.summary_client.complete([{"role": "user", "content": prompt}])
        summary = reply.get("content") or "No summary was returned."
        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS].rstrip() + "\n[Summary truncated by harness.]"
        return [
            system,
            {"role": "user", "content": "[Summary of earlier work]\n" + summary},
            *recent,
        ]
