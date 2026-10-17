#!/usr/bin/env bash
set -euo pipefail

if (( EUID == 0 )); then
    SUDO=()
else
    if ! command -v sudo >/dev/null 2>&1; then
        printf 'Error: run as root or install sudo and run this script again.\n' >&2
        exit 1
    fi
    SUDO=(sudo)
fi

if [[ ! -r /etc/os-release ]]; then
    printf 'Error: cannot identify this operating system (/etc/os-release missing).\n' >&2
    exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release

case "${ID:-}" in
    ubuntu)
        "${SUDO[@]}" apt-get update
        "${SUDO[@]}" apt-get install -y python3.11 python3.11-venv python3-pip git curl
        if apt-cache show docker.io >/dev/null 2>&1; then
            "${SUDO[@]}" apt-get install -y docker.io
        else
            printf 'Docker package is unavailable in the configured Ubuntu repositories; skipping.\n'
        fi
        ;;
    rocky)
        "${SUDO[@]}" dnf install -y python3.11 python3.11-pip git curl
        if dnf info docker >/dev/null 2>&1; then
            "${SUDO[@]}" dnf install -y docker
        else
            printf 'Docker package is unavailable in the configured Rocky repositories; skipping.\n'
        fi
        ;;
    *)
        printf 'Error: unsupported OS ID %s (supported: Ubuntu, Rocky Linux).\n' "${ID:-unknown}" >&2
        exit 1
        ;;
esac

python3.11 --version
python3.11 -m pip --version
git --version
curl --version | sed -n '1p'
if command -v docker >/dev/null 2>&1; then
    docker --version
fi
