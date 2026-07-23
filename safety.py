"""Permission gates and a small workspace sandbox for the teaching harness."""

from __future__ import annotations

import re
import shlex
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from tools import execute_tool


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ApprovalMode(str, Enum):
    STRICT = "strict"
    NORMAL = "normal"
    AUTO = "auto"


READ_ONLY_TOOLS = {"read", "grep", "find", "ls"}
MUTATING_TOOLS = {"write", "edit"}
CATASTROPHIC_PATTERNS = [
    r"\bsudo\b",
    r"\brm\s+-[^\n]*r[^\n]*f[^\n]*\s+/(?:\s|$)",
    r"\b(?:mkfs|shutdown|reboot)\b",
]
RISKY_PATTERNS = [
    r"\brm\b",
    r"\bfind\b[^\n]*\s-delete\b",
    r"\bgit\s+push\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bssh\b",
    r"\bscp\b",
    r"\bchmod\b",
    r"\bchown\b",
    r"\b(?:pip|npm|brew)\s+install\b",
]
NETWORK_PATTERNS = [r"\bcurl\b", r"\bwget\b", r"\bssh\b", r"\bscp\b", r"\bnc\b"]
NESTED_SHELL_PATTERNS = [
    r"\b(?:python(?:3)?|ruby|perl|node)\b[^;&|]*\s-[ce]\b",
    r"\b(?:ba|z|c|fi)?sh\b[^;&|]*\s-c\b",
    r"\b(?:eval|source)\b",
    r"\$\{?(?:HOME|TMPDIR|PWD|OLDPWD)\}?",
]


class PermissionGate:
    """Classify what the model wants before execution reaches a tool."""

    def __init__(self, mode: ApprovalMode | str = ApprovalMode.NORMAL) -> None:
        self.mode = ApprovalMode(mode)

    def decide(self, tool: str, arguments: dict[str, Any]) -> Decision:
        command = str(arguments.get("command", "")) if tool == "bash" else ""
        if tool == "bash" and _matches(command, CATASTROPHIC_PATTERNS):
            return Decision.DENY
        if self.mode is ApprovalMode.STRICT:
            return Decision.ASK
        if self.mode is ApprovalMode.AUTO:
            return Decision.ALLOW
        if tool in READ_ONLY_TOOLS:
            return Decision.ALLOW
        if tool in MUTATING_TOOLS:
            return Decision.ASK
        if tool == "bash":
            return Decision.ASK if _matches(command, RISKY_PATTERNS) else Decision.ALLOW
        return Decision.ASK

    def reason(self, tool: str, arguments: dict[str, Any], decision: Decision) -> str:
        if decision is Decision.DENY:
            return "the command matches a catastrophic pattern that is never allowed"
        if self.mode is ApprovalMode.STRICT:
            return "strict mode asks before every action"
        if tool in MUTATING_TOOLS:
            return f"{tool} changes files"
        if tool == "bash":
            return "the shell command can delete, publish, install, or reach outside the workspace"
        return "the action requires human judgment"


def _matches(command: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, command, re.IGNORECASE) for pattern in patterns)


class WorkspaceSandbox:
    """Shrink blast radius to one directory; this is not OS/container isolation."""

    FILE_PATH_FIELDS = {
        "read": ("path",),
        "write": ("path",),
        "edit": ("path",),
        "grep": ("path",),
        "find": ("path",),
        "ls": ("path",),
        "remember": ("path",),
    }

    def __init__(self, root: str | Path, allow_network: bool = False) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.allow_network = allow_network

    def validate(self, tool: str, arguments: dict[str, Any]) -> str | None:
        for field in self.FILE_PATH_FIELDS.get(tool, ()):
            value = arguments.get(field)
            if value in (None, ""):
                continue
            candidate = self._resolve(str(value))
            if not self._contains(candidate):
                return f"SANDBOX DENIED: {field} resolves outside workspace {self.root}: {candidate}"
        if tool == "bash":
            command = str(arguments.get("command", ""))
            if not self.allow_network and _matches(command, NETWORK_PATTERNS):
                return "SANDBOX DENIED: outbound network commands are disabled in this workspace."
            if self._shell_may_escape(command):
                return f"SANDBOX DENIED: shell command may escape workspace {self.root}."
        return None

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path.resolve() if path.is_absolute() else (self.root / path).resolve()

    def _contains(self, path: Path) -> bool:
        try:
            path.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _shell_may_escape(self, command: str) -> bool:
        if _matches(command, NESTED_SHELL_PATTERNS):
            return True
        if re.search(r"(^|[;&|]\s*)cd\s+(?:\.\.|/|~)", command):
            return True
        try:
            tokens = shlex.split(command)
        except ValueError:
            return True
        for token in tokens:
            if (
                token.startswith(("/", "~"))
                or token == ".."
                or token.startswith("../")
                or "/../" in token
            ):
                return True
        return False


ApprovalCallback = Callable[[str, dict[str, Any], str], bool]


class SafeToolExecutor:
    """Sandbox → permission decision → optional human approval → execution."""

    def __init__(
        self,
        workspace: str | Path,
        mode: ApprovalMode | str = ApprovalMode.NORMAL,
        approve: ApprovalCallback | None = None,
        allow_network: bool = False,
        allow_unsafe_shell: bool = False,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.gate = PermissionGate(mode)
        self.sandbox = WorkspaceSandbox(self.workspace, allow_network=allow_network)
        self.approve = approve or terminal_approval
        self.allow_unsafe_shell = allow_unsafe_shell

    def execute(self, tool: str, arguments: dict[str, Any]) -> str:
        if tool == "bash" and not self.allow_unsafe_shell:
            return (
                "SANDBOX DENIED: bash is disabled because this educational "
                "string-matching policy is not OS-level isolation. Run inside "
                "a container/VM, or explicitly enable supervised demo mode."
            )
        sandbox_error = self.sandbox.validate(tool, arguments)
        if sandbox_error:
            return sandbox_error
        decision = self.gate.decide(tool, arguments)
        reason = self.gate.reason(tool, arguments, decision)
        if decision is Decision.DENY:
            return f"PERMISSION DENIED: {reason}. Choose a safer action."
        prefix = ""
        if decision is Decision.ASK:
            if not self.approve(tool, arguments, reason):
                return "PERMISSION DENIED BY USER: action was not executed. Choose a safer alternative or explain why it is needed."
            prefix = "APPROVED BY USER\n"
        return prefix + execute_tool(tool, arguments, cwd=self.workspace)


def terminal_approval(tool: str, arguments: dict[str, Any], reason: str) -> bool:
    print("\n" + "!" * 72)
    print("PERMISSION GATE: human judgment required")
    print(f"Tool:   {tool}")
    print(f"Input:  {arguments}")
    print(f"Reason: {reason}")
    answer = input("Run this action? [y/N] ").strip().lower()
    return answer in {"y", "yes"}
