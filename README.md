# Vizuara Agentic Harness Engineering

An agentic harness built from scratch, one layer at a time. No agent framework and no hidden runtime. The only remote dependency is an LLM reached through OpenRouter's HTTP API.

## Current lesson

This first checkpoint isolates the two ideas we want to teach:

1. **A bare LLM call** can produce text but cannot touch the external world.
2. **An agent loop** lets the model request an action, lets our code perform it, feeds the observation back, and asks the model what to do next.

The repository will later grow tools, context management, durability, and subagents. They are intentionally absent today.

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
