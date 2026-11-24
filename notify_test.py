"""Notification channel tests. Run: python notify_test.py

No real credentials and no real sends: urlopen is stubbed, so this exercises
request construction, the Markdown fallback, chunking and error handling
offline and deterministically.
"""
import json
import urllib.error
import urllib.request
from io import BytesIO

import notify

CALLS = []


class _Resp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def install_stub(behaviour):
    """behaviour(params) -> payload dict, or raises HTTPError."""
    CALLS.clear()

    def fake_urlopen(req, timeout=None):
        import urllib.parse as up
        # GET calls (getMe, getUpdates) have no body.
        raw = req.data.decode() if req.data else ""
        params = dict(up.parse_qsl(raw, keep_blank_values=True))
        CALLS.append({"url": req.full_url, **params})
        return _Resp(behaviour(params))

    urllib.request.urlopen = fake_urlopen


_real_urlopen = urllib.request.urlopen


def http_error(code, description):
    body = json.dumps({"ok": False, "error_code": code,
                       "description": description}).encode()
    return urllib.error.HTTPError("u", code, description, {}, BytesIO(body))


TOKEN, CHAT = "11111:FAKE-TOKEN", "4242"
tg = notify.TelegramNotifier(token=TOKEN, chat_id=CHAT)

# ------------------------------------------------------- happy path
install_stub(lambda p: {"ok": True, "result": {}})
tg.send("Leave expires soon", title="PTO-Hacker · expiry")
assert len(CALLS) == 1, CALLS
c = CALLS[0]
assert c["url"].endswith("/sendMessage") and TOKEN in c["url"]
assert c["chat_id"] == CHAT
assert c["parse_mode"] == "Markdown"
assert c["text"].startswith("*PTO-Hacker") and "expires soon" in c["text"]
print("happy path: one POST, correct chat, Markdown, title bolded")

# ------------------------------- the real bug: user text breaks Markdown
# A commitment label like "Anu_wedding" makes Telegram 400 the whole message.
state = {"n": 0}


def flaky(params):
    state["n"] += 1
    if params.get("parse_mode") == "Markdown":
        raise http_error(400, "Bad Request: can't parse entities: Can't find "
                              "end of Italic entity at byte offset 42")
    return {"ok": True, "result": {}}


install_stub(flaky)
tg.send("Break *25 Dec* — Anu_wedding trip")
assert len(CALLS) == 2, f"expected a retry, got {len(CALLS)} call(s)"
assert CALLS[0]["parse_mode"] == "Markdown"
assert "parse_mode" not in CALLS[1], "retry must send no parse_mode at all"
assert CALLS[1]["text"] == CALLS[0]["text"], "retry must keep the same content"
print("markdown fallback: 400 on parse -> resent as plain text, same content")

# ------------------------------- a non-parse 400 must NOT be retried
install_stub(lambda p: (_ for _ in ()).throw(
    http_error(400, "Bad Request: chat not found")))
try:
    tg.send("hi")
    raise AssertionError("should have raised")
except notify.NotifyError as e:
    assert "chat not found" in str(e)
assert len(CALLS) == 1, "a non-parse error must not trigger a pointless retry"
print("non-parse 400: surfaced immediately, no retry")

# ------------------------------- ok:false in a 200 body
install_stub(lambda p: {"ok": False, "description": "bot was blocked by the user"})
try:
    tg.send("hi")
    raise AssertionError("should have raised")
except notify.NotifyError as e:
    assert "blocked" in str(e)
print("ok:false in a 200 body: treated as failure")

# ------------------------------- long messages are split on line boundaries
install_stub(lambda p: {"ok": True, "result": {}})
long_text = "\n".join(f"line {i} " + "x" * 60 for i in range(200))
tg.send(long_text)
assert len(CALLS) > 1, "a >4096 char message must be split"
assert all(len(c["text"]) <= notify.TelegramNotifier.MAX_LEN for c in CALLS)
assert not any(c["text"].startswith("x") for c in CALLS), "split mid-line"
print(f"chunking: {len(CALLS)} parts, all within the 4096 limit, split on newlines")

