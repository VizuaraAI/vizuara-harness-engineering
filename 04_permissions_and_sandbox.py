"""Module 3: the harness—not the model—decides whether an action runs."""

from pathlib import Path

from harness import run_agent
from safety import ApprovalMode, SafeToolExecutor

workspace = Path("safety_demo_workspace")
workspace.mkdir(exist_ok=True)
(workspace / "keep.txt").write_text("This file should survive a refusal.\n", encoding="utf-8")
(workspace / "trash.tmp").write_text("Temporary data.\n", encoding="utf-8")

print("WORKSPACE:", workspace.resolve())
print("APPROVAL MODE: normal")
print("Read/search actions are allowed. Writes and risky shell commands ask.")
print("A catastrophic command is denied, and paths outside the workspace are sandbox-denied.")

SYSTEM_PROMPT = """
You are a coding agent operating through a real tool-calling API.
When the user asks for an action, call the supplied tool; never print JSON that
merely describes a call, and never invent or simulate a tool result. Make exactly
one tool call per turn when requested. The harness—not you—executes tools,
applies permissions, and returns observations. Continue after refusal or error.
""".strip()

executor = SafeToolExecutor(
    workspace,
    mode=ApprovalMode.NORMAL,
    allow_network=False,
    allow_unsafe_shell=True,  # supervised classroom demo only
)
request = """
Teach the permission gate with one tool call per turn:
1. Use ls to inspect this workspace. It should be allowed automatically.
2. Use bash with `rm trash.tmp`. The harness should ask the human.
3. After the tool result, use read on keep.txt and report whether it survived.
4. Try write with path ../escaped.txt and content `escape attempt`. The sandbox should deny it.
5. Finish by explaining which decisions came from the model and which came from the harness.
Do not combine tool calls. A refusal or sandbox error is an observation, not a crash.
""".strip()

print(
    "\nFINAL ANSWER:\n",
    run_agent(
        request,
        cwd=workspace,
        executor=executor,
        max_turns=8,
        show_state=True,
        system_prompt=SYSTEM_PROMPT,
    ),
)
