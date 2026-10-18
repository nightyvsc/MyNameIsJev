# Mock Social API

SQLite-backed API for fictional social posts. It never contacts a social network.

## Run locally

```bash
pip install -e '.[world]'
SOCIAL_DB_PATH=world/data/social.sqlite3 \
  uvicorn world.social.app:app --host 127.0.0.1 --port 3003
```

## Endpoints

- `GET /health`
- `POST /posts` with `{ "content": "...", "platform": "twitter|linkedin|instagram" }`
- `GET /posts?limit=100&offset=0`
- `DELETE /posts/{id}`

New posts receive a fictional `https://fakesocial.local/post/{id}` URL; this host is not
contacted.