# ------------------------------- config + registry
assert not notify.TelegramNotifier(token="", chat_id="").configured
try:
    notify.TelegramNotifier(token="", chat_id="").send("x")
    raise AssertionError("should have raised")
except notify.NotifyError:
    pass
assert notify.get_notifier("console").name == "console"
assert notify.get_notifier("none").name == "none"
notify.get_notifier("none").send("goes nowhere")
try:
    notify.get_notifier("pigeon")
    raise AssertionError("should have raised")
except ValueError:
    pass
print("config: unconfigured raises, registry resolves, unknown channel rejected")

# ------------------------------- retries: 429 and transient network errors
SLEPT = []
notify._sleep = SLEPT.append              # never really sleep in tests


def rate_limited_then_ok(n_limits, retry_after=2):
    state = {"n": 0}

    def behaviour(params):
        state["n"] += 1
        if state["n"] <= n_limits:
            raise urllib.error.HTTPError(
                "u", 429, "Too Many Requests", {},
                BytesIO(json.dumps({
                    "ok": False, "description": "Too Many Requests",
                    "parameters": {"retry_after": retry_after},
                }).encode()))
        return {"ok": True, "result": []}

    return behaviour


SLEPT.clear()
install_stub(rate_limited_then_ok(1))
out = notify._api_call("tok", "getUpdates")
assert out["ok"] and len(CALLS) == 2, CALLS
assert SLEPT == [3], f"should wait retry_after+1, slept {SLEPT}"
print("429: honours the server's retry_after, then succeeds")

SLEPT.clear()
install_stub(rate_limited_then_ok(99))
try:
    notify._api_call("tok", "getUpdates")
    raise AssertionError("should have raised")
except notify.NotifyError as e:
    assert "rate limited, not a bad token" in str(e)
assert len(CALLS) == notify.MAX_RETRIES, f"bounded retries, got {len(CALLS)}"
print(f"429 forever: gives up after {notify.MAX_RETRIES}, says it is not the token")

SLEPT.clear()
install_stub(rate_limited_then_ok(1, retry_after=notify.MAX_WAIT + 10))
try:
    notify._api_call("tok", "getUpdates")
    raise AssertionError("should have raised")
except notify.NotifyError:
    pass
assert SLEPT == [], "must not sleep longer than MAX_WAIT"
print("429 with an absurd retry_after: refuses to wait, does not wedge the daemon")

flaky_state = {"n": 0}


def flaky_network(params):
    flaky_state["n"] += 1
    if flaky_state["n"] == 1:
        raise TimeoutError("The read operation timed out")
    return {"ok": True, "result": []}


SLEPT.clear()
install_stub(flaky_network)
assert notify._api_call("tok", "getMe")["ok"], "should recover from one timeout"
assert len(CALLS) == 2 and SLEPT == [1]
print("timeout: retried with backoff, then succeeded")

SLEPT.clear()
install_stub(lambda p: (_ for _ in ()).throw(TimeoutError("timed out")))
try:
    notify._api_call("tok", "getMe")
    raise AssertionError("should have raised")
except notify.NotifyError as e:
    assert "unreachable" in str(e) and "api.telegram.org" in str(e)
print("timeout forever: clear 'unreachable' message, not a bogus token error")

# ------------------------------- non-retryable statuses surface immediately
install_stub(lambda p: (_ for _ in ()).throw(http_error(401, "Unauthorized")))
try:
    notify._api_call("tok", "getMe")
    raise AssertionError("should have raised")
except notify.ApiError as e:
    assert e.code == 401 and "Unauthorized" in e.description
assert len(CALLS) == 1, "a 401 must not be retried"
print("401: raised at once as ApiError, no retry")

