"""«Оптимизатор» — пошаговый CALC-бот внутри MAX-лид-бота No! Routine.

Шаги диалога (inline_keyboard, payload вида ``opt:...``):

1. сфера деятельности — те же 6 сфер, что в калькуляторе на сайте;
2. кого оптимизируем — «только я» или команда по специальностям + количество
   (пресетами или числом сообщением);
3. наиболее частые рутинные операции — мультивыбор, у каждой часов в месяц;
4. результат №1 — описание ситуации, часы рутины и их стоимость;
5. инструменты оптимизации — мультивыбор + шуточная кнопка «Уволить всех»;
6. результат №2 — экономия в часах и рублях и пошаговый чек-лист внедрения;
7. примерная стоимость внедрения, окупаемость, дисклеймер и кнопка
   обратной связи (текст пользователя уходит владельцу).

Модуль не знает про MAX API: он возвращает список сообщений
``{"text": ..., "buttons": [...]}``, а транспорт, ответы на callbacks и
хранение состояния делает max_lead.py. Благодаря этому флоу прогоняется
локально без токена: ``python tools/simulate_optimizer.py``.

Методика совпадает с калькулятором сайта: часы рутины × фактор инструмента.
Факторы взяты оттуда же (chat 0.65, agent 0.85, n8n 0.75, tracker 0.5,
full 0.9) и складываются как независимые события: непокрытая доля =
произведение (1 − f), с потолком 92%. Ставка — типовая месячная зарплата по
специальности, поделённая на ~160 рабочих часов.
"""
import html
import re
import time

SESSION_TTL = 40 * 60          # без действий сессия сбрасывается
MAX_HEADCOUNT = 300            # потолок для ручного ввода
TEXT_CHUNK = 900               # запас под лимит длины сообщения в MAX
WORK_HOURS = 160               # рабочих часов в месяце на человека

SELF_ROLE = {"label": "Я сам (руковожу и делаю руками)", "salary": 120000}

