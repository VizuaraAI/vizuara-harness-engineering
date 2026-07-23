"""Module 4: make context visibly grow, compact, and reload durable memory."""

from pathlib import Path

from context_engine import ContextEngine, count_tokens, load_memory, remember
from harness import OpenRouterClient, run_agent

workspace = Path("context_demo_workspace")
workspace.mkdir(exist_ok=True)
memory_path = workspace / "AGENT_MEMORY.md"
client = OpenRouterClient()

print("PHASE 1 — COMPACTION: old clutter becomes meeting minutes")
synthetic = [{"role": "system", "content": "You are a coding agent."}]
for turn in range(1, 9):
    synthetic.append(
        {
            "role": "user" if turn % 2 else "assistant",
            "content": f"turn {turn}: " + ("large raw tool output and repeated detail " * 100),
        }
    )
print(f"Before: {count_tokens(synthetic):,} estimated tokens in {len(synthetic)} messages")
engine = ContextEngine(compact_at=250, keep_recent=2, memory_path=memory_path, summary_client=client)
compacted = engine.compact(synthetic)
print(f"After:  {count_tokens(compacted):,} estimated tokens in {len(compacted)} messages")
print("Recent messages preserved verbatim:", compacted[-2:] == synthetic[-2:])
print("Summary preview:", compacted[1]["content"][:500])

print("\nPHASE 2 — MEMORY: write a durable project fact")
print(remember("The classroom test command is python3 -m unittest discover -s tests -v.", memory_path))
print("Memory file now contains:\n", load_memory(memory_path))

print("\nPHASE 3 — NEW SESSION: start with an empty conversation but load the notebook")
new_session_engine = ContextEngine(
    compact_at=4_000,
    keep_recent=4,
    memory_path=memory_path,
    summary_client=client,
)
answer = run_agent(
    "What is the classroom test command? Answer from project memory; do not use a tool.",
    client=client,
    cwd=workspace,
    context_engine=new_session_engine,
    max_turns=2,
    show_state=True,
)
print("\nFINAL ANSWER:\n", answer)
print("\nThe new process-level conversation began fresh; the fact survived on disk.")
