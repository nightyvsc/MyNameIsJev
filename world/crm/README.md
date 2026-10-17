# Mock CRM

FastAPI service with 1,000 deterministic fictional contacts and SQLite-backed writes.
No CRM vendor or external service is contacted.

## Run locally

```bash
pip install -e '.[world]'
uvicorn world.crm.app:app --host 127.0.0.1 --port 3001
```

Set `CRM_DB_PATH` to choose the local SQLite file. The default for a container is
`/data/crm.sqlite3`.

## Endpoints

- `GET /health`
- `GET /contacts?limit=100&offset=0` returns `{total, items}`.
- `GET /contacts/{id}`
- `POST /contacts/bulk-upsert` accepts a JSON array; at most 1,000 records per request.

## Verify

```bash
curl -fsS http://127.0.0.1:3001/contacts | jq '.total'
curl -fsS -X POST http://127.0.0.1:3001/contacts/bulk-upsert \
  -H 'Content-Type: application/json' \
  -d '[{"name":"Demo User","email":"demo@example.invalid"}]'
```
