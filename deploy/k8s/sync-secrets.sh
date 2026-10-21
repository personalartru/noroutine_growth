#!/usr/bin/env bash
# Кладёт секреты в namespace lead-bot из файла .env.k8s в корне репозитория.
#
#   k8s/sync-secrets.sh [--dry-run]
#
# Формат .env.k8s (по одной строке KEY=VALUE):
#   TELEGRAM_BOT_TOKEN=...
#   LEAD_CHANNEL_USERNAME=@noroutine2026
#   LEAD_ADMIN_CHAT_ID=270479866
#   MAX_BOT_TOKEN=...
#   MAX_ADMIN_CHAT_ID=60669315
#   MAX_PING_CHAT_ID=485434975

set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
kubeconfig=${KUBECONFIG:-${HOME}/.k8s/doclub-ru.yaml}
namespace=lead-bot
env_file=${ENV_FILE:-$root/.env.k8s}
dry_run=0

kubectl() {
  if [[ -f $kubeconfig ]]; then
    command kubectl --kubeconfig "$kubeconfig" "$@"
  else
    command kubectl "$@"
  fi
}

if [[ ${1:-} == "--dry-run" ]]; then
  dry_run=1
fi

if [[ ! -f $env_file ]]; then
  echo "Файл $env_file не найден" >&2
  exit 1
fi

args=()
while IFS= read -r line; do
  [[ -z $line || $line == \#* ]] && continue
  key=${line%%=*}
  value=${line#*=}
  value=${value%\"}
  value=${value#\"}
  args+=(--from-literal="$key=$value")
done < "$env_file"

if [[ ${#args[@]} -eq 0 ]]; then
  echo "В $env_file нет переменных" >&2
  exit 1
fi

if [[ $dry_run -eq 1 ]]; then
  echo "dry-run: секрет lead-bot-env из $env_file ($((${#args[@]} / 2)) переменных)"
  exit 0
fi

kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$namespace" create secret generic lead-bot-env "${args[@]}" --dry-run=client -o yaml | kubectl apply -f -
echo "Секрет lead-bot-env обновлён"
