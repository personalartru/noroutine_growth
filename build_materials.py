"""Сборка лид-магнита: 5 основных n8n-воркфлоу + 5 бонусных + гайд -> ZIP.

Запуск: python build_materials.py
Результат: materials/noroutine-n8n-pack.zip
"""
import json
import os
import re
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(BASE_DIR, "materials")
WF_DIR = os.path.join(OUT_DIR, "workflows")
BONUS_DIR = os.path.join(OUT_DIR, "workflows-bonus")

TRACKER = "https://api.tracker.yandex.net"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
TG_API = "https://api.telegram.org/bot{{token}}/sendMessage"


class Builder:
    def __init__(self):
        self.nodes = []
        self.connections = {}
        self._id = 0

    def add(self, name, ntype, params, pos, type_version=1):
        self._id += 1
        self.nodes.append({
            "parameters": params,
            "id": f"n{self._id:04d}{name[:4].lower()}",
            "name": name,
            "type": ntype,
            "typeVersion": type_version,
            "position": pos,
        })
        return name

    def link(self, src, dst, out=0, inp=0):
        self.connections.setdefault(src, {"main": []})
        while len(self.connections[src]["main"]) <= out:
            self.connections[src]["main"].append([])
        self.connections[src]["main"][out].append({"node": dst, "type": "main", "index": inp})

    def flow(self, names):
        for a, b in zip(names, names[1:]):
            self.link(a, b)

    def dump(self, name, tags, core=False):
        return {
            "name": name,
            "core": core,
            "nodes": self.nodes,
            "connections": self.connections,
            "active": False,
            "settings": {"executionOrder": "v1"},
            "versionId": f"noroutine-{name.lower().replace(' ', '-')[:24]}",
            "meta": {"instanceId": "noroutine-pack"},
            "id": f"nr-{name.lower().replace(' ', '-')[:24]}",
            "tags": tags,
            "pinData": {},
        }


def tracker_issue_body(title, desc, project="TMP"):
    return {
        "fields": {
            "summary": title,
            "description": desc,
            "project": {"id": project},
            "type": {"id": "3"},
        }
    }