SPHERES = [
    {
        "id": "ecommerce",
        "label": "E-commerce / ритейл",
        "blurb": "карточки, отгрузки, отзывы и отчёты повторяются каждый день "
                 "одними и теми же руками",
        "roles": [
            {"id": "content", "label": "Менеджер карточек и контента", "salary": 65000},
            {"id": "ops", "label": "Оператор маркетплейса", "salary": 70000},
            {"id": "support", "label": "Менеджер поддержки покупателей", "salary": 60000},
            {"id": "supply", "label": "Закупщик / логист", "salary": 95000},
        ],
        "ops": [
            {"id": "cards", "label": "Заполнение и обновление карточек", "hours": 22,
             "detail": "описания, характеристики, фото, цены по регламенту"},
            {"id": "reviews", "label": "Ответы на отзывы и вопросы", "hours": 18,
             "detail": "шаблоны, модерация, отработка негатива"},
            {"id": "stock", "label": "Сверка остатков и заказов", "hours": 20,
             "detail": "обход кабинетов, таблички, поиск расхождений"},
            {"id": "ship", "label": "Оформление отгрузок и возвратов", "hours": 16,
             "detail": "перенос данных из заявок в учётную систему, документы"},
            {"id": "price", "label": "Контроль цен и конкурентов", "hours": 12,
             "detail": "ежедневной ручной мониторинг листов и кабинетов"},
            {"id": "report", "label": "Отчётность по продажам", "hours": 14,
             "detail": "выгрузки из кабинетов, сведение в таблицу, график"},
        ],
    },
    {
        "id": "lead",
        "label": "Lead-gen / маркетинг",
        "blurb": "заявки приходят из пяти источников, и каждую кто-то открывает, "
                 "копирует и прозванивает вручную",
        "roles": [
            {"id": "manager", "label": "Менеджер по обработке лидов", "salary": 75000},
            {"id": "marketer", "label": "Таргетолог / маркетолог", "salary": 110000},
            {"id": "content", "label": "Контент-менеджер", "salary": 70000},
            {"id": "analyst", "label": "Маркетинговый аналитик", "salary": 120000},
        ],
        "ops": [
            {"id": "leads", "label": "Разбор заявок из форм и чатов", "hours": 24,
             "detail": "открыть почту или таблицу, перенести в CRM, поставить статус"},
            {"id": "crm", "label": "Перенос лидов между системами", "hours": 16,
             "detail": "копирование полей, дедупликация, ручные комментарии"},
            {"id": "camp", "label": "Сбор отчётов по кампаниям", "hours": 14,
             "detail": "выгрузки из кабинетов, сведение CPL/ДРР в таблицу"},
            {"id": "brief", "label": "ТЗ креативам и подрядчикам", "hours": 12,
             "detail": "повторяющиеся брифы, правки, контроль сроков"},
            {"id": "social", "label": "Ответы в комментах и директе", "hours": 15,
             "detail": "одни и те же вопросы про цену, сроки, адрес"},
            {"id": "pay", "label": "Контроль оплат и документов", "hours": 10,
             "detail": "сверка актов, напоминания, загрузка в учётную систему"},
        ],
    },
    {
        "id": "support",
        "label": "Поддержка / сервис",
        "blurb": "большая часть обращений повторяется, но каждый раз их читает, "
                 "классифицирует и закрывает живой человек",
        "roles": [
            {"id": "first", "label": "Оператор первой линии", "salary": 60000},
            {"id": "second", "label": "Специалист второй линии", "salary": 85000},
            {"id": "csm", "label": "Аккаунт-менеджер / CSM", "salary": 100000},
            {"id": "lead", "label": "Руководитель смены поддержки", "salary": 120000},
        ],
        "ops": [
            {"id": "tickets", "label": "Ответы на типовые обращения", "hours": 26,
             "detail": "инструкция, статус заказа, сброс пароля, тарифы"},
            {"id": "route", "label": "Категоризация и маршрутизация", "hours": 14,
             "detail": "ручной разбор, шаблоны тем, передача на линию"},
            {"id": "status", "label": "Статусы и шаблонные письма", "hours": 16,
             "detail": "шаблоны, подстановка данных клиента, отправка"},
            {"id": "crm", "label": "Ведение записей в CRM и трекере", "hours": 12,
             "detail": "комментарии, история обращений, теги"},
            {"id": "sla", "label": "Контроль SLA и эскалации", "hours": 10,
             "detail": "обход очереди, напоминания, ручная эскалация"},
            {"id": "report", "label": "Ежедневные отчёты поддержки", "hours": 12,
             "detail": "выгрузка тикетов, сводка по линиям, график"},
        ],
    },
    {
        "id": "hr",
        "label": "HR / онбординг",
        "blurb": "поиск, приглашения, кадровые документы и доступы новичку — "
                 "цепочка шаблонных действий на каждый найм",
        "roles": [
            {"id": "recruiter", "label": "Рекрутер", "salary": 85000},
            {"id": "kadro", "label": "Специалист по кадровому учёту", "salary": 65000},
            {"id": "onboard", "label": "Онбординг-менеджер", "salary": 80000},
            {"id": "hrbp", "label": "HR-партнёр", "salary": 130000},
        ],
        "ops": [
            {"id": "screen", "label": "Скрининг резюме", "hours": 20,
             "detail": "первичный отбор, отметки, шаблонные отказы"},
            {"id": "invite", "label": "Приглашения и напоминания", "hours": 14,
             "detail": "переписка о собеседованиях, переносы, подтверждения"},
            {"id": "docs", "label": "Кадровые документы", "hours": 18,
             "detail": "приказы, договоры, заполнения, сканы"},
            {"id": "onboard", "label": "Чек-листы онбординга и доступы", "hours": 12,
             "detail": "заявки на доступы, рассылка инструкций, контроль"},
            {"id": "survey", "label": "Опросы и сбор обратной связи", "hours": 8,
             "detail": "ручная рассылка, сбор ответов, сведение в таблицу"},
            {"id": "report", "label": "Отчётность по найму", "hours": 10,
             "detail": "воронка, источники, сроки закрытия вакансий"},
        ],
    },
    {
        "id": "finance",
        "label": "Финансы / бухучёт",
        "blurb": "первичка, платежи и сверки приходят каждый день, и каждый день "
                 "их кто-то ищет, разносит и сверяет руками",
        "roles": [
            {"id": "primary", "label": "Специалист по первичке", "salary": 65000},
            {"id": "accountant", "label": "Бухгалтер", "salary": 85000},
            {"id": "analyst", "label": "Финансовый аналитик", "salary": 125000},
            {"id": "control", "label": "Финансовый контролёр", "salary": 140000},
        ],
        "ops": [
            {"id": "primary", "label": "Сбор и сверка первички", "hours": 24,
             "detail": "почта, ЭДО, папки, поиск недостающих документов"},
            {"id": "bank", "label": "Разнос платежей и выписок", "hours": 18,
             "detail": "ручное отнесение, назначения, разбивки"},
            {"id": "invoice", "label": "Счета, акты и УПД", "hours": 14,
             "detail": "создание документов по заявкам, отправка клиентам"},
            {"id": "budget", "label": "Отчёты по расходам и бюджету", "hours": 14,
             "detail": "выгрузки, сведение план/факта в таблицу"},
            {"id": "remind", "label": "Напоминания по оплатам", "hours": 10,
             "detail": "контроль дебиторки, письма и звонки"},
            {"id": "close", "label": "Закрытие периода и реконсиляция", "hours": 16,
             "detail": "сверки с контрагентами, поиск расхождений"},
        ],
    },
    {
        "id": "saas",
        "label": "SaaS / продукт",
        "blurb": "фидбек, баг-репорты, бэклог и метрики разлетаются по чатам — "
                 "и кто-то сводит это вручную в задачи и отчёты",
        "roles": [
            {"id": "pm", "label": "Продакт / проект-менеджер", "salary": 145000},
            {"id": "support", "label": "Продуктовая поддержка / CSM", "salary": 80000},
            {"id": "analyst", "label": "Аналитик", "salary": 130000},
            {"id": "qa", "label": "QA / координатор задач", "salary": 105000},
        ],
        "ops": [
            {"id": "feedback", "label": "Разбор фидбека и баг-репортов", "hours": 20,
             "detail": "чаты, почта, сториз — перенос в задачу с деталями"},
            {"id": "backlog", "label": "Ведение бэклога и задач", "hours": 16,
             "detail": "ручные апдейты статусов, приоритеты, комментарии"},
            {"id": "metrics", "label": "Сбор метрик и отчётов", "hours": 14,
             "detail": "запросы, выгрузки, сведение в дашборд вручную"},
            {"id": "onboard", "label": "Онбординг и follow-up клиентов", "hours": 15,
             "detail": "шаблонные письма, контроль шагов, напоминания"},
            {"id": "release", "label": "Релизные заметки и комментарии", "hours": 8,
             "detail": "сбор изменений, тексты, рассылка"},
            {"id": "ticket", "label": "Контроль тикетов и статусов", "hours": 12,
             "detail": "обход очереди, эскалации, ответы «где моя задача»"},
        ],
    },
]

