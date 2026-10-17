#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_CONFIG="${SSH_CONFIG:-$ROOT/infra/ssh_config}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/opt/mynameisjev}"

usage() {
    printf 'Usage: %s {dashboard|world|agents}\n' "$0" >&2
}

if [[ $# -ne 1 ]]; then
    usage
    exit 2
fi
if [[ ! -r "$SSH_CONFIG" ]]; then
    printf 'SSH config is missing or unreadable: %s\n' "$SSH_CONFIG" >&2
    exit 2
fi
if [[ ! "$REMOTE_PROJECT_DIR" =~ ^/[A-Za-z0-9_./-]+$ ]]; then
    printf 'REMOTE_PROJECT_DIR must be an absolute path containing only letters, numbers, /, ., _, and -.\n' >&2
    exit 2
fi
for command_name in ssh rsync; do
    command -v "$command_name" >/dev/null || {
        printf '%s is required.\n' "$command_name" >&2
        exit 2
    }
done

case "$1" in
    dashboard)
        host=vm2
        compose_file=dashboard/docker-compose.yml
        files=(pyproject.toml README.md .dockerignore contracts src dashboard)
        deploy_command="docker compose --env-file .env -f dashboard/docker-compose.yml up -d --build"
        ;;
    world)
        host=vm3
        compose_file=world/docker-compose.yml
        files=(pyproject.toml README.md .dockerignore contracts src world)
        deploy_command="docker compose --env-file .env -f world/docker-compose.yml up -d --build"
        ;;
    agents)
        host=vm4
        compose_file=world/agents/docker-compose.yml
        files=(pyproject.toml README.md .dockerignore contracts src world/agents)
        deploy_command="docker compose --env-file .env -f world/agents/docker-compose.yml --profile agents build"
        ;;
    *)
        usage
        exit 2
        ;;
esac

for file in "${files[@]}"; do
    if [[ ! -e "$ROOT/$file" ]]; then
        printf 'Required deployment path is missing: %s\n' "$file" >&2
        exit 2
    fi
done

printf 'Preparing %s on %s (no secrets will be copied).\n' "$1" "$host"
ssh -F "$SSH_CONFIG" -o BatchMode=yes "$host" \
    "mkdir -p '$REMOTE_PROJECT_DIR' && test -f '$REMOTE_PROJECT_DIR/.env' && mode=\$(stat -c %a '$REMOTE_PROJECT_DIR/.env') && case \"\$mode\" in 400|600) ;; *) printf 'Remote .env must have mode 400 or 600.\\n' >&2; exit 1 ;; esac && command -v docker >/dev/null && docker compose version"
rsync -a --compress --mkpath \
    --exclude='__pycache__/' \
    --exclude='.env*' \
    --exclude='*.db' \
    --exclude='*.sqlite*' \
    --exclude='*.pem' \
    --exclude='*.key' \
    --exclude='*password*' \
    --exclude='*credential*' \
    --exclude='*secret*' \
    --exclude='data/' \
    --exclude='secrets.toml' \
    "${files[@]/#/$ROOT/}" \
    -e "ssh -F $SSH_CONFIG -o BatchMode=yes" \
    "$host:$REMOTE_PROJECT_DIR/"
ssh -F "$SSH_CONFIG" -o BatchMode=yes "$host" \
    "cd '$REMOTE_PROJECT_DIR' && $deploy_command"

if [[ "$1" == agents ]]; then
    printf 'Agent images are built but not started. Review the remote .env and explicitly run the agents only when ready.\n'
    printf 'Manual command: ssh -F %q %q %q\n' "$SSH_CONFIG" "$host" \
        "cd '$REMOTE_PROJECT_DIR' && docker compose --env-file .env -f $compose_file --profile agents up --abort-on-container-exit"
else
    printf '%s deployed on %s.\n' "$1" "$host"
fi
