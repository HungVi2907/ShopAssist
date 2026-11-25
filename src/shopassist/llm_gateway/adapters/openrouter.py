"""OpenRouter single-dispatch Gateway adapter."""
from shopassist.llm_gateway.adapters.chat_completion import ChatCompletionAdapter


class OpenRouterAdapter(ChatCompletionAdapter):
    kind = "openrouter"