TOOLS = [
    {"id": "chat", "label": "Чат-бот", "factor": 0.65,
     "impl": (60000, 150000), "support": (8000, 15000),
     "what": "бот закрывает повторяющиеся обращения и заявки: отвечает по "
             "сценариям, собирает данные и кладёт их туда, где нужно",
     "pilot": "перевести 5–10 самых частых вопросов на сценарии бота"},
    {"id": "agent", "label": "AI-агент", "factor": 0.85,
     "impl": (90000, 250000), "support": (15000, 30000),
     "what": "модель читает входящее сообщение или документ, понимает смысл, "
             "готовит черновик ответа и передаёт человеку только спорное",
     "pilot": "автоответы и суммаризация обращений с проверкой человеком"},
    {"id": "n8n", "label": "n8n-воркфлоу", "factor": 0.75,
     "impl": (40000, 120000), "support": (5000, 12000),
     "what": "связки между системами: заявка → задача → уведомление → отчёт, "
             "без копирования поля из окна в окно",
     "pilot": "сквозная связка «источник → система → уведомление»"},
    {"id": "tracker", "label": "Интеграция с Яндекс Трекером", "factor": 0.5,
     "impl": (30000, 90000), "support": (4000, 10000),
     "what": "задачи создаются сами: из форм, чатов и писем, с полями, "
             "исполнителем и автоматическими статусами",
     "pilot": "вебхук на создание задач плюс автоназначение и уведомления"},
    {"id": "full", "label": "Комплексная автоматизация", "factor": 0.9,
     "impl": (200000, 500000), "support": (25000, 50000),
     "what": "контур процесса целиком: бот + воркфлоу + трекер + дашборды, "
             "человек остаётся только на исключениях",
     "pilot": "один процесс от входа заявки до отчёта, потом тираж на соседние"},
]

FIRE_TOOL = {"id": "fire", "label": "Уволить всех 🙂", "factor": 1.0,
             "what": "радикальный метод, который мы не рекомендуем"}

ALL_TOOLS = TOOLS + [FIRE_TOOL]

DISCLAIMER = (
    "<b>Дисклеймер.</b> Расчёт ориентировочный: часы и ставки взяты из ваших "
    "ответов и средних по рынку значений, бюджет и сроки — типовой диапазон "
    "для похожих проектов. Это не оферта и не гарантия экономии. Точная оценка "
    "появляется после разбора процесса — обычно на 30-минутном созвоне."
)

COUNT_PRESETS = [
    {"payload": "opt:c:1", "text": "1 человек"},
    {"payload": "opt:c:2", "text": "2"},
    {"payload": "opt:c:4", "text": "3–5"},
    {"payload": "opt:c:8", "text": "6–10"},
    {"payload": "opt:c:18", "text": "11–25"},
    {"payload": "opt:c:x", "text": "Своё число"},
]
COUNT_RANGE = {"opt:c:4": 4, "opt:c:8": 8, "opt:c:18": 18}


# ── Мелкие утилиты ───────────────────────────────────────────────────────────
def esc(value):
    """Экранирование пользовательского текста: сообщения уходят format=html."""
    return html.escape(str(value), quote=False)


def fmt(number):
    return f"{int(round(number)):,}".replace(",", " ")


def money(number):
    return fmt(number) + " ₽"


def hour_rate(salary):
    return round(salary / WORK_HOURS / 5) * 5


def plural(number, forms):
    """plural(2, ("операция", "операции", "операций")) — русские склонения."""
    n = abs(int(number)) % 100
    digit = n % 10
    if 11 <= n <= 14:
        return forms[2]
    if digit == 1:
        return forms[0]
    if 2 <= digit <= 4:
        return forms[1]
    return forms[2]


def capital(text):
    return text[:1].upper() + text[1:] if text else text


def round_to(number, step=1000):
    return int(round(number / step) * step)


def sphere_by_id(sid):
    return next((s for s in SPHERES if s["id"] == sid), None)


def tool_by_id(tid):
    return next((t for t in ALL_TOOLS if t["id"] == tid), None)


def btn(text, payload):
    return {"type": "callback", "text": text, "payload": payload}


def chunk(text, size=TEXT_CHUNK):
    """Резка длинного текста по абзацам, чтобы не упереться в лимит сообщения."""
    if len(text) <= size:
        return [text]
    parts = []
    current = ""
    for block in text.split("\n\n"):
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= size:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(block) > size:
            cut = block.rfind("\n", 0, size)
            cut = cut if cut > size // 2 else size
            parts.append(block[:cut].rstrip())
            block = block[cut:].lstrip()
        current = block
    if current:
        parts.append(current)
    return parts


def emit(text, buttons=None):
    """Текст (или список текстов) + клавиатура на последнем сообщении."""
    texts = text if isinstance(text, list) else chunk(text)
    messages = [{"text": part} for part in texts]
    if buttons and messages:
        messages[-1]["buttons"] = buttons
    return messages


