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

> **Safety warning:** `bash`, `write`, and `edit` currently run without a
> permission gate or sandbox. That omission is deliberate for this teaching
> module; permissions and sandboxing are the next layer.
