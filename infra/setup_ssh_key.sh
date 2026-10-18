#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SSH_CONFIG="$SCRIPT_DIR/ssh_config"
KEY_FILE="$HOME/.ssh/mynameisjev_vm_ed25519"
PUBLIC_KEY="$KEY_FILE.pub"
HOSTS=(vm1 vm2 vm3 vm4 vm5 vm6)

if ! command -v ssh-keygen >/dev/null 2>&1 || ! command -v ssh-copy-id >/dev/null 2>&1; then
    printf 'Error: ssh-keygen and ssh-copy-id are required.\n' >&2
    exit 1
fi

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

if [[ ! -f "$KEY_FILE" ]]; then
    ssh-keygen -q -t ed25519 -N '' -C 'mynameisjev-vm-access' -f "$KEY_FILE"
fi
if [[ ! -f "$PUBLIC_KEY" ]]; then
    printf 'Error: public key not found at %s.\n' "$PUBLIC_KEY" >&2
    exit 1
fi
chmod 600 "$KEY_FILE"

for host in "${HOSTS[@]}"; do
    printf 'Installing the public key on %s (enter the VM password when prompted).\n' "$host"
    ssh-copy-id -F "$SSH_CONFIG" -i "$PUBLIC_KEY" "$host"
done

printf 'Key-based SSH setup complete. Test with: ssh -F %s vm1\n' "$SSH_CONFIG"