# ── Состояние ────────────────────────────────────────────────────────────────
def new_session():
    return {
        "step": "sphere",
        "sphere": None,
        "sphere_label": None,
        "mode": None,
        "roles": [],
        "pending_role": None,
        "ops": [],
        "tools": [],
        "calc": None,
        "sav": None,
        "updated": time.time(),
    }


def is_expired(session, now=None):
    if not session:
        return True
    return (now or time.time()) - float(session.get("updated") or 0) > SESSION_TTL


def expects_text(session):
    """Шаги, где ждём свободный текст: своё число и текст заявки."""
    return bool(session) and session.get("step") in ("count_text", "feedback")


def headcount(session):
    return sum(role["count"] for role in session["roles"])


PEOPLE_FORMS = ("человек", "человека", "человек")


def roles_summary(session):
    """Один человек — «вы сами»; команда — «роль × сколько»."""
    if session.get("mode") == "self":
        return "вы один, всё на вас"
    return ", ".join(f"{esc(r['label'])} × {r['count']}" for r in session["roles"])


def people_phrase(count):
    return f"{count} {plural(count, PEOPLE_FORMS)}"


def blended_rate(session):
    people = headcount(session)
    if not people:
        return hour_rate(SELF_ROLE["salary"])
    return sum(r["rate"] * r["count"] for r in session["roles"]) / people


# ── Расчёт ───────────────────────────────────────────────────────────────────
def compute_routine(session):
    sphere = sphere_by_id(session.get("sphere")) or SPHERES[0]
    chosen = [op for op in sphere["ops"] if op["id"] in session["ops"]]
    per_person = min(sum(op["hours"] for op in chosen), WORK_HOURS)
    people = headcount(session) or 1
    rate = blended_rate(session)
    hours = per_person * people
    return {
        "sphere_label": sphere["label"],
        "blurb": sphere["blurb"],
        "people": people,
        "rate": rate,
        "per_person": per_person,
        "share": round(per_person / WORK_HOURS * 100),
        "hours": hours,
        "cost_month": hours * rate,
        "cost_year": hours * rate * 12,
        "ops": chosen,
    }


def combined_factor(tools):
    remaining = 1.0
    for tool in tools:
        remaining *= (1 - tool["factor"])
    return min(1 - remaining, 0.92)


def compute_savings(session, calc):
    tools = [t for t in (tool_by_id(tid) for tid in session["tools"]) if t]
    factor = combined_factor(tools)
    saved_hours = calc["hours"] * factor
    saved_money = saved_hours * calc["rate"]
    scale = 1 + 0.10 * max(0, len(tools) - 1) + 0.08 * max(0, len(calc["ops"]) - 2)
    if calc["people"] >= 10:
        scale += 0.25
    if calc["people"] >= 30:
        scale += 0.25
    impl_low = round_to(sum(t["impl"][0] for t in tools) * scale)
    impl_high = round_to(sum(t["impl"][1] for t in tools) * scale)
    support_low = round_to(sum(t["support"][0] for t in tools))
    support_high = round_to(sum(t["support"][1] for t in tools))
    payback = (impl_low + impl_high) / 2 / saved_money if saved_money else None
    return {
        "tools": tools,
        "factor": factor,
        "saved_hours": saved_hours,
        "saved_money": saved_money,
        "saved_year": saved_money * 12,
        "impl_low": impl_low,
        "impl_high": impl_high,
        "support_low": support_low,
        "support_high": support_high,
        "payback": payback,
    }


# ── Клавиатуры ───────────────────────────────────────────────────────────────
def keyboard_sphere():
    return [[btn(s["label"], f"opt:s:{s['id']}")] for s in SPHERES]


def keyboard_mode():
    return [[btn("Только я", "opt:m:self"), btn("Несколько человек", "opt:m:team")],
            [btn("🔄 Начать заново", "opt:reset")]]


def keyboard_roles(session):
    sphere = sphere_by_id(session.get("sphere")) or SPHERES[0]
    rows = [[btn(f"{role['label']} · {money(hour_rate(role['salary']))}/ч", f"opt:r:{i}")]
            for i, role in enumerate(sphere["roles"])]
    if session["roles"]:
        rows.append([btn("Достаточно, к рутине", "opt:n:calc")])
    rows.append([btn("🔄 Начать заново", "opt:reset")])
    return rows


def keyboard_count():
    return [COUNT_PRESETS[i:i + 3] for i in range(0, len(COUNT_PRESETS), 3)]


def keyboard_more():
    return [[btn("Добавить специальность", "opt:n:more")],
            [btn("Считаем рутину", "opt:n:calc")],
            [btn("🔄 Начать заново", "opt:reset")]]


def keyboard_ops(session):
    sphere = sphere_by_id(session.get("sphere")) or SPHERES[0]
    rows = []
    for i, op in enumerate(sphere["ops"]):
        mark = "✅" if op["id"] in session["ops"] else "▫️"
        rows.append([btn(f"{mark} {op['label']} · {op['hours']} ч", f"opt:o:{op['id']}")])
    rows.append([btn("Посчитать рутину", "opt:o:ok"), btn("Сбросить выбор", "opt:o:clear")])
    rows.append([btn("🔄 Начать заново", "opt:reset")])
    return rows


