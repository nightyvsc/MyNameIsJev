# Streamlit Dashboard

The dashboard is hosted on VM2 and communicates only with the gateway HTTP API on VM1.
It never opens, mounts, or writes the gateway's SQLite file.

## Configuration

- `GATEWAY_BASE_URL`: reachable base URL for VM1, for example `http://<VM1-private-address>:8000`.
- `GATE_TOKEN`: the same internal token configured in the gateway.
- `DASHBOARD_APPROVER_ID`: optional default approver label.

Put deployment secrets in a local ignored `.env` or a restricted environment file on VM2.
Never commit real values.

## Run

```bash
pip install -e '.[dashboard]'
GATEWAY_BASE_URL='http://<VM1-private-address>:8000' \
GATE_TOKEN='<local-gate-token>' \
streamlit run dashboard/app.py --server.address 0.0.0.0 --server.port 3000
```

Replace the quoted address placeholder with VM1's private address before running.

The app polls `/audit/log` every 2 seconds and `/audit/metrics` every 10 seconds. It uses
`GET /queue` for pending decisions and posts approvals to
`POST /gate/{decision_id}/approve`. Gateway/API failures are shown in the UI; the
dashboard does not substitute mock data.

Streamlit starts on port 3000. Restrict access to the development LAN/VPN; configure a
TLS reverse proxy before exposing it outside that network.
