# VM Infrastructure

The current topology uses the six supplied VMs. They share the SSH user `estudiante`.
The local private key is stored outside this repository at
`~/.ssh/mynameisjev_vm_ed25519`; VM passwords are never saved in project files.

## Inventory

| Alias | Private IP | OS | Role |
|---|---|---|---|
| `vm1` | `10.43.99.216` | Ubuntu | Gateway, policy engine, local SQLite |
| `vm2` | `10.43.100.175` | Ubuntu | Streamlit dashboard |
| `vm3` | `10.43.99.199` | Ubuntu | Simulated world and GitHub relay |
| `vm4` | `10.43.99.206` | Ubuntu | Synthetic agents |
| `vm5` | `10.43.97.73` | Rocky Linux | SQLite backup storage |
| `vm6` | `10.43.97.69` | Rocky Linux | Load tests, CI, optional monitoring |

The IPs also appear in the ignored local `inventory.yaml`, `ssh_config`, and root `.env`;
do not commit those files. The root `.env` is an operator-side worksheet with empty
secret fields. Do not copy it wholesale to any VM. `inventory.yaml` is the local
Ansible inventory.

## Passwordless SSH setup

From the repository root, run:

```bash
bash infra/setup_ssh_key.sh
```

The script creates an Ed25519 key without a passphrase in the local user's `~/.ssh/`
directory, then runs `ssh-copy-id` for each VM. Enter each VM's existing password only
once when prompted. The passwords are not written to disk by this project. Do not copy
the private key to any VM.

Use the aliases with the supplied config file:

```bash
ssh -F infra/ssh_config vm1 'hostname'
ssh -F infra/ssh_config vm6 'hostname'
```

To check all six hosts after key setup:

```bash
for host in vm1 vm2 vm3 vm4 vm5 vm6; do
  ssh -F infra/ssh_config "$host" 'printf "%s OK\n" "$(hostname)"' || exit 1
done
```

## Base packages

Run the setup script on each VM with an account that can use `sudo`:

```bash
bash infra/setup_base.sh
```

It installs Python 3.11, pip, Git, and curl using the OS package manager. It installs
Docker only when the package is available in the currently configured OS repositories;
it does not add third-party repositories or alter firewall/network configuration.

## Connectivity

From the local machine, confirm SSH access to all six hosts using the loop above. To
verify VM-to-VM network reachability without copying the local private key to a VM:

```bash
ssh -F infra/ssh_config vm1 'ping -c 1 10.43.99.199'
```

For a read-only summary of OS, hostname, Python, and Docker availability on all six
machines:

```bash
bash infra/check_hosts.sh
```

## Support-service deployment

The deployment helper supports Persona A's gateway and Persona B's dashboard, simulated
world services, and agent images. It was run on 2026-10-17 for VM1–VM4: gateway,
dashboard, and world services are healthy, and VM4's bounded agent dry-run completed.
Before a fresh deployment, provision each service's own `.env` on the destination host
with mode `600`, ensure the SSH deployment account owns the file and can write the
project directory, and verify SSH aliases:

```bash
bash infra/deploy_support.sh gateway   # VM1
bash infra/deploy_support.sh dashboard  # VM2
bash infra/deploy_support.sh world      # VM3
bash infra/deploy_support.sh agents     # VM4; builds images only
bash infra/deploy_support.sh loadtest   # VM6; deploys the bounded runner only
```

For VM1, set a unique `GATE_TOKEN`, `TYPESAFE_API_KEY`, `JEV_BASE_URL`, `JEV_MODEL`, and
private `VM1_BIND_IP` in that host's `.env`. The TypeSafe key is used only for the
gateway's outbound HTTPS calls and must never be placed on another VM. Keep action data
synthetic until payload minimization and PII handling are agreed. The gateway binds to
loopback unless the private bind address is explicitly configured. Its SQLite database
is persisted in the Compose-managed `gateway_data` volume. The deployment helper checks
that the destination `.env` is mode `400` or `600`; it never copies environment files or
secrets.

The helper excludes environment files, database files, local data, and credentials from
transfer. Agent containers are not started by the helper; they submit requests to the
gateway and may incur provider usage when manually run. Their bounded `--dry-run`
completed against real TypeSafe with synthetic actions; no side effects were executed.
Keep `GITHUB_ENABLE_WRITES=false`. VM5 is a backup-only host with an SFTP-restricted
`jevbackup` account; backups are created on VM1 and integrity-verified via SFTP download.
VM6 receives only a bounded baseline runner; provide it a separate mode-600 `.env` with
the gateway client token after agreeing an estimated spend limit. Never copy the
TypeSafe API key to VM6.

The deployed stack is a test/demo environment, not a production integration. The
GitHub relay now creates an Action matching contract v2.0, but webhook delivery from
GitHub.com and the complete PR-to-dashboard flow have not been verified. A dashboard
demo can use synthetic examples and does not need GitHub ingress. A publicly viewable
demo needs an approved HTTPS endpoint/hosting layer and access controls; it does not
require publishing the private gateway or GitHub relay.

See the full IP-to-role mapping, flow diagram, port policy, per-VM configuration,
deployment phases, and readiness criteria in
[`DEPLOYMENT_PLAN.md`](DEPLOYMENT_PLAN.md).