def keyboard_tools_marked(session):
    rows = []
    for tool in ALL_TOOLS:
        if tool["id"] == "fire":
            rows.append([btn(tool["label"], "opt:t:fire")])
            continue
        mark = "✅" if tool["id"] in session["tools"] else "▫️"
        rows.append([btn(f"{mark} {tool['label']}", f"opt:t:{tool['id']}")])
    rows.append([btn("Показать экономию", "opt:t:ok"), btn("Сбросить", "opt:t:clear")])
    rows.append([btn("🔄 Начать заново", "opt:reset")])
    return rows


def keyboard_final():
    return [[btn("💬 Отправить заявку Павлу", "opt:fb")],
            [btn("Пройти заново", "opt:again")]]


# ── Тексты ───────────────────────────────────────────────────────────────────
def text_intro():
    return (
        "Запускаю <b>Оптимизатор</b> — тот же расчёт, что в калькуляторе на сайте, "
        "только по шагам и по вашему процессу.\n\n"
        "Вопросов шесть, ответ занимает пару минут. На выходе — часы рутины, их "
        "стоимость, экономия по инструментам, чек-лист внедрения и вилка бюджета. "
        "В любой момент можно начать заново.\n\n"
        "<b>Шаг 1 из 6 · Сфера деятельности</b>"
    )


def text_mode(session):
    return (
        f"<b>{esc(session['sphere_label'])}</b> — принято.\n\n"
        "<b>Шаг 2 из 6 · Кого оптимизируем?</b>\n"
        "Рутину считаем по людям: чем больше одинаковых рук на одной операции, "
        "тем быстрее окупается автоматизация."
    )


def text_roles(session):
    current = ", ".join(f"{esc(r['label'])} × {r['count']}" for r in session["roles"])
    lines = [
        "<b>Шаг 2 из 6 · Кого оптимизируем?</b>",
        "",
        "Выберите специальность — по ней посчитаем стоимость часа рутины.",
    ]
    if current:
        lines += ["", f"Уже в расчёте: {current}."]
    return "\n".join(lines)


def text_count(session):
    role = session["pending_role"]
    return (
        f"<b>{esc(role['label'])}</b> — сколько таких человек?\n"
        "Ставка по этой роли: " + f"{money(role['rate'])}/ч. "
        "Можно кнопкой, можно написать число сообщением."
    )


def text_more(session):
    return (
        f"Добавил: {esc(session['last_role'])}. В расчёте "
        f"{people_phrase(headcount(session))}.\n\n"
        "Докидываем специальность или переходим к рутине?"
    )


def text_ops(session):
    sphere = sphere_by_id(session.get("sphere")) or SPHERES[0]
    total = sum(op["hours"] for op in sphere["ops"] if op["id"] in session["ops"])
    lines = [
        "<b>Шаг 3 из 6 · Что чаще всего повторяете руками?</b>",
        "",
        "Отмечайте операции — часы сложатся. Нажать ещё раз = снять отметку.",
        "",
    ]
    for i, op in enumerate(sphere["ops"], start=1):
        mark = "✅" if op["id"] in session["ops"] else "▫️"
        lines.append(f"{mark} {i}. {esc(op['label'])} · {op['hours']} ч/мес")
    lines += ["", f"Отмечено {len(session['ops'])} "
                  f"{plural(len(session['ops']), ('операцию', 'операции', 'операций'))}"
                  f" — {total} ч/мес на человека."]
    return "\n".join(lines)


def text_tools(session, calc):
    lines = [
        "<b>Шаг 5 из 6 · Чем убираем рутину?</b>",
        "",
        "Отметьте инструменты, которые реально рассматриваете — можно несколько, "
        "эффекты сложатся. Последняя кнопка шуточная, но очень в тему 🙂",
        "",
    ]
    for i, tool in enumerate(ALL_TOOLS):
        if tool["id"] == "fire":
            lines.append(f"▫️ {i + 1}. {esc(tool['label'])} — {esc(tool['what'])}")
            continue
        mark = "✅" if tool["id"] in session["tools"] else "▫️"
        pct = int(round(tool["factor"] * 100))
        lines.append(f"{mark} {i + 1}. {esc(tool['label'])} — забирает до {pct}% "
                     f"времени рутины")
    lines += ["", f"Сейчас рутины: {fmt(calc['hours'])} ч/мес. Выберите инструмент — "
                  "покажу экономию."]
    return "\n".join(lines)


def text_routine(session, calc):
    roles = roles_summary(session)
    ops = "\n".join(f"  • {esc(op['label'])} — {op['hours']} ч/мес на человека "
                    f"({esc(op['detail'])})" for op in calc["ops"])
    team = people_phrase(calc["people"])
    return [
        (
            "<b>Шаг 4 из 6 · Что получилось по рутине</b>\n\n"
            f"<b>Ситуация.</b> {esc(calc['sphere_label'])}, {roles}. Повторов на "
            f"{calc['per_person']} ч/мес на человека — это ~{calc['share']}% "
            f"рабочего месяца. {capital(esc(calc['blurb']))}.\n\n"
            f"<b>Операции в расчёте:</b>\n{ops}"
        ),
        (
            f"<b>Часы рутины:</b> {fmt(calc['hours'])} ч/мес на {team}, "
            f"{fmt(calc['hours'] * 12)} ч/год.\n"
            f"<b>Стоимость:</b> ~{money(calc['cost_month'])}/мес по смешанной ставке "
            f"{money(calc['rate'])}/ч — это {money(calc['cost_year'])} в год.\n\n"
            "Сумма честная, но это не «деньги в минус»: столько стоит время, которое "
            "люди отдают повторам вместо работы, где они приносят выручку.\n\n"
            "Теперь посмотрим, что отсюда убирается."
        ),
    ]


