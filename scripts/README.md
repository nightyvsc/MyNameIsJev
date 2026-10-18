# Operational Scripts

## Real TypeSafe API probe

The real API probe sends one deliberately synthetic request to the official TypeSafe
endpoint. The API key belongs only in the ignored repository-root `.env` file:

```dotenv
TYPESAFE_API_KEY=replace-with-your-local-key
JEV_MODEL=jev-latest
```

Do not commit `.env`, send the key in chat, or put it in a shell command argument. Run
from the repository root after checking the provider's current pricing:

```bash
python scripts/test_jev_api.py --confirm
```

`--confirm` is mandatory. The probe sends no retry, follows no redirects, accepts only
`https://api.typesafe.ai/v1/systemone`, and includes only fictional data. A successful
response prints the model, answer values, latency, and token counts when supplied. The
key is never printed. Without credentials, validate the interface without network access:

```bash
python scripts/test_jev_api.py --help
python -m pytest tests/unit/test_jev_api_probe.py
```

## SQLite backups

Create a consistent local backup and run SQLite's integrity check:

```bash
python scripts/backup_sqlite.py --source /path/to/audit.db
```

The gateway's Docker volume is not readable by the VM1 SSH user. Create the Online
Backup snapshot from inside the gateway container, copy that snapshot to a private
temporary path on VM1, then use the uploader with VM5's dedicated SFTP-only identity.
VM5's host key must have been verified independently and pinned in
`~/.ssh/jev_vm5_known_hosts`:

```bash
docker cp /opt/mynameisjev/scripts/backup_sqlite.py \
  infra-gateway-1:/tmp/backup_sqlite.py
SNAPSHOT_PATH="$(docker exec -u 0 infra-gateway-1 \
  python /tmp/backup_sqlite.py \
    --source /var/lib/jev-gate/audit.sqlite3 \
    --output-directory /tmp/jev-backup \
  | sed -n 's/^Created and integrity-checked backup: //p')"
docker cp "infra-gateway-1:${SNAPSHOT_PATH}" /tmp/jev-audit-source.sqlite3
chmod 600 /tmp/jev-audit-source.sqlite3
python3 /opt/mynameisjev/scripts/backup_sqlite.py \
  --source /tmp/jev-audit-source.sqlite3 \
  --output-directory /tmp/jev-vm5-upload \
  --upload \
  --identity-file "$HOME/.ssh/jev_vm5_backup" \
  --known-hosts "$HOME/.ssh/jev_vm5_known_hosts"
```

The script checks the local SQLite copy, uploads over SFTP, downloads it to a temporary
file, compares SHA-256, and restore-checks the downloaded copy to a separate temporary
database. The verified archive remains in `/backups` on VM5; remove the temporary
`/tmp/jev-audit-source.sqlite3` and contents of `/tmp/jev-backup` and
`/tmp/jev-vm5-upload` after verification. Backups contain audit payloads; define
retention and encryption-at-rest before scheduling automatic copies.

## VM6 baseline runner

`bash infra/deploy_support.sh loadtest` deploys the standard-library-only runner to VM6;
it does not send requests or transfer secrets. The runner is installed under
`~/.local/share/mynameisjev/scripts/`. Provision `~/.config/mynameisjev/.env` on VM6
with mode `0600`, containing only `GATE_TOKEN` and
`LOAD_TEST_TARGET=http://10.43.99.216:8000`.
The token is the gateway client token, not the TypeSafe API key. After an estimated spend
limit is explicitly approved, run up to 10 synthetic dry-run actions. Concurrency
defaults to 1; the upper bound is 5:

```bash
python3 ~/.local/share/mynameisjev/scripts/loadtest_gateway.py \
  --requests 10 \
  --concurrency 1 \
  --max-estimated-cost-usd <approved-limit>
```

The runner is restricted to VM1, at most 10 actions, concurrency 1–5, a 15-second
request timeout by default, and stops before starting another batch after a failed or
non-allow response. It requires a maximum estimated cost and reserves `$0.0005` for
every requested action before sending the first batch; after each batch it rechecks the
reserve for remaining actions. A 10-request run therefore requires a cap of at least
`$0.0050`. The spend limit is not an absolute provider billing guarantee: retries or
timeouts can incur charges not represented in the returned successful decision. This
is a bounded baseline tool, not an unbounded load generator. If a request fails, other
requests already dispatched in that same concurrent batch may still complete and incur
cost; the runner will not start the next batch.
