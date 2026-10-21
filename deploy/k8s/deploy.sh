#!/usr/bin/env bash
# Раскатывает lead-bot в кластере: namespace, PVC, configmap, deployment.
# Секреты — отдельно, k8s/sync-secrets.sh.
#
#   k8s/deploy.sh            # применить и перезапустить
#   k8s/deploy.sh --status   # только статус и логи

set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
kubeconfig=${KUBECONFIG:-${HOME}/.k8s/doclub-ru.yaml}
namespace=lead-bot

kubectl() {
  if [[ -f $kubeconfig ]]; then
    command kubectl --kubeconfig "$kubeconfig" "$@"
  else
    command kubectl "$@"
  fi
}

status() {
  kubectl -n "$namespace" get pods -o wide
  echo
  kubectl -n "$namespace" logs -l app.kubernetes.io/name=lead-bot --tail=40 --max-log-requests=2 || true
}

if [[ ${1:-} == "--status" ]]; then
  status
  exit 0
fi

# namespace создаётся отдельно: он не удаляется вместе с остальными ресурсами
kubectl apply -f "$root/deploy/k8s/namespace.yaml"
kubectl apply -k "$root/deploy/k8s"

if ! kubectl -n "$namespace" get secret lead-bot-env >/dev/null 2>&1; then
  echo "Секрет lead-bot-env не найден — сначала k8s/sync-secrets.sh" >&2
  exit 1
fi

kubectl -n "$namespace" rollout restart deployment/lead-bot
kubectl -n "$namespace" rollout status deployment/lead-bot --timeout=300
status