def text_fire(calc):
    return FIRE_TEXT.replace("{money}", money(calc["cost_month"]))


FIRE_TEXT = (
    "Считаем: уволить всех — и рутина исчезнет вместе с процессом 🙂\n\n"
    "<b>Экономия по расчёту — 100% часов, {money} в месяц.</b>\n\n"
    "Минус в том, что вместе с часом уйдут заявки, клиенты и отчётность, поэтому "
    "оставим это как мерзкую шутку про масштаб проблемы.\n\n"
    "Смысл, впрочем, ровно этот: рутину нужно не «делать быстрее», а убирать "
    "совсем — оставив людей там, где они приносят деньги. Выбирайте настоящие "
    "инструменты, ниже те же кнопки."
)


def text_savings(session, calc, sav):
    names = ", ".join(esc(t["label"]) for t in sav["tools"])
    freed = sav["saved_hours"] / max(1, calc["people"])
    top = "\n".join(
        f"  • {esc(op['label'])} ({op['hours']} ч/мес на человека): {esc(op['detail'])}"
        for op in sorted(calc["ops"], key=lambda o: -o["hours"])[:3])
    return [
        (
            "<b>Шаг 6 из 6 · Экономия</b>\n\n"
            f"<b>Инструменты:</b> {names}.\n"
            f"<b>Забираем:</b> {int(round(sav['factor'] * 100))}% времени рутины "
            "(эффекты независимых инструментов складываются, но потолок честной "
            "автоматизации — ~92%: исключения всегда остаются).\n\n"
            f"• Часы: было {fmt(calc['hours'])} → станет "
            f"{fmt(calc['hours'] - sav['saved_hours'])} ч/мес руками; "
            f"экономия <b>{fmt(sav['saved_hours'])} ч/мес</b>, "
            f"{fmt(sav['saved_hours'] * 12)} ч/год.\n"
            f"• Деньги: <b>{money(sav['saved_money'])}/мес</b>, "
            f"{money(sav['saved_year'])} в год.\n"
            f"• На человека: {fmt(freed)} ч/мес освобождается — это примерно "
            f"{round(freed / WORK_HOURS * 100)}% его месяца."
        ),
        "<b>Что именно освобождается в первую очередь:</b>\n" + top,
    ]


def text_checklist(calc, sav):
    ops = sorted(calc["ops"], key=lambda o: -o["hours"])
    first = ops[0]["label"] if ops else "повторяющаяся операция"
    first_hours = ops[0]["hours"] if ops else 0
    second = ops[1]["label"] if len(ops) > 1 else "соседние операции"
    pilot = sav["tools"][0]["pilot"] if sav["tools"] else "переводим шаг в сценарий"
    tool_names = ", ".join(t["label"].lower() for t in sav["tools"]) or "связки"
    steps = [
        ("Зафиксировать процесс как есть",
         f"Опишите операцию «{esc(first)}» по шагам: кто начинает, в какой системе "
         "живут данные, что считается «готово». 20–30 минут — и автоматизация "
         "перестаёт быть абстракцией.", "0,5 дня, своими силами"),
        ("Выбрать один пилот",
         f"Берём операцию с максимумом часов — «{esc(first)}» ({first_hours} ч/мес на "
         f"человека): {esc(pilot)}. Остальное только после первого результата.",
         "1 неделя"),
        ("Подготовить данные и доступы",
         "Регламенты, таблицы-источники, API-ключи и права в системах, плюс ответственный "
         "за исключения. Без этого шага любой воркфлоу упирается в «а у нас нет доступа».",
         "2–3 дня, параллельно с разработкой"),
        ("Собрать MVP и две недели гонять рядом с руками",
         f"Первая версия ({esc(tool_names)}) работает параллельно с человеком: автомат "
         "делает, человек проверяет и правит правила. Так находятся крайние случаи, "
         "которые никто не предскажет.", "1–2 недели"),
        ("Замерить часы до и после",
         "Простой замер: сколько времени уходило и сколько осталось. Только он отличает "
         "«кажется, стало быстрее» от реальной экономии из расчёта выше.",
         "2 недели, по ходу пилота"),
        ("Передать владельцу и задокументировать",
         "Кто правит сценарии, куда писать при сбое, как добавить новую операцию. "
         "Автоматизация без ответственного через квартал превращается в новый ручной процесс.",
         "1 день"),
        ("Тиражировать",
         f"Когда по «{esc(first)}» есть цифра — добавляем «{esc(second)}» и остальные "
         "операции из расчёта: они встают на отлаженный контур заметно дешевле.",
         "по 1 операции за 1–2 недели"),
    ]
    lines = ["<b>Пошаговый чек-лист внедрения</b>", ""]
    for i, (title, body, when) in enumerate(steps, start=1):
        lines.append(f"<b>{i}. {title}</b>\n   {body}\n   <i>{when}</i>\n")
    return "\n".join(lines).rstrip()