# This is the path that had a NameError: discover_chat_id -> _explain
install_stub(lambda p: (_ for _ in ()).throw(http_error(401, "Unauthorized")))
try:
    notify.discover_chat_id("tok")
    raise AssertionError("should have raised")
except notify.NotifyError as e:
    assert "401" in str(e) and "@BotFather" in str(e), str(e)
print("discover_chat_id: turns a 401 into advice, not a stack trace")

for code, must_contain in ((401, "BotFather"), (404, "malformed"),
                           (409, "deleteWebhook"), (429, "not a bad token"),
                           (500, "500")):
    msg = notify._explain(code, {"description": "x"})
    assert must_contain in msg, f"{code}: {msg}"
print("explanations: every status says what to actually do about it")

urllib.request.urlopen = _real_urlopen

# ------------------------------- .env loading (host runs, not just Docker)
import os          # noqa: E402
import tempfile    # noqa: E402
from pathlib import Path  # noqa: E402

import envfile     # noqa: E402

_tmp = Path(tempfile.mkdtemp(prefix="ptohacker-env-")) / ".env"
_tmp.write_text(
    "# a comment\n"
    "\n"
    "PTOHACKER_NOTIFY=telegram\n"
    'export PTOHACKER_TELEGRAM_TOKEN="quoted-token"\n'
    "PTOHACKER_TELEGRAM_CHAT_ID='4242'\n"
    "PTOHACKER_ALREADY_SET=from-file\n"
    "malformed line with no equals\n",
    encoding="utf-8",
)
for _k in ("PTOHACKER_NOTIFY", "PTOHACKER_TELEGRAM_TOKEN",
           "PTOHACKER_TELEGRAM_CHAT_ID"):
    os.environ.pop(_k, None)

# "Real environment" means set BEFORE the process started, which envfile
# snapshots at import. Set it first, then reload so the snapshot includes it.
os.environ["PTOHACKER_ALREADY_SET"] = "from-real-env"
import importlib  # noqa: E402
importlib.reload(envfile)

_n = envfile.load(_tmp)
assert os.environ["PTOHACKER_NOTIFY"] == "telegram"
assert os.environ["PTOHACKER_TELEGRAM_TOKEN"] == "quoted-token", "quotes stripped"
assert os.environ["PTOHACKER_TELEGRAM_CHAT_ID"] == "4242", "single quotes stripped"
assert os.environ["PTOHACKER_ALREADY_SET"] == "from-real-env", \
    "a real environment variable must beat the file"
assert envfile.load(_tmp.parent / "nope.env") == 0, "a missing file is not an error"
print(f".env: {_n} vars loaded, quotes stripped, real env wins, junk ignored")

# ---- regression: an empty value must not be cached forever ----------------
# Streamlit re-runs the script on every interaction. The app was started while
# the token line in .env was still blank; a "skip keys already in os.environ"
# rule then pinned the empty string, so filling the token in and refreshing
# left the UI reporting "not configured" while the CLI worked.
_tmp2 = Path(tempfile.mkdtemp(prefix="ptohacker-env2-")) / ".env"
_tmp2.write_text("PTOHACKER_DEMO_TOKEN=\n", encoding="utf-8")
os.environ.pop("PTOHACKER_DEMO_TOKEN", None)
envfile.load(_tmp2)
assert os.environ["PTOHACKER_DEMO_TOKEN"] == "", "blank should load as blank"

_tmp2.write_text("PTOHACKER_DEMO_TOKEN=filled-in-later\n", encoding="utf-8")
envfile.load(_tmp2)                      # same process, as a Streamlit rerun does
assert os.environ["PTOHACKER_DEMO_TOKEN"] == "filled-in-later", \
    "editing .env must take effect on the next load, not require a restart"
print(".env: a blank value is refreshed once filled in (no restart needed)")

print("\nALL NOTIFY CHECKS PASSED")
