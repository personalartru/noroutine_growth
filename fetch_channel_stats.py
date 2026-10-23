#!/usr/bin/env python3
"""
Сбор статистики просмотров постов MAX-канала для отображения в админке.
Выводит JSON с данными о постах (просмотры, текст, timestamp, URL).
"""

import os
import sys
import json
import requests
from datetime import datetime

MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN")
CHANNEL_ID = os.environ.get("MAX_CHANNEL_ID", "-71062363105923")


def call(method, path, query=None):
    """Вызов MAX Bot API."""
    url = f"https://platform-api2.max.ru/{path}"
    headers = {"Authorization": MAX_BOT_TOKEN}
    r = requests.request(method, url, params=query, headers=headers, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
    return r.json()


def get_channel_stats(count=50):
    """Получить статистику постов канала."""
    try:
        resp = call("GET", "messages", query={"chat_id": CHANNEL_ID, "count": count})
        messages = resp.get("messages", [])
        stats = []
        
        for msg in messages:
            stat = msg.get("stat", {})
            body = msg.get("body", {})
            text = (body.get("text") or "")[:150]
            timestamp_ms = msg.get("timestamp", 0)
            timestamp_dt = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M")
            
            stats.append({
                "url": msg.get("url", ""),
                "timestamp": timestamp_ms,
                "datetime": timestamp_dt,
                "views": stat.get("views", 0),
                "text": text
            })
        
        return stats
    except RuntimeError as e:
        print(f"Ошибка получения статистики: {e}", file=sys.stderr)
        return []


def main():
    if not MAX_BOT_TOKEN:
        print(json.dumps({"error": "MAX_BOT_TOKEN не установлен"}))
        sys.exit(1)

    count = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    stats = get_channel_stats(count)
    
    result = {
        "channel_id": CHANNEL_ID,
        "total_posts": len(stats),
        "total_views": sum(s["views"] for s in stats),
        "posts": stats
    }
    
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