def text_rollout(sav):
    what = "\n".join(f"  • <b>{esc(t['label'])}</b>: {esc(t['what'])}"
                     for t in sav["tools"])
    support = ""
    if sav["support_high"]:
        support = (f"\n<b>Сопровождение:</b> {money(sav['support_low'])}–"
                   f"{money(sav['support_high'])}/мес — правки сценариев, мониторинг, "
                   "разбор исключений.")
    payback = ""
    if sav["payback"]:
        months = sav["payback"]
        pretty = (f"{months:.1f}".replace(".", ",").rstrip("0").rstrip(",")
                  if months < 10 else str(int(round(months))))
        payback = (f"\nПри экономии {money(sav['saved_money'])}/мес средний бюджет "
                   f"окупается за ~{pretty} мес.")
    return [
        (
            "<b>Стоимость внедрения</b>\n\n"
            f"{what}\n\n"
            f"<b>Примерный бюджет:</b> {money(sav['impl_low'])}–{money(sav['impl_high'])} "
            f"разово.{support}{payback}"
        ),
        DISCLAIMER + "\n\nДальше за вами: собрать по чек-листу самим, забрать готовые "
        "шаблоны или прислать пару строк про процесс — разберу и пришлю конкретный план "
        "по вашему случаю.",
    ]


TEXT_FEEDBACK_PROMPT = (
    "Напишите одним сообщением, что за процесс и что в нём мешает — и контакт, "
    "если нужен ответ. Перешлю Павлу: такие запросы он разбирает сам.\n\n"
    "Можно и просто спросить по расчёту выше — тоже перешлю."
)

TEXT_FEEDBACK_DONE = (
    "Отправил Павлу вместе с вашим расчётом — обычно отвечает в течение дня.\n\n"
    "Если захотите пересчитать другой процесс, кнопка «Оптимизатор» ниже."
)


# ── Диспетчер кнопок ─────────────────────────────────────────────────────────
TEXT_STALE = ("Похоже, это кнопка из прошлого расчёта. "
              "Нажмите «Оптимизатор» — начнём с начала.")

# шаги, которые бессмысленны без выбранной сферы (кнопки «сфера»/«режим» — нет)
STALE_GUARDED = {"r", "c", "n", "o", "t"}

# сессия без сферы — значит кнопки пришли из давно сброшенного расчёта
def is_stale(session):
    return sphere_by_id(session.get("sphere")) is None


def start(session=None):
    """Точка входа по кнопке «Оптимизатор»."""
    return new_session(), emit(text_intro(), keyboard_sphere())


def dispatch(payload, session):
    """Один клик по клавиатуре → (новое состояние, список сообщений)."""
    if not payload or not payload.startswith("opt:"):
        return session, []
    # добиваем недостающие поля: состояние могло прийти из более старой версии
    session = {**new_session(), **(session or {})}
    session["updated"] = time.time()
    parts = payload.split(":")
    kind = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    if kind == "reset" or kind == "again":
        return start(session)
    if kind == "start":
        return start(session)
    if kind == "cancel":
        return {**session, "step": "done"}, emit(
            "Оптимизатор остановил. Захотите продолжить — нажмите «Оптимизатор» ещё раз.")

    handler = HANDLERS.get(kind)
    if not handler:
        return session, emit("Не распознал кнопку — нажмите «Оптимизатор», "
                             "чтобы начать заново.")
    if kind in STALE_GUARDED and is_stale(session):
        # тап по клавиатуре из сброшенного/просроченного расчёта
        return session, emit(TEXT_STALE)
    return handler(session, arg)


def on_sphere(session, arg):
    sphere = sphere_by_id(arg)
    if not sphere:
        return session, emit("Такой сферы нет в списке — выберите из кнопок.")
    session.update(sphere=sphere["id"], sphere_label=sphere["label"], mode=None,
                   roles=[], pending_role=None, ops=[], tools=[], calc=None, sav=None,
                   step="mode")
    return session, emit(text_mode(session), keyboard_mode())


def on_mode(session, arg):
    if session["step"] != "mode":
        return session, emit("Сначала выберите сферу — кнопки выше.")
    if arg == "self":
        session["mode"] = "self"
        session["roles"] = [{"label": SELF_ROLE["label"], "count": 1,
                             "rate": hour_rate(SELF_ROLE["salary"])}]
        session["last_role"] = f"{SELF_ROLE['label']} × 1"
        return to_ops(session)
    session["mode"] = "team"
    session["step"] = "role"
    return session, emit(text_roles(session), keyboard_roles(session))


def on_role(session, arg):
    sphere = sphere_by_id(session.get("sphere"))
    if not sphere:
        return start(session)
    try:
        role = sphere["roles"][int(arg)]
    except (ValueError, IndexError):
        return session, emit("Специальность не распознана — выберите из списка.")
    session["pending_role"] = {"label": role["label"], "rate": hour_rate(role["salary"])}
    session["step"] = "count"
    return session, emit(text_count(session), keyboard_count())


def on_count(session, arg):
    role = session.get("pending_role")
    if not role:
        return on_role(session, "0") if session.get("sphere") else start(session)
    if arg == "x":
        session["step"] = "count_text"
        return session, emit(f"Сколько человек в роли «{esc(role['label'])}»? "
                             "Напишите число, например 7.")
    count = COUNT_RANGE.get(f"opt:c:{arg}")
    if count is None:
        try:
            count = int(arg)
        except ValueError:
            return session, emit("Не понял количество — выберите кнопкой или "
                                 "напишите число.")
    return add_role(session, role["label"], count, role["rate"])


def add_role(session, label, count, rate):
    count = max(1, min(int(count), MAX_HEADCOUNT))
    roles = list(session["roles"])
    for role in roles:
        if role["label"] == label:
            role["count"] += count
            break
    else:
        roles.append({"label": label, "count": count, "rate": rate})
    session["roles"] = roles
    session["last_role"] = f"{label} × {count}"
    session["pending_role"] = None
    session["step"] = "more_roles"
    return session, emit(text_more(session), keyboard_more())


