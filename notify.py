"""Notification channels.

Same shape as flights.FareProvider: an interface plus swappable backends, so
the jobs never know or care where a message goes.

Telegram is the default channel on purpose. Outbound email from a VPS is
genuinely hard -- most providers block port 25, and a fresh IP has no sending
reputation, so digests land in spam. Telegram needs a bot token and nothing
else, and it arrives instantly on the phone, which also makes it the better
thing to show in a live demo.

Configure with environment variables:
    PTOHACKER_NOTIFY=telegram|console|none
    PTOHACKER_TELEGRAM_TOKEN=123456:ABC...
    PTOHACKER_TELEGRAM_CHAT_ID=987654321
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

TELEGRAM_API = "https://api.telegram.org"


class NotifyError(RuntimeError):
    """Delivery failed. Jobs log this and carry on -- a failed send must never
    lose the work the job already did."""


class Notifier(ABC):
    name = "abstract"

    @abstractmethod
    def send(self, text: str, title: str | None = None) -> None:
        ...

    @property
    def configured(self) -> bool:
        return True


class ConsoleNotifier(Notifier):
    """Prints instead of sending. The default, so nothing is ever silently
    dropped into the void when no channel is set up."""

    name = "console"

    def send(self, text: str, title: str | None = None) -> None:
        if title:
            print(f"\n=== {title} ===")
        print(text)


class NullNotifier(Notifier):
    name = "none"

    def send(self, text: str, title: str | None = None) -> None:
        pass


class TelegramNotifier(Notifier):
    """Posts to the Telegram Bot API. Stdlib only -- no `requests` needed.

    Setup:
      1. Message @BotFather, /newbot, copy the token.
      2. Message your new bot once (bots cannot start conversations).
      3. Visit https://api.telegram.org/bot<TOKEN>/getUpdates and read
         result[0].message.chat.id -- that is your chat id.
    """

    name = "telegram"
    MAX_LEN = 4096  # Telegram's hard limit per message

    def __init__(self, token: str | None = None, chat_id: str | None = None,
                 timeout: int = 15):
        self.token = token or os.environ.get("PTOHACKER_TELEGRAM_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("PTOHACKER_TELEGRAM_CHAT_ID", "")
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str, title: str | None = None) -> None:
        if not self.configured:
            raise NotifyError(
                "Telegram is not configured: set PTOHACKER_TELEGRAM_TOKEN and "
                "PTOHACKER_TELEGRAM_CHAT_ID."
            )
        body = f"*{_escape(title)}*\n\n{text}" if title else text
        for chunk in _split(body, self.MAX_LEN):
            try:
                self._post(chunk, markdown=True)
            except _MarkdownRejected:
                # Messages interpolate text the USER typed -- commitment labels
                # ("Anu_wedding"), watchlist notes, company holiday names. One
                # stray _ * or [ makes Telegram reject the entire message with
                # 400, so a leave reminder would silently never arrive. Rather
                # than try to escape every path, resend it unformatted: plain
                # text always parses, and a message without bold beats no
                # message at all.
                self._post(chunk, markdown=False)

    def _post(self, text: str, markdown: bool = True) -> None:
        fields = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
        if markdown:
            # Omitted entirely on the retry -- an empty parse_mode is ambiguous.
            fields["parse_mode"] = "Markdown"
        try:
            payload = _api_call(self.token, "sendMessage", fields,
                                timeout=self.timeout)
        except ApiError as exc:
            if markdown and exc.code == 400 and _is_parse_error(exc.description):
                raise _MarkdownRejected() from None
            # _explain never includes the token, so this is safe to log.
            raise NotifyError(_explain(exc.code, exc.body)) from None
        if not payload.get("ok"):
            if markdown and _is_parse_error(json.dumps(payload)):
                raise _MarkdownRejected()
            raise NotifyError(f"Telegram rejected the message: {payload}")


class _MarkdownRejected(Exception):
    """Internal: Telegram could not parse our formatting. Retry as plain text."""


class ApiError(Exception):
    """A non-retryable HTTP error from Telegram, with the body already read.

    Carrying the decoded body matters: an HTTPError's stream can only be read
    once, and two layers both wanting to inspect it is how you get an empty
    error message.
    """

    def __init__(self, code: int, body: dict):
        self.code = code
        self.body = body or {}
        self.description = str(self.body.get("description", ""))
        super().__init__(f"Telegram HTTP {code}: {self.description}")


def _is_parse_error(detail: str) -> bool:
    low = detail.lower()
    return "parse" in low or "entity" in low or "entities" in low


def _escape(s: str) -> str:
    for ch in ("_", "*", "`", "["):
        s = s.replace(ch, "\\" + ch)
    return s


def _split(text: str, limit: int) -> list[str]:
    """Split on line boundaries so a long digest is not cut mid-word."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > limit:
            out.append(cur)
            cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out


