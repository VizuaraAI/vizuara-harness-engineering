"""Stage 2: the same model, now inside a loop with one tiny tool."""

from harness import run_agent

print(run_agent("Read secret.txt and tell me exactly what it contains."))
