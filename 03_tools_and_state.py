"""Module 2: seven tools, multiple turns, and the message array growing live."""

from pathlib import Path

from harness import run_agent

workspace = Path("tool_demo_workspace")
workspace.mkdir(exist_ok=True)

request = """
Work only inside the supplied workspace and complete this exact sequence one tool
call at a time so the class can observe at least ten turns:

1. Use ls to inspect the workspace.
2. Use write to create notes.txt with exactly `alpha\nbeta\ngamma\n` (including the final newline).
3. Use read to inspect notes.txt.
4. Use edit to replace the exact line beta with BETA-EDITED.
5. Use grep to search the workspace for BETA-EDITED.
6. Use find to locate every .txt file.
7. Use bash to run: wc -l notes.txt
8. Deliberately use read on missing.txt. Do not guess its contents.
9. After receiving the error, use ls to recover by checking what exists.
10. Use read on the real notes.txt and verify the edit.
11. Only then give a short final summary.

Do not combine calls. Make exactly one tool call per turn and follow the numbered
order. Tool errors are observations: append them to memory, reason from them, and
continue rather than stopping.
""".strip()

print("WORKSPACE:", workspace.resolve())
print("USER REQUEST:\n", request)
print("\nWatch the message array grow after every assistant and tool message.")
print("\nFINAL ANSWER:\n", run_agent(request, cwd=workspace, max_turns=15, show_state=True))