def build_workflows():
    wfs = []

    # 1. Вебхук -> создание задачи в Яндекс Трекере
    b = Builder()
    b.add("Webhook", "n8n-nodes-base.webhook", {
        "httpMethod": "POST",
        "path": "tracker-task",
        "responseMode": "responseNode",
        "options": {},
    }, [0, 0], 2)
    b.add("Собрать задачу", "n8n-nodes-base.set", {
        "assignments": {"assignments": [
            {"id": "f1", "name": "summary", "value": "={{ $json.body.title }}", "type": "string"},
            {"id": "f2", "name": "description", "value": "={{ $json.body.description }}", "type": "string"},
            {"id": "f3", "name": "project", "value": "={{ $json.body.project || 'TMP' }}", "type": "string"},
        ]},
        "includeOtherFields": False,
    }, [220, 0], 3.4)
    b.add("Создать задачу", "n8n-nodes-base.httpRequest", {
        "method": "POST",
        "url": f"={TRACKER}/v2/issues/",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "Authorization", "value": "=Bearer {{$env.TRACKER_TOKEN}}"},
            {"name": "X-Tracker-Org-Id", "value": "={{$env.TRACKER_ORG_ID}}"},
        ]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ fields: { summary: $json.summary, description: $json.description, project: { id: $json.project }, type: { id: '3' } } }) }}",
        "options": {},
    }, [440, 0], 4.2)
    b.add("Ответ", "n8n-nodes-base.respondToWebhook", {
        "respondWith": "json",
        "responseBody": "={{ { ok: true, issueId: $json.id, key: $json.key } }}",
        "options": {"responseCode": 200},
    }, [660, 0], 1.1)
    b.flow(["Webhook", "Собрать задачу", "Создать задачу", "Ответ"])
    wfs.append(b.dump("01 Tracker: вебхук -> новая задача", ["Трекер", "webhook"], core=True))

    # 2. Смена статуса -> автоназначение исполнителя -> уведомление в Telegram
    b = Builder()
    b.add("Webhook статуса", "n8n-nodes-base.webhook", {
        "httpMethod": "POST", "path": "tracker-status", "responseMode": "responseNode", "options": {},
    }, [0, 0], 2)
    b.add("Данные задачи", "n8n-nodes-base.set", {
        "assignments": {"assignments": [
            {"id": "a1", "name": "issueId", "value": "={{ $json.body.issueId }}", "type": "string"},
            {"id": "a2", "name": "status", "value": "={{ $json.body.status }}", "type": "string"},
            {"id": "a3", "name": "assignee", "value": "={{ $json.body.assignee || $env.TRACKER_DEFAULT_ASSIGNEE }}", "type": "string"},
            {"id": "a4", "name": "summary", "value": "={{ $json.body.summary }}", "type": "string"},
        ]},
        "includeOtherFields": False,
    }, [220, 0], 3.4)
    b.add("Назначить ответственного", "n8n-nodes-base.httpRequest", {
        "method": "PATCH",
        "url": "={{ $env.TRACKER_URL + '/v2/issues/' + $json.issueId }}",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "Authorization", "value": "=Bearer {{$env.TRACKER_TOKEN}}"},
            {"name": "X-Tracker-Org-Id", "value": "={{$env.TRACKER_ORG_ID}}"},
        ]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ fields: { assignee: { id: $json.assignee } } }) }}",
        "options": {},
    }, [440, 0], 4.2)
    b.add("Уведомить в Telegram", "n8n-nodes-base.telegram", {
        "chatId": "={{ $env.TG_CHAT_ID }}",
        "text": "={{ 'Задача ' + $json.summary + ' перешла в статус ' + $json.status + '. Ответственный назначен автоматически.' }}",
        "additionalFields": {"parse_mode": "HTML"},
    }, [660, 0], 1.2)
    b.add("Ответ", "n8n-nodes-base.respondToWebhook", {
        "respondWith": "json", "responseBody": "={{ { ok: true } }}", "options": {"responseCode": 200},
    }, [880, 0], 1.1)
    b.flow(["Webhook статуса", "Данные задачи", "Назначить ответственного", "Уведомить в Telegram", "Ответ"])
    wfs.append(b.dump("02 Tracker: автоназначение и уведомление", ["Трекер", "Telegram"], core=True))

    # 3. Яндекс Формы -> задачи в Трекере
    b = Builder()
    b.add("Webhook формы", "n8n-nodes-base.webhook", {
        "httpMethod": "POST", "path": "yandex-form", "responseMode": "responseNode", "options": {},
    }, [0, 0], 2)
    b.add("Разобрать ответы", "n8n-nodes-base.code", {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "const body = $json.body || {};\n"
            "const answers = body.answers || [];\n"
            "const get = (code) => {\n"
            "  const a = answers.find((x) => String(x.code).includes(code));\n"
            "  return a ? (a.text || a.value || '') : '';\n"
            "};\n"
            "const title = get('question_title') || body.title || 'Заявка из формы';\n"
            "const description = answers.map((a) => `${a.question || a.code}: ${a.text || a.value || ''}`).join('\\n');\n"
            "return [{ json: { summary: title, description, email: body.email || '', project: body.project || 'TMP' } }];"
        ),
    }, [220, 0], 2)
    b.add("Создать задачу", "n8n-nodes-base.httpRequest", {
        "method": "POST",
        "url": f"={TRACKER}/v2/issues/",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "Authorization", "value": "=Bearer {{$env.TRACKER_TOKEN}}"},
            {"name": "X-Tracker-Org-Id", "value": "={{$env.TRACKER_ORG_ID}}"},
        ]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ fields: { summary: $json.summary, description: $json.description, project: { id: $json.project }, type: { id: '3' } } }) }}",
        "options": {},
    }, [440, 0], 4.2)
    b.add("Ответ", "n8n-nodes-base.respondToWebhook", {
        "respondWith": "json", "responseBody": "={{ { ok: true, key: $json.key } }}", "options": {"responseCode": 201},
    }, [660, 0], 1.1)
    b.flow(["Webhook формы", "Разобрать ответы", "Создать задачу", "Ответ"])
    wfs.append(b.dump("03 Яндекс Формы -> задачи в Трекере", ["Трекер", "Формы"], core=True))

    # 4. AI-комментарий к задаче + отчёт в Telegram
    b = Builder()
    b.add("Расписание", "n8n-nodes-base.scheduleTrigger", {
        "rule": {"interval": [{"field": "hours", "hoursInterval": 8}]},
    }, [0, 0], 1.2)
    b.add("Забрать задачи", "n8n-nodes-base.httpRequest", {
        "method": "GET",
        "url": f"={TRACKER}/v2/issues/?fields=id,key,summary,status,updatedAt&limit=50",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "Authorization", "value": "=Bearer {{$env.TRACKER_TOKEN}}"},
            {"name": "X-Tracker-Org-Id", "value": "={{$env.TRACKER_ORG_ID}}"},
        ]},
        "options": {},
    }, [220, 0], 4.2)
    b.add("Выбрать без комментария", "n8n-nodes-base.code", {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "const out = [];\n"
            "for (const item of $input.all()) {\n"
            "  const issue = item.json;\n"
            "  if (!issue || !issue.id) continue;\n"
            "  if (issue.updatedAt && Date.now() - new Date(issue.updatedAt).getTime() < 3600000) continue;\n"
            "  out.push({ json: { id: issue.id, key: issue.key, summary: issue.summary } });\n"
            "}\n"
            "return out;"
        ),
    }, [440, 0], 2)
    b.add("LLM-комментарий", "n8n-nodes-base.openAi", {
        "resource": "chat",
        "operation": "message",
        "model": "gpt-4o-mini",
        "promptType": "define",
        "text": (
            "=Ты тимлид. По задаче {{$json.key}} — {{$json.summary}} — напиши один короткий комментарий "
            "(до 400 символов): что делать дальше и какой риск. Без воды, по-русски."
        ),
        "options": {"temperature": 0.4},
    }, [660, 0], 1)
    b.add("Добавить комментарий", "n8n-nodes-base.httpRequest", {
        "method": "POST",
        "url": "={{ $env.TRACKER_URL + '/v2/issues/' + $json.id + '/comments' }}",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "Authorization", "value": "=Bearer {{$env.TRACKER_TOKEN}}"},
            {"name": "X-Tracker-Org-Id", "value": "={{$env.TRACKER_ORG_ID}}"},
            {"name": "Content-Type", "value": "application/json"},
        ]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ comment: $json.text }) }}",
        "options": {},
    }, [880, 0], 4.2)
    b.add("Отчёт в Telegram", "n8n-nodes-base.telegram", {
        "chatId": "={{ $env.TG_CHAT_ID }}",
        "text": "={{ 'AI добавил комментарии к ' + $input.all().length + ' задачам.' }}",
        "additionalFields": {"parse_mode": "HTML"},
    }, [1100, 0], 1.2)
    b.link("Расписание", "Забрать задачи")
    b.link("Забрать задачи", "Выбрать без комментария")
    b.link("Выбрать без комментария", "LLM-комментарий")
    b.link("LLM-комментарий", "Добавить комментарий")
    b.link("Добавить комментарий", "Отчёт в Telegram")
    wfs.append(b.dump("04 AI-комментарии к задачам в Трекере", ["Трекер", "AI"]))

    # 5. Трекер -> Google Sheets (выгрузка задач)
    b = Builder()
    b.add("Расписание", "n8n-nodes-base.scheduleTrigger", {
        "rule": {"interval": [{"field": "hours", "hoursInterval": 24}]},
    }, [0, 0], 1.2)
    b.add("Забрать задачи", "n8n-nodes-base.httpRequest", {
        "method": "GET",
        "url": f"={TRACKER}/v2/issues/?fields=id,key,summary,status,assignee,updatedAt&limit=200",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "Authorization", "value": "=Bearer {{$env.TRACKER_TOKEN}}"},
            {"name": "X-Tracker-Org-Id", "value": "={{$env.TRACKER_ORG_ID}}"},
        ]},
        "options": {},
    }, [220, 0], 4.2)
    b.add("Привести к строке", "n8n-nodes-base.code", {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "return $input.all().map((item) => ({\n"
            "  json: {\n"
            "    key: item.json.key,\n"
            "    summary: item.json.summary,\n"
            "    status: item.json.status,\n"
            "    assignee: item.json.assignee && item.json.assignee.name ? item.json.assignee.name : '',\n"
            "    updatedAt: item.json.updatedAt || '',\n"
            "  },\n"
            "}));"
        ),
    }, [440, 0], 2)
    b.add("Дописать в таблицу", "n8n-nodes-base.googleSheets", {
        "documentId": "={{ $env.SHEETS_ID }}",
        "sheetName": "Задачи",
        "operation": "append",
        "columns": "={{ ['key','summary','status','assignee','updatedAt'] }}",
    }, [660, 0], 2.2)
    b.flow(["Расписание", "Забрать задачи", "Привести к строке", "Дописать в таблицу"])
    wfs.append(b.dump("05 Трекер -> Google Sheets: выгрузка задач", ["Трекер", "Google Sheets"]))

    # 6. Telegram-бот обратной связи -> Google Sheets
    b = Builder()
    b.add("Telegram Trigger", "n8n-nodes-base.telegramTrigger", {
        "updates": ["message"],
        "additionalFields": {},
    }, [0, 0], 1.2)
    b.add("Разобрать сообщение", "n8n-nodes-base.code", {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "const text = $json.message ? $json.message.text : ($json.text || '');\n"
            "const chat = $json.message ? $json.message.chat : $json.chat;\n"
            "const from = $json.message ? $json.message.from : $json.from;\n"
            "return [{ json: {\n"
            "  text: text,\n"
            "  chatId: chat ? chat.id : null,\n"
            "  name: from ? (from.first_name || '') : '',\n"
            "  username: from ? (from.username || '') : '',\n"
            "  created: new Date().toISOString(),\n"
            "} }];"
        ),
    }, [220, 0], 2)
    b.add("Валидация", "n8n-nodes-base.if", {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
            "conditions": [{
                "id": "c1",
                "leftValue": "={{ $json.text.length }}",
                "rightValue": 2,
                "operator": {"type": "number", "operation": "gte"},
            }],
            "combinator": "and",
        },
        "options": {},
    }, [440, 0], 2.2)
    b.add("Записать заявку", "n8n-nodes-base.googleSheets", {
        "documentId": "={{ $env.SHEETS_ID }}",
        "sheetName": "Заявки",
        "operation": "append",
        "columns": "={{ ['created','name','username','text'] }}",
    }, [660, 0], 2.2)
    b.add("Ответить в чат", "n8n-nodes-base.telegram", {
        "chatId": "={{ $json.chatId }}",
        "text": "=Принял, спасибо! Отвечу в рабочее время.",
        "additionalFields": {"parse_mode": "HTML"},
    }, [880, 0], 1.2)
    b.add("Ответить «пусто»", "n8n-nodes-base.telegram", {
        "chatId": "={{ $json.chatId }}",
        "text": "=Пришлите текст заявки — запишу её.",
        "additionalFields": {"parse_mode": "HTML"},
    }, [660, 120], 1.2)
    b.flow(["Telegram Trigger", "Разобрать сообщение", "Валидация"])
    b.link("Валидация", "Записать заявку", 0)
    b.link("Записать заявку", "Ответить в чат")
    b.link("Валидация", "Ответить «пусто»", 1)
    wfs.append(b.dump("06 Telegram-бот обратной связи -> Google Sheets", ["Telegram", "Google Sheets"], core=True))

    # 7. MAX-бот: сообщения -> Google Sheets
    b = Builder()
    b.add("Webhook MAX", "n8n-nodes-base.webhook", {
        "httpMethod": "POST", "path": "max-bot", "responseMode": "responseNode", "options": {},
    }, [0, 0], 2)
    b.add("Разобрать сообщение", "n8n-nodes-base.code", {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "const body = $json.body || {};\n"
            "const msg = body.message || {};\n"
            "const text = msg.body && msg.body.text ? msg.body.text : (body.text || '');\n"
            "const user = body.user || {};\n"
            "return [{ json: {\n"
            "  text: text,\n"
            "  userId: user.user_id || '',\n"
            "  name: user.name || '',\n"
            "  chatId: body.chat_id || '',\n"
            "  created: new Date().toISOString(),\n"
            "} }];"
        ),
    }, [220, 0], 2)
    b.add("Записать в таблицу", "n8n-nodes-base.googleSheets", {
        "documentId": "={{ $env.SHEETS_ID }}",
        "sheetName": "MAX заявки",
        "operation": "append",
        "columns": "={{ ['created','userId','name','text'] }}",
    }, [440, 0], 2.2)
    b.add("Ответ в MAX", "n8n-nodes-base.httpRequest", {
        "method": "POST",
        "url": "=https://platform-api2.max.ru/messages",
        "sendQuery": True,
        "queryParameters": {"parameters": [
            {"name": "chat_id", "value": "={{ $json.chatId }}"},
        ]},
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "Authorization", "value": "={{ $env.MAX_BOT_TOKEN }}"},
            {"name": "Content-Type", "value": "application/json"},
        ]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ text: 'Принял, спасибо! Отвечу в рабочее время.', format: 'html', notify: true }) }}",
        "options": {},
    }, [660, 0], 4.2)
    b.add("Ответ на вебхук", "n8n-nodes-base.respondToWebhook", {
        "respondWith": "json", "responseBody": "={{ { ok: true } }}", "options": {"responseCode": 200},
    }, [880, 0], 1.1)
    b.flow(["Webhook MAX", "Разобрать сообщение", "Записать в таблицу", "Ответ в MAX", "Ответ на вебхук"])
    wfs.append(b.dump("07 MAX-бот: заявки в Google Sheets", ["MAX", "Google Sheets"], core=True))

    # 8. Ежедневный отчёт: Google Sheets -> Telegram
    b = Builder()
    b.add("Расписание 08:00", "n8n-nodes-base.scheduleTrigger", {
        "rule": {"interval": [{"field": "hours", "hoursInterval": 24}]},
    }, [0, 0], 1.2)
    b.add("Прочитать таблицу", "n8n-nodes-base.googleSheets", {
        "documentId": "={{ $env.SHEETS_ID }}",
        "sheetName": "Задачи",
        "range": "A:E",
        "options": {},
    }, [220, 0], 2.2)
    b.add("Собрать отчёт", "n8n-nodes-base.code", {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "const rows = $input.all().map((i) => i.json);\n"
            "const byStatus = {};\n"
            "for (const r of rows) {\n"
            "  const s = r.status || 'не указан';\n"
            "  byStatus[s] = (byStatus[s] || 0) + 1;\n"
            "}\n"
            "const lines = Object.entries(byStatus).map(([k, v]) => `${k}: ${v}`);\n"
            "return [{ json: { report: `Задач всего: ${rows.length}\\n` + lines.join('\\n') } }];"
        ),
    }, [440, 0], 2)
    b.add("Отправить отчёт", "n8n-nodes-base.telegram", {
        "chatId": "={{ $env.TG_CHAT_ID }}",
        "text": "={{ 'Отчёт за день\\n' + $json.report }}",
        "additionalFields": {"parse_mode": "HTML"},
    }, [660, 0], 1.2)
    b.flow(["Расписание 08:00", "Прочитать таблицу", "Собрать отчёт", "Отправить отчёт"])
    wfs.append(b.dump("08 Ежедневный отчёт: Sheets -> Telegram", ["Google Sheets", "Telegram"]))

    # 9. REST API: вебхук с валидацией -> Sheets + 400 при ошибке
    b = Builder()
    b.add("Webhook", "n8n-nodes-base.webhook", {
        "httpMethod": "POST", "path": "intake", "responseMode": "responseNode", "options": {},
    }, [0, 0], 2)
    b.add("Валидация", "n8n-nodes-base.code", {
        "mode": "runOnceForAllItems",
        "jsCode": (
            "const body = $json.body || {};\n"
            "const email = body.email || '';\n"
            "const ok = /^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(email);\n"
            "if (!ok) { return [{ json: { valid: false, error: 'Некорректный email' } }]; }\n"
            "return [{ json: { valid: true, email: email, message: body.message || '', created: new Date().toISOString() } }];"
        ),
    }, [220, 0], 2)
    b.add("Ошибка 400", "n8n-nodes-base.respondToWebhook", {
        "respondWith": "json",
        "responseBody": "={{ { ok: false, error: $json.error } }}",
        "options": {"responseCode": 400},
    }, [440, 120], 1.1)
    b.add("Сохранить заявку", "n8n-nodes-base.googleSheets", {
        "documentId": "={{ $env.SHEETS_ID }}",
        "sheetName": "Лиды",
        "operation": "append",
        "columns": "={{ ['created','email','message'] }}",
    }, [440, 0], 2.2)
    b.add("Ответ 200", "n8n-nodes-base.respondToWebhook", {
        "respondWith": "json",
        "responseBody": "={{ { ok: true } }}",
        "options": {"responseCode": 200},
    }, [660, 0], 1.1)
    b.link("Webhook", "Валидация")
    b.link("Валидация", "Ошибка 400", 1)
    b.link("Валидация", "Сохранить заявку", 0)
    b.link("Сохранить заявку", "Ответ 200")
    wfs.append(b.dump("09 REST API: лид с валидацией и записью", ["Webhook", "Google Sheets"]))

    # 10. Yandex Cloud Function: приём вебхука и проксирование в n8n
    b = Builder()
    b.add("Webhook", "n8n-nodes-base.webhook", {
        "httpMethod": "POST", "path": "serverless", "responseMode": "responseNode", "options": {},
    }, [0, 0], 2)
    b.add("Подготовить", "n8n-nodes-base.set", {
        "assignments": {"assignments": [
            {"id": "s1", "name": "payload", "value": "={{ JSON.stringify($json.body) }}", "type": "string"},
            {"id": "s2", "name": "ts", "value": "={{ $now.toISO() }}", "type": "string"},
        ]},
        "includeOtherFields": False,
    }, [220, 0], 3.4)
    b.add("Вызвать n8n", "n8n-nodes-base.httpRequest", {
        "method": "POST",
        "url": "={{ $env.N8N_WEBHOOK_URL }}",
        "sendHeaders": True,
        "headerParameters": {"parameters": [
            {"name": "X-Signature", "value": "={{ $env.WEBHOOK_SECRET }}"},
        ]},
        "sendBody": True,
        "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ payload: $json.payload, ts: $json.ts }) }}",
        "options": {},
    }, [440, 0], 4.2)
    b.add("Ответ", "n8n-nodes-base.respondToWebhook", {
        "respondWith": "json",
        "responseBody": "={{ { ok: true, status: $json.status || 'accepted' } }}",
        "options": {"responseCode": 202},
    }, [660, 0], 1.1)
    b.flow(["Webhook", "Подготовить", "Вызвать n8n", "Ответ"])
    wfs.append(b.dump("10 Serverless-функция как вход в n8n", ["Serverless", "webhook"]))

    return wfs


