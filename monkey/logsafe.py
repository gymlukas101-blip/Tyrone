"""Logs the owner may send for help must not carry secrets or private links.

httpx logs every request URL at INFO, which includes `?key=...` API keys and the owner's private calendar (ICS) links.
Chatty HTTP loggers are turned down to WARNING, and every record passes a redaction filter as a second line of
defence (keys, tokens, bearer headers, private calendar links, email addresses)."""
from __future__ import annotations

import logging
import re

_PATTERNS = [
    # Query-string secrets (?key=…&token=…) and the named token fields anywhere; plain "code=1" stays readable.
    (re.compile(r"(?i)([?&](?:api[_-]?key|key|token|access_token|refresh_token|id_token|code|client_secret|"
                r"password|pwd|sig|signature|auth)=)([^&\s\"'#]+)"), r"\1[redacted]"),
    (re.compile(r"(?i)\b((?:access|refresh|id)_token|client_secret|api_key|token|secret|password)(\s*[=:]\s*[\"']?)"
                r"([^\s\"'&,}]+)"), r"\1\2[redacted]"),
    (re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}"), "Bearer [redacted]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}"), "sk-ant-[redacted]"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}"), "[redacted-google-key]"),
    (re.compile(r"(?i)\bhttps?://[^\s\"']*(?:/feeds/|private-|/ical/|\.ics\b|calendar/ical)[^\s\"']*"),
     "[private calendar link]"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[email]"),
]
QUIET = ("httpx", "httpcore", "urllib3", "googleapiclient.discovery", "googleapiclient.discovery_cache",
         "google_auth_httplib2", "anthropic._base_client", "websockets")


def redact(text: str) -> str:
    for rx, rep in _PATTERNS:
        text = rx.sub(rep, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, ()
        if record.exc_info and not record.exc_text:
            # Formatters fill exc_text *after* filters run: format the traceback here so it is redacted too.
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
            record.exc_info = None                 # the redacted text is what gets written
        return True


def install(handlers: list[logging.Handler]) -> None:
    f = RedactingFilter()
    for h in handlers:
        h.addFilter(f)
    for name in QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
