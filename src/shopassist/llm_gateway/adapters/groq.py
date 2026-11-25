"""Groq single-dispatch Gateway adapter using its OpenAI-compatible REST API."""
from shopassist.llm_gateway.adapters.chat_completion import ChatCompletionAdapter


class GroqAdapter(ChatCompletionAdapter):
    kind = "groq"