README = """# 5 готовых n8n-воркфлоу для рутины

Пять воркфлоу, которые закрывают самые частые ручные процессы в digital и
проектном управлении: заявки из форм, задачи в Яндекс Трекере, статусы и
автоназначение, боты обратной связи в Telegram и MAX, выгрузка в таблицу.
В папке `workflows-bonus/` — ещё пять: AI-комментарии, ежедневный отчёт,
REST-приём лидов и serverless-обработчик.

## Как импортировать

1. Откройте n8n -> Import from File -> выберите `.json` из папки `workflows`.
2. В узлах HTTP Request подставьте свои токены (см. «Переменные» ниже).
3. Нажмите Execute Workflow, потом Active.

## Переменные окружения

| Переменная | Где взять |
|---|---|
| `TRACKER_URL` | https://tracker.yandex.ru, версия API: `/v2` |
| `TRACKER_TOKEN` | OAuth-токен Яндекс Трекера |
| `TRACKER_ORG_ID` | ID организации в Трекере |
| `TRACKER_DEFAULT_ASSIGNEE` | ID сотрудника для автоназначения |
| `SHEETS_ID` | ID таблицы Google Sheets |
| `TG_CHAT_ID` | чат, куда слать отчёты |
| `MAX_BOT_TOKEN` | токен бота MAX (platform-api2.max.ru) |
| `N8N_WEBHOOK_URL` | production-webhook URL для serverless-функции |
| `WEBHOOK_SECRET` | подпись для проверки входящих вебхуков |

## Основные воркфлоу (5)

1. **Tracker: вебхук -> новая задача** — приём заявки с сайта и создание задачи.
2. **Tracker: автоназначение и уведомление** — смена статуса -> ответственный + Telegram.
3. **Яндекс Формы -> задачи в Трекере** — ответы формы становятся задачами.
4. **AI-комментарии к задачам в Трекере** — LLM ставит короткий комментарий по задаче.
5. **Трекер -> Google Sheets** — выгрузка задач в таблицу раз в сутки.
6. **Telegram-бот обратной связи -> Google Sheets** — заявки из чата в таблицу.
7. **MAX-бот: заявки в Google Sheets** — приём сообщений из мессенджера MAX.
8. **Ежедневный отчёт: Sheets -> Telegram** — сводка статусов каждое утро.
9. **REST API: лид с валидацией** — приём лидов с проверкой email и кодом 400.
10. **Serverless-функция как вход в n8n** — облачная функция проксирует вебхуки в n8n.

Пункты 4–10 лежат в папке `workflows-bonus/` — они не входят в основные пять,
но доступны, если захочется продолжить.

## Бонус: serverless-обработчик

В папке `functions/` лежит обработчик для Yandex Cloud Functions (Python), который
принимает вебхук, проверяет подпись и проксирует запрос в n8n.

## Что дальше

Каждый воркфлоу — готовая основа под внедрение. Если нужен разбор под
ваши процессы (а не шаблон из интернета) — напишите: разберу ваш процесс и
соберу связку под него. https://t.me/noroutine2026
"""


