"""Keep provider credentials out of logs.

Found 2026-09-14: logs/feed-pull-error.log held ~1,800 lines with live EIA,
FRED, OpenWeatherMap, NewsAPI, AlphaVantage, Finnhub and NASA keys. httpx logs
every request URL at INFO, and these APIs take the key as a query parameter.
scrub_credentials() only cleaned the saved feed payloads, not the log.
"""

import logging
import re

_SECRET_PARAM = re.compile(
    r"(?i)([?&](?:api_?key|apikey|appid|token|access_?key|key|x-rapidapi-key|client_secret)=)[^&\s\"'#]+"
)


def redact(text: str) -> str:
    return _SECRET_PARAM.sub(r"\1REDACTED", text)


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


def install() -> None:
    """Silence per-request URL logging and redact anything that still slips through."""
    for name in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    root = logging.getLogger()
    for handler in root.handlers or []:
        if not any(isinstance(f, RedactSecretsFilter) for f in handler.filters):
            handler.addFilter(RedactSecretsFilter())
