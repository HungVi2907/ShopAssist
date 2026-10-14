"""HTTP API clients for ShopAssist Telegram Bot."""

from shopassist.bot.clients.recommendation import (
    BackendConnectionError,
    BackendResponseError,
    BackendSchemaError,
    BackendTimeoutError,
    FastAPIRecommendationClient,
)

__all__ = [
    "BackendConnectionError",
    "BackendResponseError",
    "BackendSchemaError",
    "BackendTimeoutError",
    "FastAPIRecommendationClient",
]
