#!/usr/bin/env python3
"""
Сбор аналитики по обоим каналам (Telegram + MAX) с историей по дням.

Результат пишется в analytics.json, который отображается админкой
noroutine_posting (графики Chart.js, разбивка по каналам).

Telegram: просмотр постов берётся со страницы t.me/s/{username} (BOT API
просмотры постов канала не отдаёт). Собираются все страницы по пагинации.
MAX: GET /messages (поле stat.views) и GET /chats/{id} (подписчики).

Запуск:
    python3 fetch_analytics.py --out ../posting/analytics.json
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import urllib3
from datetime import datetime, timezone

urllib3.disable_warnings()

import requests

TG_USERNAME = os.environ.get("TG_CHANNEL_USERNAME", "noroutine2026")
MAX_CHANNEL_ID = os.environ.get("MAX_CHANNEL_ID", "-71062363105923")
MAX_BOT_TOKEN = os.environ.get("MAX_BOT_TOKEN", "")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
MAX_PAGES = 10
HISTORY_DAYS = 120


def log(msg):
    print(msg, flush=True)


# ----------------------------- MAX -----------------------------

def max_call(method, path, query=None):
    url = f"https://platform-api2.max.ru/{path}"
    try:
        r = requests.request(method, url, params=query,
                             headers={"Authorization": MAX_BOT_TOKEN},
                             timeout=30, verify=False)
        if r.status_code != 200:
            log(f"MAX: {method} {path} → HTTP {r.status_code}: {r.text[:200]}")
            return None
        return r.json()
    except Exception as e:
        log(f"MAX: error calling {method} {path}: {e}")
        return None


def fetch_max():
    """Посты MAX-канала: views, дата, текст. Подписчики из GET /chats."""
    if not MAX_BOT_TOKEN:
        log("MAX: токен не задан, пропускаем")
        return None
    posts = []
    resp = max_call("GET", "messages",
                    query={"chat_id": MAX_CHANNEL_ID, "count": 100})
    if not resp:
        log("MAX: не удалось получить сообщения")
        return None
    for msg in resp.get("messages", []):
        ts = msg.get("timestamp", 0)
        day = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""
        text = (msg.get("body", {}) or {}).get("text") or ""
        posts.append({
            "id": str(msg.get("body", {}).get("mid") or ts),
            "date": day,
            "views": int((msg.get("stat") or {}).get("views") or 0),
            "text": re.sub(r"<[^>]+>", "", text).strip()[:120],
            "url": msg.get("url") or "",
        })

    subscribers = None
    chat = max_call("GET", f"chats/{MAX_CHANNEL_ID}")
    if chat:
        for key in ("subscribers_count", "members_count", "subscribers"):
            if chat.get(key) is not None:
                subscribers = int(chat[key])
                break
    else:
        log("MAX: подписчики недоступны")
    return {"posts": sorted(posts, key=lambda p: p["date"]), "subscribers": subscribers}


# --------------------------- Telegram ---------------------------

def tg_fetch_page(before=None):
    url = f"https://t.me/s/{TG_USERNAME}"
    if before:
        url += f"?before={before}"
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "ignore")


def tg_parse(html):
    rows = []
    for part in re.split(r"(?=<div class=\"tgme_widget_message_wrap)", html):
        mpost = re.search(r"data-post=\"[\w]+/(\d+)\"", part)
        mviews = re.search(r"tgme_widget_message_views\">(\d+)</span>", part)
        mdate = re.search(r"datetime=\"([^\"]+)\"", part)
        mtext = re.search(r"tgme_widget_message_text[^>]*>([\s\S]*?)</div>", part)
        if not (mpost and mviews):
            continue
        text = re.sub(r"<[^>]+>", " ", mtext.group(1)).strip()[:120] if mtext else ""
        rows.append({
            "id": mpost.group(1),
            "date": mdate.group(1)[:10] if mdate else "",
            "views": int(mviews.group(1)),
            "text": text,
            "url": f"https://t.me/{TG_USERNAME}/{mpost.group(1)}",
        })
    return rows


def fetch_telegram():
    posts = {}
    subscribers = None
    try:
        first = tg_fetch_page()
        msubs = re.search(r"counter_value\">(\d+)</span> <span class=\"counter_type\">subscribers", first)
        if msubs:
            subscribers = int(msubs.group(1))
        for page in range(MAX_PAGES):
            html = first if page == 0 else tg_fetch_page(before=min(int(p["id"]) for p in posts.values()))
            rows = tg_parse(html)
            if not rows:
                break
            new_ids = {r["id"] for r in rows} - set(posts)
            for r in rows:
                posts[r["id"]] = r
            if len(new_ids) == 0:
                break
            time.sleep(0.5)
    except Exception as e:
        log(f"Telegram: ошибка сбора: {e}")
        if not posts:
            return None
    return {"posts": sorted(posts.values(), key=lambda p: int(p["id"])),
            "subscribers": subscribers}


# --------------------------- История ---------------------------

def day_totals(posts):
    """{date: сумма views постов, опубликованных в этот день} — для графика по дням."""
    totals = {}
    for p in posts:
        if not p["date"]:
            continue
        totals[p["date"]] = totals.get(p["date"], 0) + p["views"]
    return totals


def update_history(old, channel, posts, subscribers):
    """Обновляет daily-историю канала: сумма просмотров всех постов на сегодня."""
    history = (old or {}).get("daily", [])
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total_now = sum(p["views"] for p in posts)

    if history and history[-1]["date"] == today:
        entry = history[-1]
        prev_total = entry.get("total_views", 0)
        entry["total_views"] = total_now
        if subscribers is not None:
            entry["subscribers"] = subscribers
        entry["new_views"] = max(0, total_now - prev_total)
    else:
        prev_total = history[-1]["total_views"] if history else 0
        history.append({
            "date": today,
            "total_views": total_now,
            "new_views": max(0, total_now - prev_total),
            "posts": len(posts),
            "subscribers": subscribers,
        })
    history = [h for h in history if h["date"]][-HISTORY_DAYS:]
    # Подписчики: берём последнее известное значение
    subs = subscribers
    if subs is None:
        for h in reversed(history):
            if h.get("subscribers") is not None:
                subs = h["subscribers"]
                break
    return {"subscribers": subs,
            "total_views": total_now,
            "daily": history,
            "posts": posts[-100:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="куда записать analytics.json")
    args = ap.parse_args()

    old = {}
    if os.path.exists(args.out):
        try:
            with open(args.out, encoding="utf-8") as f:
                old = json.load(f)
        except (OSError, ValueError) as e:
            log(f"Не удалось прочитать старый файл ({e}), начинаем историю заново")

    channels = old.get("channels", {})

    tg = fetch_telegram()
    if tg:
        channels["telegram"] = update_history(channels.get("telegram"), "telegram",
                                              tg["posts"], tg["subscribers"])
        log(f"Telegram: {len(tg['posts'])} постов, "
            f"{channels['telegram']['total_views']} просмотров, "
            f"{tg['subscribers']} подписчиков")
    else:
        log("Telegram: данные не получены, оставляем прежние")

    mx = fetch_max()
    if mx:
        channels["max"] = update_history(channels.get("max"), "max",
                                         mx["posts"], mx["subscribers"])
        log(f"MAX: {len(mx['posts'])} постов, "
            f"{channels['max']['total_views']} просмотров, "
            f"{mx['subscribers']} подписчиков")
    else:
        log("MAX: данные не получены, оставляем прежние")

    result = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "channels": channels,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    log(f"Записано в {args.out}")


if __name__ == "__main__":
    main()
