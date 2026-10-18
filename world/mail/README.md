# Local SMTP Sink

Runs a local SMTP server on port `2525` and a read/clear REST API on port `3002`.
Messages are stored in SQLite and are never relayed, forwarded, or delivered externally.

## Run locally

```bash
pip install -e '.[world]'
MAIL_DB_PATH=world/data/mail.sqlite3 SMTP_HOST=127.0.0.1 SMTP_PORT=2525 \
  uvicorn world.mail.app:app --host 127.0.0.1 --port 3002
```

Container defaults bind SMTP port `2525` inside its network namespace.

## Endpoints

- `GET /health`
- `GET /emails?limit=100&offset=0`
- `GET /emails/{id}`
- `DELETE /emails` clears stored messages.

## Send a synthetic message

```bash
printf 'Subject: Sink test\n\nThis message stays local.\n' |
  curl --url 'smtp://127.0.0.1:2525' --mail-from sender@example.invalid \
    --mail-rcpt recipient@example.invalid --upload-file -
curl -fsS http://127.0.0.1:3002/emails
```

The SMTP daemon accepts mail only into this local sink; there is no outbound SMTP client.
