# Vizuara Agentic Harness Engineering

An agentic harness built from scratch, one layer at a time. No agent framework and no hidden runtime. The only remote dependency is an LLM reached through OpenRouter's HTTP API.

## Current lesson

This first checkpoint isolates the two ideas we want to teach:

1. **A bare LLM call** can produce text but cannot touch the external world.
2. **An agent loop** lets the model request an action, lets our code perform it, feeds the observation back, and asks the model what to do next.

The repository now contains two incremental modules:

1. the bare LLM call and smallest loop;
2. a seven-tool coding toolbox with an observable message array.

Context management, durability, permissions, sandboxing, and subagents remain intentionally absent.

## Requirements

- Python 3.11+
- An OpenRouter API key

No Python packages are required; the client uses the standard library.

```bash
export OPENROUTER_API_KEY="your-key"
# Optional. The default is the simple open-weight model below.
export OPENROUTER_MODEL="openai/gpt-oss-20b:free"
```

## Demo 1 — the model has no hands

```bash
python3 01_bare_llm.py
```

The prompt asks for the contents of `secret.txt`, but the script sends only the prompt. The model should state that it cannot access the file. The file exists locally; it was simply never put in the model's context.

## Demo 2 — add one tool and a loop

```bash
python3 02_agent_loop.py
```

Expected shape:

```text
TURN 1: tool call
TURN 2: final answer
The launch code is ORANGE-KITE-27.
```

The model does **not** read the file. It emits a structured `read_file` request. `run_tool` performs the read, and `run_agent` appends the result before calling the model again.

## The loop

```text
user request
    ↓
call model
    ↓
tool call? ── no ──→ return final text
    │
   yes
    ↓
run tool in our code
    ↓
append observation to messages
    └──────────────→ call model again
```

## Test

```bash
python3 -m unittest discover -s tests -v
```

The tests use a fake model transport, so they do not spend API credits.

---

## Module 2 — tools as contracts

`tools.py` implements the seven native coding tools used by Pi-style harnesses:

| Tool | Model-facing job | Runtime action |
|---|---|---|
| `read` | Read a text file, with paging | Reads UTF-8 text and returns numbered lines |
| `write` | Create or completely overwrite a file | Creates parents and writes text |
| `edit` | Replace one exact, unique string | Validates uniqueness, then changes the file |
| `bash` | Execute a shell command | Runs a subprocess in the workspace |
| `grep` | Search inside files | Applies a regex or literal search |
| `find` | Search for files by glob | Recursively matches file paths |
| `ls` | List one directory | Returns immediate entries alphabetically |

Each tool is one `Tool` object with two halves:

```python
Tool(
    name="read",              # model reads this
    label="Read",             # human UI reads this
    description="...",        # model reads this
    parameters={...},          # model reads this JSON Schema
    execute=_read,             # only our harness runs this
)
```

`openrouter_tools()` serializes only `name`, `description`, and `parameters`.
The model never receives the Python `execute` function. After a model emits a
tool call, `execute_tool()` dispatches its name and arguments to that hidden
function.

### Run every tool locally without API credits

```bash
python3 -m unittest discover -s tests -p 'test_tools.py' -v
```

These tests create temporary directories and exercise real filesystem and shell
behavior. They do not call OpenRouter and do not modify your repository files.

### Run the message-state teaching test

```bash
python3 -m unittest discover -s tests -p 'test_teaching_loop.py' -v
```

### Run the complete test suite

```bash
python3 -m unittest discover -s tests -v
```

### Run the live 10+ turn tutorial

First configure OpenRouter:

```bash
export OPENROUTER_API_KEY="your-key"
export OPENROUTER_MODEL="openai/gpt-oss-20b:free"
```

Then run:

```bash
python3 03_tools_and_state.py
```

The model is instructed to perform one call per turn: `ls`, `write`, `read`,
`edit`, `grep`, `find`, `bash`, a deliberately failing `read`, recovery with
`ls`, and a final successful `read`. The terminal displays, after each append:

- the turn number;
- which tool the model selected from the contracts;
- the exact arguments it generated;
- the tool result appended by the harness;
- every message currently in the model's memory.

