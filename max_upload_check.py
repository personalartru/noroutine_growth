"""Проверка загрузки файла в MAX: формат /uploads и отправка вложения.

Запуск: python max_upload_check.py
"""
import os

import requests

MAX_API = os.environ.get("MAX_API_BASE", "https://platform-api2.max.ru")
TOKEN = os.environ["MAX_BOT_TOKEN"]
ADMIN_CHAT_ID = os.environ.get("MAX_ADMIN_CHAT_ID", "")
MATERIALS_PATH = os.environ.get("MATERIALS_PATH", "materials/noroutine-n8n-pack.zip")


def main():
    print("=== 1. POST /uploads?type=file (без файла) ===")  # диагностика формата
    r = requests.post(f"{MAX_API}/uploads", params={"type": "file"},
                      headers={"Authorization": TOKEN}, timeout=60)
    print("HTTP", r.status_code, r.text[:400])
    token = None
    upload_url = None
    if r.status_code == 200:
        data = r.json()
        token = data.get("token") or (data.get("result") or {}).get("token")
        upload_url = data.get("url")

    if not token and upload_url:
        print("\n=== 2. загрузка файла на upload-url ===")
        with open(MATERIALS_PATH, "rb") as f:
            r2 = requests.post(upload_url, headers={"Authorization": TOKEN},
                               files={"data": (os.path.basename(MATERIALS_PATH), f, "application/zip")},
                               timeout=180)
        print("HTTP", r2.status_code, r2.text[:400])
        if r2.status_code == 200:
            data2 = r2.json()
            token = (data2.get("token") or (data2.get("result") or {}).get("token")
                     or data.get("token") or (data.get("result") or {}).get("token"))

    print("\n=== 3. токен файла:", token, "===")
    if not token:
        print("Токен не получен — вложение собрать нельзя")
        return

    if not ADMIN_CHAT_ID:
        print("MAX_ADMIN_CHAT_ID не задан — отправку пропускаю")
        return

    print("\n=== 4. отправка архива в чат ===")
    r3 = requests.post(
        f"{MAX_API}/messages",
        params={"chat_id": ADMIN_CHAT_ID},
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},
        json={
            "text": "Проверка вложения: 5 готовых n8n-воркфлоу.",
            "format": "html",
            "notify": True,
            "attachments": [{"type": "file", "payload": {"token": token}}],
        },
        timeout=90,
    )
    print("HTTP", r3.status_code, r3.text[:300])


if __name__ == "__main__":
    main()
