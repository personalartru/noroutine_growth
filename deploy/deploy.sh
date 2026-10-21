#!/usr/bin/env bash
# Обновление и перезапуск бота на сервере.
# Запуск: sudo bash deploy/deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/noroutine-growth}"
cd "$APP_DIR"

echo "==> git pull"
git pull --ff-only

echo "==> зависимости"
./.venv/bin/pip install -q -r requirements.txt

echo "==> пересборка лид-магнита"
./.venv/bin/python build_materials.py

echo "==> перезапуск"
SUDO=""
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; fi
$SUDO systemctl restart noroutine-bot
sleep 2
$SUDO systemctl --no-pager --lines=5 status noroutine-bot || true

echo "==> проверка"
./.venv/bin/python bot.py --check