The demo changes files only inside `tool_demo_workspace/`. Remove and rerun it
for a clean classroom demonstration:

```bash
rm -rf tool_demo_workspace
python3 03_tools_and_state.py
```

> **Module boundary:** `03_tools_and_state.py` deliberately runs the naked
> toolbox so students can see why a safety layer is necessary. Module 3 adds the
> permission gate and workspace boundary around the same tools.

---

## Module 3 — permissions and sandboxing

`safety.py` places two independent defenses between a model request and tool
execution:

```text
model requests action
        ↓
workspace sandbox: is it contained?
        ↓
permission gate: ALLOW / ASK / DENY
        ↓
execute only if both defenses permit it
```

The model never approves itself. `PermissionGate` classifies the request, and
`SafeToolExecutor` either runs it, asks the human, or returns a refusal to the
message loop as a tool result.

Approval modes:

- `strict`: ask before every non-catastrophic action;
- `normal`: allow reads/searches, ask for writes and risky shell commands;
- `auto`: allow actions without asking, while sandbox denials still apply.

`SafeToolExecutor` disables arbitrary `bash` by default. The classroom demo opts
into `allow_unsafe_shell=True` only so students can watch the interactive gate;
that mode must remain supervised and is not containment.

Catastrophic patterns such as `sudo rm -rf /` are always denied. The workspace
sandbox rejects file paths outside its root, shell path escapes, and common
network commands when networking is disabled.

> This is an educational application-level policy boundary, not a hardened OS
> sandbox. It rejects direct path escapes, common network commands, environment
> paths, and opaque nested interpreters, but arbitrary shell syntax cannot be
> contained reliably with string matching. For hostile or unsupervised code, use
> a container/VM with filesystem, process, credential, and network isolation.

### Test Module 3 without API credits

```bash
python3 -m unittest discover -s tests -p 'test_safety.py' -v
```

### Run the interactive safety demo

```bash
export OPENROUTER_API_KEY="your-key"
export OPENROUTER_MODEL="openai/gpt-oss-20b:free"
rm -rf safety_demo_workspace
python3 04_permissions_and_sandbox.py
```

The model first uses an allowed read-only action. When it proposes deletion,
the harness prints the exact tool, inputs, and reason before asking:

```text
Run this action? [y/N]
```

Run once and answer `y`; reset and run again answering `n`. On refusal, the file
survives and the refusal is appended to the model's messages. A later attempt to
write `../escaped.txt` is denied by the sandbox regardless of approval mode.

---

## Module 4 — compaction and persistent memory

`context_engine.py` adds two kinds of memory:

- **compaction:** summarize old messages while preserving the most recent ones
  verbatim, keeping a long session under a configurable estimated-token budget;
- **persistent memory:** save concise durable facts in `AGENT_MEMORY.md` and
  load that notebook into the system message at the start of a new session.

The token count is intentionally a dependency-free estimate for teaching. It
shows growth and the compaction sawtooth; it is not provider billing telemetry.

### Test Module 4 without API credits

```bash
python3 -m unittest discover -s tests -p 'test_context_engine.py' -v
```

The tests prove that compaction:

- triggers only above budget;
- preserves the system message;
- preserves recent messages exactly;
- replaces old transcript clutter with a short summary;
- reduces estimated context size.

They also prove that memory survives a new `ContextEngine` instance and duplicate
facts are not written twice.

### Run the live context-engine demo

```bash
export OPENROUTER_API_KEY="your-key"
export OPENROUTER_MODEL="openai/gpt-oss-20b:free"
rm -rf context_demo_workspace
python3 05_context_engine.py
```

The demo has three phases:

1. builds a deliberately bloated transcript and prints its estimated token size;
2. asks the model for meeting minutes, then prints the smaller compacted size;
3. writes a durable fact, starts a fresh conversation, and answers from memory.

Inspect the notebook afterward:

```bash
cat context_demo_workspace/AGENT_MEMORY.md
```

### Run everything

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile *.py tests/*.py
```

Automated tests do not require an API key. Only numbered live demos call
OpenRouter.
