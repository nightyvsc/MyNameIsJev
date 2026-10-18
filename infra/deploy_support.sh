#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_CONFIG="${SSH_CONFIG:-$ROOT/infra/ssh_config}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/opt/mynameisjev}"

usage() {
    printf 'Usage: %s {gateway|dashboard|world|agents|loadtest}\n' "$0" >&2
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
for command_name in ssh; do
    command -v "$command_name" >/dev/null || {
        printf '%s is required.\n' "$command_name" >&2
        exit 2
    }
done
if [[ "$1" != loadtest ]] && ! command -v rsync >/dev/null; then
    printf 'rsync is required for this deployment.\n' >&2
    exit 2
fi
if [[ "$1" == loadtest ]] && ! command -v scp >/dev/null; then
    printf 'scp is required for the VM6 runner deployment.\n' >&2
    exit 2
fi

case "$1" in
    gateway)
        host=vm1
        compose_file=infra/gateway-compose.yml
        files=(pyproject.toml README.md .dockerignore contracts docs scripts/backup_sqlite.py src infra/gateway-compose.yml)
        deploy_command="docker compose --env-file .env -f infra/gateway-compose.yml up -d --build"
        require_env=true
        ;;
    dashboard)
        host=vm2
        compose_file=dashboard/docker-compose.yml
        files=(pyproject.toml README.md .dockerignore contracts src dashboard)
        deploy_command="docker compose --env-file .env -f dashboard/docker-compose.yml up -d --build"
        require_env=true
        ;;
    world)
        host=vm3
        compose_file=world/docker-compose.yml
        files=(pyproject.toml README.md .dockerignore contracts src world)
        deploy_command="docker compose --env-file .env -f world/docker-compose.yml up -d --build"
        require_env=true
        ;;
    agents)
        host=vm4
        compose_file=world/agents/docker-compose.yml
        files=(pyproject.toml README.md .dockerignore contracts src world/agents)
        deploy_command="docker compose --env-file .env -f world/agents/docker-compose.yml --profile agents build"
        require_env=true
        ;;
    loadtest)
        host=vm6
        REMOTE_PROJECT_DIR="${LOADTEST_REMOTE_PROJECT_DIR:-/home/estudiante/.local/share/mynameisjev}"
        compose_file=
        files=(scripts/loadtest_gateway.py)
        deploy_command="chmod 0755 scripts/loadtest_gateway.py"
        require_env=false
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

relative_files=()
for file in "${files[@]}"; do
    relative_files+=("$ROOT/./$file")
done

printf 'Preparing %s on %s (no secrets will be copied).\n' "$1" "$host"
remote_preflight="mkdir -p '$REMOTE_PROJECT_DIR'"
if [[ "$require_env" == true ]]; then
    remote_preflight+=" && test -f '$REMOTE_PROJECT_DIR/.env' && mode=\$(stat -c %a '$REMOTE_PROJECT_DIR/.env') && case \"\$mode\" in 400|600) ;; *) printf 'Remote .env must have mode 400 or 600.\\n' >&2; exit 1 ;; esac"
fi
if [[ "$1" == loadtest ]]; then
    remote_preflight+=" && command -v python3 >/dev/null && command -v docker >/dev/null && docker compose version"
else
    remote_preflight+=" && command -v docker >/dev/null && docker compose version"
fi
ssh -F "$SSH_CONFIG" -o BatchMode=yes "$host" "$remote_preflight"
if [[ "$1" == loadtest ]]; then
    ssh -F "$SSH_CONFIG" -o BatchMode=yes "$host" \
        "mkdir -p '$REMOTE_PROJECT_DIR/scripts'"
    scp -F "$SSH_CONFIG" -o BatchMode=yes \
        "$ROOT/scripts/loadtest_gateway.py" \
        "$host:$REMOTE_PROJECT_DIR/scripts/loadtest_gateway.py"
else
    rsync -a --compress --mkpath --relative \
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
        "${relative_files[@]}" \
        -e "ssh -F $SSH_CONFIG -o BatchMode=yes" \
        "$host:$REMOTE_PROJECT_DIR/"
fi
ssh -F "$SSH_CONFIG" -o BatchMode=yes "$host" \
    "cd '$REMOTE_PROJECT_DIR' && $deploy_command"

if [[ "$1" == agents ]]; then
    printf 'Agent images are built but not started. Review the remote .env and explicitly run the agents only when ready.\n'
    printf 'Manual command: ssh -F %q %q %q\n' "$SSH_CONFIG" "$host" \
        "cd '$REMOTE_PROJECT_DIR' && docker compose --env-file .env -f $compose_file --profile agents up --abort-on-container-exit"
elif [[ "$1" == loadtest ]]; then
    printf 'VM6 runner deployed, not executed. Provision its mode-600 .env and approve the estimated spend cap before running Jev requests.\n'
else
    printf '%s deployed on %s.\n' "$1" "$host"
fi
