"""Stage 1: an LLM can answer, but it cannot inspect your machine."""

from harness import OpenRouterClient, text_of

client = OpenRouterClient()
request = (
    "Read the local file secret.txt and tell me exactly what it contains. "
    "If you cannot access it, say so plainly. Do not guess."
)
reply = client.complete([{"role": "user", "content": request}])
print(text_of(reply))
