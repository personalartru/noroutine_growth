#!/usr/bin/env bash
# Делает ограниченный kubeconfig для деплоя lead-бота.
#
# Зачем: в публичном репозитории нельзя держать админский kubeconfig.
# Здесь создаётся сервис-аккаунт с правами только в namespace lead-bot,
# а на выход — готовый base64, который вставляется в секрет KUBECONFIG.
#
#   bash deploy/k8s/make-sa-kubeconfig.sh
#
# Нужен рабочий админский kubeconfig (по умолчанию ~/.k8s/doclub-ru.yaml)
# и kubectl. На выходе — строка base64 и файл deploy/k8s/sa-kubeconfig.yaml.

set -euo pipefail

root=$(cd "$(dirname "$0")/../.." && pwd)
kubeconfig=${KUBECONFIG:-${HOME}/.k8s/doclub-ru.yaml}
namespace=lead-bot
sa=lead-bot-deploy
out=$root/deploy/k8s/sa-kubeconfig.yaml

kubectl() {
  if [[ -f $kubeconfig ]]; then
    command kubectl --kubeconfig "$kubeconfig" "$@"
  else
    command kubectl "$@"
  fi
}

echo "==> 1/5 создаём namespace"
kubectl apply -f "$root/deploy/k8s/namespace.yaml" >/dev/null

echo "==> 2/5 сервис-аккаунт $sa"
kubectl -n "$namespace" create serviceaccount "$sa" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> 3/5 права только в namespace $namespace"
cat <<EOF | kubectl apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: lead-bot-deploy
  namespace: $namespace
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "services", "configmaps", "secrets", "persistentvolumeclaims", "serviceaccounts", "events"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["batch"]
    resources: ["jobs", "cronjobs"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apiextensions.k8s.io"]
    resources: ["customresourcedefinitions"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: lead-bot-deploy
  namespace: $namespace
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: lead-bot-deploy
subjects:
  - kind: ServiceAccount
    name: $sa
    namespace: $namespace
EOF

echo "==> 4/5 токен сервис-аккаунта (1 год)"
token=$(kubectl -n "$namespace" create token "$sa" --duration=8760h 2>/dev/null) || {
  echo "Не удалось создать токен: возможно, в кластере отключён TokenRequest API." >&2
  echo "Тогда используйте ограниченный kubeconfig вручную или задеплойте с машины с kubectl." >&2
  exit 1
}

server=$(kubectl config view --kubeconfig "$kubeconfig" -o jsonpath='{.clusters[0].cluster.server}')
ca=$(kubectl config view --kubeconfig "$kubeconfig" --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')

echo "==> 5/5 собираем ограниченный kubeconfig"
cat > "$out" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: mks
    cluster:
      server: $server
      certificate-authority-data: $ca
users:
  - name: $sa
    user:
      token: $token
contexts:
  - name: mks
    context:
      cluster: mks
      user: $sa
      namespace: $namespace
current-context: mks
EOF

echo
echo "Готово: $out"
echo "Проверка:"
echo "  kubectl --kubeconfig $out -n $namespace get pods"
echo
echo "Скопируйте эту строку в секрет KUBECONFIG (репозиторий personalartru/noroutine_growth):"
base64 < "$out" | tr -d '\n'
echo