def on_more(session, arg):
    if arg == "more":
        session["step"] = "role"
        return session, emit(text_roles(session), keyboard_roles(session))
    return to_ops(session)


def to_ops(session):
    sphere = sphere_by_id(session.get("sphere"))
    if not sphere:
        return start(session)
    if not session["roles"]:
        session["roles"] = [{"label": SELF_ROLE["label"], "count": 1,
                             "rate": hour_rate(SELF_ROLE["salary"])}]
        session["mode"] = "self"
    session["step"] = "ops"
    return session, emit(text_ops(session), keyboard_ops(session))


def on_op(session, arg):
    sphere = sphere_by_id(session.get("sphere"))
    if not sphere:
        # кнопка со старого сообщения: сфера уже сбросилась или её не выбирали
        return session, emit(TEXT_STALE)
    if arg == "clear":
        session["ops"] = []
        return session, emit(text_ops(session), keyboard_ops(session))
    if arg == "ok":
        if not session["ops"]:
            return session, emit("Отметьте хотя бы одну операцию — иначе считать нечего. "
                                 "Можно начать заново кнопкой внизу.")
        calc = compute_routine(session)
        session["calc"] = calc
        session["step"] = "tools"
        return session, emit(text_routine(session, calc), keyboard_tools_marked(session))
    op = next((o for o in sphere["ops"] if o["id"] == arg), None)
    if not op:
        return session, emit("Такой операции нет в списке — выберите из кнопок.")
    ops = list(session["ops"])
    ops.remove(op["id"]) if op["id"] in ops else ops.append(op["id"])
    session["ops"] = ops
    return session, emit(text_ops(session), keyboard_ops(session))


def on_tool(session, arg):
    if session.get("step") not in ("tools", "savings", "rollout"):
        return session, emit(TEXT_STALE)
    calc = session.get("calc") or compute_routine(session)
    session["calc"] = calc
    if arg == "clear":
        session["tools"] = []
        return session, emit(text_tools(session, calc), keyboard_tools_marked(session))
    if arg == "ok":
        if not session["tools"]:
            return session, emit("Выберите инструмент 🙂 «Уволить всех» тоже считается.")
        sav = compute_savings(session, calc)
        session["sav"] = sav
        session["step"] = "savings"
        return session, emit(text_savings(session, calc, sav),
                             [[btn("Дальше: чек-лист внедрения", "opt:t:plan")],
                              [btn("Выбрать другие инструменты", "opt:t:back")]])
    if arg == "plan":
        sav = session.get("sav") or compute_savings(session, calc)
        session["step"] = "rollout"
        messages = emit(text_checklist(calc, sav))
        messages += emit(text_rollout(sav), keyboard_final())
        return session, messages
    if arg == "back":
        session["step"] = "tools"
        return session, emit(text_tools(session, calc), keyboard_tools_marked(session))
    tool = tool_by_id(arg)
    if not tool:
        return session, emit("Такого инструмента нет в списке.")
    if tool["id"] == "fire":
        return session, emit(text_fire(calc) + "\n\n"
                             "Шутку в расчёт не беру — отмечайте настоящие инструменты.") \
            + emit(text_tools(session, calc), keyboard_tools_marked(session))
    tools = list(session["tools"])
    tools.remove(tool["id"]) if tool["id"] in tools else tools.append(tool["id"])
    session["tools"] = tools
    return session, emit(text_tools(session, calc), keyboard_tools_marked(session))


def on_feedback(session, _arg=None):
    session["step"] = "feedback"
    return session, emit(TEXT_FEEDBACK_PROMPT)


HANDLERS = {
    "s": on_sphere,
    "m": on_mode,
    "r": on_role,
    "c": on_count,
    "n": on_more,
    "o": on_op,
    "t": on_tool,
    "fb": on_feedback,
}


# ── Текстовые сообщения внутри активной сессии ───────────────────────────────
def dispatch_text(text, session):
    """Свободный текст на шагах, где он ожидается: число и заявка."""
    session = {**new_session(), **(session or {})}
    session["updated"] = time.time()
    step = session.get("step")

    if step == "count_text":
        role = session.get("pending_role")
        if not role:
            # состояние пришло без роли — возвращаем к выбору специальности
            return to_ops(session) if session.get("roles") else start(session)
        match = re.search(r"\d+", text or "")
        if not match:
            return session, emit("Нужно число — например «7» или «примерно 12».")
        return add_role(session, role["label"], int(match.group()), role["rate"])

    if step == "feedback":
        calc = session.get("calc") or {}
        summary = ""
        if calc:
            summary = (f"\n\nЧерновик расчёта: {calc.get('sphere_label')} · "
                       f"{calc.get('people')} чел · {fmt(calc.get('hours', 0))} ч/мес "
                       f"рутины · ~{money(calc.get('cost_month', 0))}/мес.")
        messages = emit(
            TEXT_FEEDBACK_DONE + summary,
            [[btn("🔧 Оптимизатор заново", "opt:again"),
              btn("Хочу такое же под свой процесс", "want_task")]])
        # «admin» — сигнал транспорту переслать этот текст владельцу
        messages[-1]["admin"] = text
        return {**session, "step": "done"}, messages

    return session, []
