# Streamlit Dashboard

The dashboard is hosted on VM2 and communicates only with the gateway HTTP API on VM1.
It never opens, mounts, or writes the gateway's SQLite file.

## Public read-only demo

The public demo is a separate entrypoint: `dashboard/demo_app.py`. It displays a
fixed integration-test snapshot and hand-authored example scenarios. It does not
import the operational dashboard, read environment secrets, call Jev, contact the
gateway, or execute external actions. Its example decisions are illustrative; only
the explicitly labeled integration-test snapshot describes observed test results.

Run it locally without gateway configuration:

```bash
python -m pip install -r requirements.txt
streamlit run dashboard/demo_app.py
```

### Deploy on Streamlit Community Cloud

The repository is public, so Streamlit Community Cloud is the simplest free option
for a shareable demo URL. It does not expose the private VMs and requires no public IP
for them. Free-tier availability and limits may change.

1. Sign in at [share.streamlit.io](https://share.streamlit.io/) with a GitHub account
   that has admin access to this repository.
2. Create an app from `nightyvsc/MyNameIsJev`, branch `main`, entrypoint
   `dashboard/demo_app.py`.
3. Select Python 3.11 or a newer supported version if prompted.
4. Do not add Streamlit secrets, gateway URLs/tokens, TypeSafe keys, or other
   credentials. Deploy and use the generated `*.streamlit.app` URL.
5. Open the app settings and verify it is public before sharing the URL.

Community Cloud reads the root `requirements.txt`. The `dashboard/app.py` entrypoint
below is the private operational console and must not be selected for an anonymous
public deployment.

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

The app polls `GET /decisions` and `GET /approvals?status=pending` every 2 seconds,
and reads metrics from `GET /metrics` every 10 seconds. All requests send
`X-Gate-Token`. Approvals use `POST /gate/{action_id}/approve` with
`{"resolution":"approved|rejected","resolved_by":"..."}`. Gateway/API failures are
shown in the UI; the dashboard does not substitute mock data.

Streamlit starts on port 3000. Restrict access to the development LAN/VPN; configure a
TLS reverse proxy before exposing it outside that network.
