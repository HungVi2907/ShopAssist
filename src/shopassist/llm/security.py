"""Small diagnostic redaction boundary; raw provider messages are not public output."""
import re


def redact(message: str, api_key: str | None = None) -> str:
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"AIza[\w-]{20,}", "[REDACTED]", message)
    return re.sub(r"(?i)((?:api[_-]?key|key|authorization)\s*[=:]\s*)([^\s&,'\"}]+)", r"\1[REDACTED]", message)
