"""Yandex Cloud Function: принимает вебхук и проксирует его в n8n."""
import base64
import hashlib
import hmac
import json
import os

import urllib.request

N8N_WEBHOOK_URL = os.environ["N8N_WEBHOOK_URL"]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")


def _signature(payload: bytes) -> str:
    digest = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return base64.b64encode(digest.encode()).decode()


def handler(event, context):
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    payload = json.dumps({"payload": body, "ts": event.get("headers", {}).get("X-Envoy-Original-Timestamp", "")})

    req = urllib.request.Request(
        N8N_WEBHOOK_URL,
        data=payload.encode(),
        headers={"Content-Type": "application/json", "X-Signature": _signature(payload.encode())},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return {"statusCode": resp.status, "body": resp.read().decode()[:500]}
