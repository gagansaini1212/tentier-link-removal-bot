import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from telegram import Update

from bot import build_application, load_token


async def _handle_update(data: dict) -> None:
    token = load_token()
    application = build_application(token, webhook=True)
    async with application:
        update = Update.de_json(data, application.bot)
        if update is not None:
            await application.process_update(update)


async def _send_json(send, status: int, payload: dict) -> None:
    raw = json.dumps(payload).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(raw)).encode("ascii")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": raw})


async def app(scope, receive, send) -> None:
    if scope["type"] != "http":
        return
    method = scope.get("method", "GET")
    if method == "GET":
        await _send_json(send, 200, {"ok": True, "status": "webhook ready"})
        return
    if method != "POST":
        await _send_json(send, 405, {"ok": False, "error": "Method not allowed"})
        return

    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break

    try:
        data = json.loads(body.decode("utf-8") or "{}")
        await _handle_update(data)
        await _send_json(send, 200, {"ok": True})
    except Exception as exc:
        await _send_json(send, 500, {"ok": False, "error": str(exc)})
