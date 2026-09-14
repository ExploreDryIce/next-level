import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "ingestion"))

from log_redaction import RedactSecretsFilter, redact  # noqa: E402


def test_redacts_all_provider_key_params():
    url = ("https://api.eia.gov/v2/x/?api_key=AAAA1111BBBB&frequency=monthly "
           "https://api.openweathermap.org/data/2.5/weather?lat=1&appid=ZZZ999&units=imperial "
           "https://finnhub.io/api/v1/quote?symbol=SPY&token=tok_123 "
           "https://newsapi.org/v2/everything?q=x&apiKey=nk-1&pageSize=5 "
           "https://www.alphavantage.co/query?function=X&apikey=AV1")
    out = redact(url)
    for secret in ("AAAA1111BBBB", "ZZZ999", "tok_123", "nk-1", "AV1"):
        assert secret not in out
    assert "frequency=monthly" in out and "symbol=SPY" in out and "units=imperial" in out


def test_filter_rewrites_formatted_record():
    rec = logging.LogRecord("httpx", logging.INFO, __file__, 1, 'HTTP Request: GET %s "%s"',
                            ("https://x.io/q?api_key=SECRET1&a=1", "200 OK"), None)
    RedactSecretsFilter().filter(rec)
    assert "SECRET1" not in rec.getMessage() and "api_key=REDACTED" in rec.getMessage()