def safe_name(name):
    for ch in ':→':
        name = name.replace(ch, "-")
    return name.replace("  ", " ").strip()


def write_all():
    os.makedirs(WF_DIR, exist_ok=True)
    os.makedirs(BONUS_DIR, exist_ok=True)
    workflows = build_workflows()
    core_index = 0
    bonus_index = 0
    for wf in workflows:
        base = re.sub(r"^\d+\s*", "", wf["name"])
        if wf.get("core"):
            core_index += 1
            target = WF_DIR
            filename = f"{core_index:02d} {safe_name(base)}.json"
        else:
            bonus_index += 1
            target = BONUS_DIR
            filename = f"Бонус {bonus_index} - {safe_name(base)}.json"
        path = os.path.join(target, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(wf, f, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "README.md"), "w", encoding="utf-8") as f:
        f.write(README)

    fn_dir = os.path.join(OUT_DIR, "functions")
    os.makedirs(fn_dir, exist_ok=True)
    with open(os.path.join(fn_dir, "handler.py"), "w", encoding="utf-8") as f:
        f.write('''"""Yandex Cloud Function: принимает вебхук и проксирует его в n8n."""
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
''')

    zip_path = os.path.join(OUT_DIR, "noroutine-n8n-pack.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(os.path.join(OUT_DIR, "README.md"), "README.md")
        for name in sorted(os.listdir(WF_DIR)):
            z.write(os.path.join(WF_DIR, name), f"workflows/{name}")
        for name in sorted(os.listdir(BONUS_DIR)):
            z.write(os.path.join(BONUS_DIR, name), f"workflows-bonus/{name}")
        for name in sorted(os.listdir(fn_dir)):
            z.write(os.path.join(fn_dir, name), f"functions/{name}")
    core = sum(1 for w in workflows if w.get("core"))
    print("Собрано:", zip_path, os.path.getsize(zip_path), "байт,", core, "основных +", len(workflows) - core, "бонусных")


if __name__ == "__main__":
    write_all()
