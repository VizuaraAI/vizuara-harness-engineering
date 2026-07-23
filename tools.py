"""Seven small tools: each contract sits beside the code that executes it."""

from __future__ import annotations

import fnmatch
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from context_engine import DEFAULT_MEMORY_PATH, remember

Parameters = dict[str, Any]
Executor = Callable[[dict[str, Any], Path], str]
MAX_READ_LINES = 2_000
MAX_RESULTS = 100


@dataclass(frozen=True)
class Tool:
    """The contract the model reads and the implementation the harness runs."""

    name: str
    label: str
    description: str
    parameters: Parameters
    execute: Executor

    def openrouter_definition(self) -> dict[str, Any]:
        """Serialize only the contract half. Python callables cannot reach the model."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _object(properties: Parameters, required: list[str] | None = None) -> Parameters:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _path(cwd: Path, value: str = ".") -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (cwd / path).resolve()


def _display(path: Path, cwd: Path) -> str:
    try:
        return path.relative_to(cwd).as_posix()
    except ValueError:
        return str(path)


def _read(args: dict[str, Any], cwd: Path) -> str:
    path = _path(cwd, args["path"])
    if not path.is_file():
        return f"ERROR: no such file: {path}. Use ls or find to see what exists."
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        return f"ERROR: could not read {path}: {error}"
    offset = max(1, int(args.get("offset", 1)))
    limit = max(1, min(int(args.get("limit", MAX_READ_LINES)), MAX_READ_LINES))
    selected = lines[offset - 1 : offset - 1 + limit]
    output = "\n".join(f"{number}|{line}" for number, line in enumerate(selected, offset))
    next_offset = offset + len(selected)
    if next_offset <= len(lines):
        output += f"\n\n[Showing lines {offset}-{next_offset - 1} of {len(lines)}. Use offset={next_offset} to continue.]"
    return output


def _write(args: dict[str, Any], cwd: Path) -> str:
    path = _path(cwd, args["path"])
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
    except OSError as error:
        return f"ERROR: could not write {path}: {error}"
    return f"Wrote {len(args['content'].encode('utf-8'))} bytes to {_display(path, cwd)}"


def _edit(args: dict[str, Any], cwd: Path) -> str:
    path = _path(cwd, args["path"])
    if not path.is_file():
        return f"ERROR: no such file: {path}. Use ls or find to see what exists."
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return f"ERROR: could not read {path}: {error}"
    old = args["old_string"]
    count = content.count(old)
    if count != 1:
        return f"ERROR: old_string matched {count} times in {_display(path, cwd)}; it must match exactly once. Read the file and provide a unique string."
    try:
        path.write_text(content.replace(old, args["new_string"], 1), encoding="utf-8")
    except OSError as error:
        return f"ERROR: could not edit {path}: {error}"
    return f"Edited {_display(path, cwd)}"


def _bash(args: dict[str, Any], cwd: Path) -> str:
    timeout = args.get("timeout")
    try:
        result = subprocess.run(
            args["command"],
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=float(timeout) if timeout is not None else None,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {timeout} seconds"
    except OSError as error:
        return f"ERROR: could not execute command: {error}"
    output = result.stdout + result.stderr
    if result.returncode:
        output += f"\n[exit code: {result.returncode}]"
    return output.rstrip()


def _iter_files(root: Path):
    if root.is_file():
        yield root
        return
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
            yield path


def _grep(args: dict[str, Any], cwd: Path) -> str:
    root = _path(cwd, args.get("path", "."))
    if not root.exists():
        return f"ERROR: no such path: {root}. Use ls or find to see what exists."
    flags = re.IGNORECASE if args.get("ignore_case", False) else 0
    pattern = re.escape(args["pattern"]) if args.get("literal", False) else args["pattern"]
    try:
        regex = re.compile(pattern, flags)
    except re.error as error:
        return f"ERROR: invalid regular expression: {error}"
    glob = args.get("glob")
    limit = max(1, min(int(args.get("limit", MAX_RESULTS)), MAX_RESULTS))
    matches: list[str] = []
    for path in _iter_files(root):
        relative = _display(path, root if root.is_dir() else cwd)
        if glob and not fnmatch.fnmatch(relative, glob):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append(f"{_display(path, cwd)}:{number}:{line}")
                if len(matches) == limit:
                    return "\n".join(matches) + f"\n\n[Stopped at limit={limit}.]"
    return "\n".join(matches) or "No matches found."


def _find(args: dict[str, Any], cwd: Path) -> str:
    root = _path(cwd, args.get("path", "."))
    if not root.is_dir():
        return f"ERROR: no such directory: {root}. Use ls to see what exists."
    limit = max(1, min(int(args.get("limit", 1_000)), 1_000))
    pattern = args["pattern"]
    matches = [
        _display(path, root)
        for path in sorted(root.rglob("*"))
        if path.is_file()
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
        and (path.match(pattern) or fnmatch.fnmatch(_display(path, root), pattern))
    ]
    output = matches[:limit]
    if len(matches) > limit:
        output.append(f"[Stopped at limit={limit}; {len(matches) - limit} more results.]")
    return "\n".join(output) or "No files found."


def _ls(args: dict[str, Any], cwd: Path) -> str:
    root = _path(cwd, args.get("path", "."))
    if not root.is_dir():
        return f"ERROR: no such directory: {root}. Use find to search for it."
    limit = max(1, min(int(args.get("limit", 500)), 500))
    try:
        entries = sorted(root.iterdir(), key=lambda path: path.name.lower())
    except OSError as error:
        return f"ERROR: could not list {root}: {error}"
    names = [path.name + ("/" if path.is_dir() else "") for path in entries[:limit]]
    if len(entries) > limit:
        names.append(f"[Stopped at limit={limit}; {len(entries) - limit} more entries.]")
    return "\n".join(names) or "Directory is empty."


def _remember(args: dict[str, Any], cwd: Path) -> str:
    return remember(args["fact"], cwd / DEFAULT_MEMORY_PATH)


TOOLBOX = {
    tool.name: tool
    for tool in [
        Tool(
            "read",
            "Read",
            "Read a UTF-8 text file with line numbers. Output is limited to 2000 lines. Use offset and limit to page through large files; continue with the next offset shown in a truncated result.",
            _object(
                {
                    "path": {"type": "string", "description": "File path, relative to the workspace or absolute."},
                    "offset": {"type": "integer", "minimum": 1, "description": "First line to return, 1-indexed. Default: 1."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_READ_LINES, "description": "Maximum lines to return. Default: 2000."},
                },
                ["path"],
            ),
            _read,
        ),
        Tool(
            "write",
            "Write",
            "Create or completely overwrite a UTF-8 text file. Parent directories are created automatically. Use edit instead for a small change to an existing file.",
            _object(
                {
                    "path": {"type": "string", "description": "File path, relative to the workspace or absolute."},
                    "content": {"type": "string", "description": "Complete content to write."},
                },
                ["path", "content"],
            ),
            _write,
        ),
        Tool(
            "edit",
            "Edit",
            "Replace one exact, unique string in a UTF-8 text file. old_string must match exactly once, including whitespace. Read the file first when unsure; use write for complete rewrites.",
            _object(
                {
                    "path": {"type": "string", "description": "File path, relative to the workspace or absolute."},
                    "old_string": {"type": "string", "minLength": 1, "description": "Exact text to replace; it must be unique."},
                    "new_string": {"type": "string", "description": "Replacement text."},
                },
                ["path", "old_string", "new_string"],
            ),
            _edit,
        ),
        Tool(
            "bash",
            "Bash",
            "Run a shell command in the workspace and return stdout plus stderr. Use purpose-built read, grep, find, and ls tools when they express the task directly. The harness may require approval or deny the action.",
            _object(
                {
                    "command": {"type": "string", "minLength": 1, "description": "Shell command to execute."},
                    "timeout": {"type": "number", "minimum": 0.1, "description": "Optional timeout in seconds."},
                },
                ["command"],
            ),
            _bash,
        ),
        Tool(
            "grep",
            "Grep",
            "Search UTF-8 file contents with a regex or literal string. Returns matching file paths, line numbers, and lines. Use glob to narrow file types and find when searching by filename instead.",
            _object(
                {
                    "pattern": {"type": "string", "description": "Regular expression, or literal text when literal=true."},
                    "path": {"type": "string", "description": "File or directory to search. Default: current workspace."},
                    "glob": {"type": "string", "description": "Optional file glob such as '*.py' or '**/*.md'."},
                    "ignore_case": {"type": "boolean", "default": False, "description": "Case-insensitive search."},
                    "literal": {"type": "boolean", "default": False, "description": "Treat pattern as plain text, not regex."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_RESULTS, "description": "Maximum matches. Default: 100."},
                },
                ["pattern"],
            ),
            _grep,
        ),
        Tool(
            "find",
            "Find",
            "Find files by glob pattern and return paths relative to the search directory. Use grep when searching inside files and ls for one directory's immediate children.",
            _object(
                {
                    "pattern": {"type": "string", "description": "Glob such as '*.py', '**/*.json', or 'src/**/*.py'."},
                    "path": {"type": "string", "description": "Directory to search. Default: current workspace."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 1_000, "description": "Maximum results. Default: 1000."},
                },
                ["pattern"],
            ),
            _find,
        ),
        Tool(
            "ls",
            "List",
            "List one directory's immediate contents alphabetically, including dotfiles; directories end with '/'. Use find for recursive filename search.",
            _object(
                {
                    "path": {"type": "string", "description": "Directory to list. Default: current workspace."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500, "description": "Maximum entries. Default: 500."},
                }
            ),
            _ls,
        ),
        Tool(
            "remember",
            "Remember",
            "Save one short, durable project fact that should be available in future sessions. Store facts and stable rules only—not transcripts, temporary task state, or raw tool output.",
            _object(
                {
                    "fact": {
                        "type": "string",
                        "minLength": 1,
                        "description": "A concise fact worth loading at the start of a future task.",
                    }
                },
                ["fact"],
            ),
            _remember,
        ),
    ]
}


def openrouter_tools() -> list[dict[str, Any]]:
    return [tool.openrouter_definition() for tool in TOOLBOX.values()]


def execute_tool(name: str, arguments: dict[str, Any], cwd: str | Path = ".") -> str:
    """Dispatch the model's name and arguments to the hidden implementation."""
    tool = TOOLBOX.get(name)
    if tool is None:
        return f"ERROR: Unknown tool: {name}. Available tools: {', '.join(TOOLBOX)}"
    try:
        return tool.execute(arguments, Path(cwd).resolve())
    except (KeyError, TypeError, ValueError) as error:
        return f"ERROR: invalid arguments for {name}: {error}"
