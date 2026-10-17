#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_CONFIG="${SSH_CONFIG:-$ROOT/infra/ssh_config}"

if [[ ! -r "$SSH_CONFIG" ]]; then
    printf 'SSH config is missing or unreadable: %s\n' "$SSH_CONFIG" >&2
    exit 2
fi
command -v ssh >/dev/null || {
    printf 'ssh is required.\n' >&2
    exit 2
}

status=0
for host in vm1 vm2 vm3 vm4 vm5 vm6; do
    printf '%s: ' "$host"
    if ! ssh -F "$SSH_CONFIG" -o BatchMode=yes "$host" '
        . /etc/os-release
        printf "%s (%s); " "$(hostname)" "${PRETTY_NAME:-unknown}"
        python3 --version 2>&1 || true
        if command -v docker >/dev/null 2>&1; then
            docker --version
        else
            printf "Docker not installed\n"
        fi
    '; then
        printf 'SSH or inventory check failed.\n' >&2
        status=1
    fi
done
exit "$status"