CHANNELS = {
    "telegram": TelegramNotifier,
    "console": ConsoleNotifier,
    "none": NullNotifier,
}


def get_notifier(name: str | None = None) -> Notifier:
    name = (name or os.environ.get("PTOHACKER_NOTIFY", "console")).strip().lower()
    try:
        return CHANNELS[name]()
    except KeyError:
        raise ValueError(
            f"Unknown channel {name!r}. Known: {', '.join(sorted(CHANNELS))}."
        ) from None

def discover_chat_id(token: str | None = None, timeout: int = 15) -> list[dict]:
    """Ask Telegram who has messaged this bot, so you need not read raw JSON.

    Returns [{chat_id, name, text}, ...], most recent first. Empty means nobody
    has messaged the bot yet -- bots cannot start a conversation, so you must
    send it something first.
    """
    token = token or os.environ.get("PTOHACKER_TELEGRAM_TOKEN", "")
    if not token:
        raise NotifyError("No token: set PTOHACKER_TELEGRAM_TOKEN first.")
    try:
        payload = _api_call(token, "getUpdates", timeout=timeout)
    except ApiError as exc:
        raise NotifyError(_explain(exc.code, exc.body)) from None
    if not payload.get("ok"):
        raise NotifyError(f"Telegram said no: {payload.get('description', payload)}")

    seen, out = set(), []
    for update in reversed(payload.get("result", [])):
        msg = update.get("message") or update.get("channel_post") or {}
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None or cid in seen:
            continue
        seen.add(cid)
        name = (chat.get("title")
                or " ".join(filter(None, (chat.get("first_name"),
                                          chat.get("last_name"))))
                or chat.get("username") or "?")
        out.append({"chat_id": cid, "name": name, "text": (msg.get("text") or "")[:40]})
    return out

def _explain(code: int, body: dict) -> str:
    """Turn a Telegram error into something actionable.

    Lumping every status into "is the token right?" sent me chasing a bad token
    when the real answer was a rate limit -- the status codes mean genuinely
    different things and the fix differs for each.
    """
    body = body or {}
    desc = str(body.get("description", ""))
    retry = (body.get("parameters") or {}).get("retry_after")

    if code == 401:
        return ("Telegram 401 Unauthorized -- the bot token is wrong or revoked. "
                "Re-copy it from @BotFather.")
    if code == 404:
        return ("Telegram 404 -- the token is malformed. It should look like "
                "123456789:AA... with the colon included.")
    if code == 409:
        return ("Telegram 409 Conflict -- something else is already polling this "
                "bot, or a webhook is set. Stop the other poller, or clear the "
                "webhook with /deleteWebhook.")
    if code == 429:
        wait = f" Retry in {retry}s." if retry else " Wait a minute and retry."
        return ("Telegram 429 Too Many Requests -- rate limited, not a bad token."
                f"{wait} {desc}").strip()
    return f"Telegram HTTP {code}: {desc}".strip()

MAX_RETRIES = 3
MAX_WAIT = 60

# Indirection so tests can replace the wait without patching stdlib time,
# and without a default argument that binds the original at import.
_sleep = time.sleep


def _api_call(token: str, method: str, fields: dict | None = None,
              timeout: int = 15) -> dict:
    """One Telegram API call, with bounded retries on the transient failures.

    Two things are worth retrying and nothing else:

      * **429** -- Telegram rate-limits per bot, so a digest colliding with a
        fare alert trips it. Giving up immediately would drop an alert for a
        condition that clears itself in seconds, so honour the server's own
        retry_after. Bounded, so a wedged bot can never stall the daemon.
      * **timeouts and connection errors** -- observed repeatedly against
        api.telegram.org from a flaky network. A daily digest should not be
        lost to one dropped read.

    Everything else (401, 404, 409, 400) is a real answer, not a blip: raised
    straight away as ApiError with the body already decoded.
    """
    url = f"{TELEGRAM_API}/bot{token}/{method}"
    data = urllib.parse.urlencode(fields).encode() if fields else None
    last_body: dict = {}
    last_net: str = ""

    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(url, data=data,
                                     method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8", "replace"))
            except Exception:
                body = {}
            if exc.code != 429:
                raise ApiError(exc.code, body) from None
            last_body = body
            wait = (body.get("parameters") or {}).get("retry_after")
            wait = int(wait) if isinstance(wait, (int, float)) else 1
            if attempt == MAX_RETRIES - 1 or wait > MAX_WAIT:
                break
            _sleep(wait + 1)
        except OSError as exc:            # timeouts, DNS, refused connections
            last_net = f"{type(exc).__name__}: {exc}"
            if attempt == MAX_RETRIES - 1:
                break
            _sleep(2 ** attempt)          # 1s, 2s

    if last_net:
        raise NotifyError(
            f"Telegram unreachable after {MAX_RETRIES} attempts ({last_net}). "
            "Check this machine can reach api.telegram.org."
        )
    raise NotifyError(_explain(429, last_body))

