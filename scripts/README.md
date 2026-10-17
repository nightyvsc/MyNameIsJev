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

After SSH aliases are set up and VM5 is provisioned, `--upload` additionally sends the
backup to `vm5:backups/mynameisjev/` and compares local and remote SHA-256 digests:

```bash
python scripts/backup_sqlite.py --source /path/to/audit.db --upload
```

Backups contain audit data. Keep the local and remote directories access-controlled and
define a retention policy before production use. Restore by stopping the gateway,
copying the selected verified backup to a new database file, running
`sqlite3 restored.db 'PRAGMA integrity_check;'`, and only then configuring the gateway
to use that file. Never overwrite a live database as an unverified restore operation.
