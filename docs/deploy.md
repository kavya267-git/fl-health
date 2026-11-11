# Deploying MediFed (coordinator on a laptop + Tailscale Funnel + Vercel)

- **API:** the coordinator runs on one laptop (`python run.py`, port 8000, SQLite in `backend/var/`).
- **Public address:** Tailscale Funnel publishes port 8000 over HTTPS at `https://<machine>.<tailnet>.ts.net`.
  Only port 8000 is published; the dashboard's development server (5173) is not.
- **Web app:** Vercel, from `frontend/`.
- **Hospital agent:** a GitHub Release asset, built by `.github/workflows/agent-release.yml`.

Settings live in `backend/.env` (git-ignored) and in Vercel's settings page. This page lists **names only**.
The web app receives only non-secret `VITE_` settings.

## 1. Tailscale Funnel

Install Tailscale on the laptop and sign in. In a terminal:

```powershell
tailscale funnel --bg 8000
```

The first time, it prints a link to the admin console: approve HTTPS certificates and the Funnel permission,
then run the command again. `tailscale funnel status` shows the address. It stays the same across restarts.

## 2. API (`backend/.env`)

| Name | Value |
| --- | --- |
| `DEMO_MODE` | `true` |
| `HOSPITAL_NODES` | `external` |
| `ML_BACKEND` | `pytorch` |
| `ALLOW_SIGNUP` | `false` (no self-service viewer accounts; hospital registration stays open) |
| `DEMO_PASSWORD` | a new strong password (not `demo-password`) for the built-in accounts |
| `DEMO_JWT_SECRET` | 64 random hex characters; keep it fixed so sessions survive a restart |
| `NODE_TOKEN_SECRET` | 64 random hex characters; hospitals A-D's node tokens are derived from it, so keep it fixed |
| `SIMULATION_END_WEEK` | `2026-11-02` |
| `CORS_ORIGINS` | the Vercel address, plus `http://localhost:5173,http://127.0.0.1:5173` |
| `API_BASE_URL`, `PUBLIC_API_URL` | the Funnel address (shown to hospitals on "Connect your hospital") |
| `TRUST_PROXY_HEADERS` | `true` (Funnel is a proxy; registrations and sign-ins are rate-limited per client address) |
| `API_HOST` | `127.0.0.1` (Funnel reaches it locally; the laptop's port is not opened to the network) |
| `PORT` | `8000` |

Before the first demo, compute the ensemble forecasts once (stored in the database; a restart reuses them):

```powershell
python scripts/precompute_forecasts.py
python run.py
```

## 3. Web app (Vercel)

**Settings → Build and Deployment:** Root Directory `frontend`, Framework Vite, Build Command `npm run build`,
Output Directory `dist`. **Settings → Environments → Production:** the branch to publish. **Settings →
Environment Variables** (Production), then **Redeploy** (Vite reads them at build time):

| Name | Value |
| --- | --- |
| `VITE_API_BASE_URL` | the Funnel address |
| `VITE_AGENT_DOWNLOAD_URL` | optional; defaults to the `agent-v1.0.0` release's `MediFed-Hospital-Agent-Windows.zip` |

Share the production address (`https://<project>.vercel.app`). Preview deployments sit behind Vercel's sign-in
by default. `frontend/vercel.json` sends every client route (`/register`, `/situation`, ...) to the app, so a
refresh works. The sign-in page names the demo password only while the server uses the default
`demo-password`.

## 4. Hospital agent (GitHub Release)

`hospital_agent/medifed_agent/defaults.py` holds the address pre-filled in the agent's window (the operator can
change it). Set it to the Funnel address, commit, then push a tag:

```powershell
git tag agent-v1.0.0
git push origin agent-v1.0.0
```

The workflow builds on `windows-latest` and attaches `MediFed-Hospital-Agent-Windows.zip` to the release. A
repository variable `MEDIFED_API_URL`, if set, overrides `defaults.py` for that build. HTTPS certificates are
verified by the agent and by `setup_hospital.py`; verification is never disabled.

## 5. Hospitals A-D through the public address

With the same `NODE_TOKEN_SECRET` as before, A-D's tokens do not change (`python scripts/node_token.py`):

```powershell
python scripts/setup_hospital.py hospital_a --server https://<machine>.<tailnet>.ts.net --token <token for hospital_a>
```

and likewise for B-D.

## 6. Back to the plain local demo

1. `tailscale funnel reset` (or `tailscale funnel --https=443 off`): the public address stops answering.
2. Stop this coordinator and start the usual one (the main folder's `python run.py`).
3. Point each node back at the local address once (each node remembers its server in `data/nodes/<hospital>.json`):

   ```powershell
   python scripts/setup_hospital.py hospital_a --server http://<server-laptop-ip>:8000 --token <token for hospital_a>
   ```

4. In Vercel, set the production branch back to `main` (or leave the public site pointing at a stopped API).

## 7. Alternative: Hugging Face Space + Neon

`deploy/hf-space/Dockerfile` and `scripts/deploy_space.py` deploy the API to a Docker Space with Neon
PostgreSQL. Set the variables above as Space secrets and variables, plus `DATABASE_URL` (Neon pooled
connection string with `sslmode=require`); the image sets `MODEL_WEIGHTS_IN_DATABASE=true`, `PORT=7860` and
`TRUST_PROXY_HEADERS=true`.

## 8. Running the tests against PostgreSQL

```powershell
$env:TEST_DATABASE_URL = "postgresql://user:password@localhost:5432/medifed_test"   # a throwaway database
python -m pytest
```

Every test empties that database's `public` schema first, so never point it at a database you need.
