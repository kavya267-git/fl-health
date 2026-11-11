# Deploying MediFed (Hugging Face Space + Neon + Vercel)

- **API:** a Hugging Face Space (Docker SDK, CPU basic), built from `deploy/hf-space/Dockerfile`.
- **Database:** Neon PostgreSQL (pooled connection, TLS).
- **Web app:** Vercel, from `frontend/`.
- **Hospital agent:** a GitHub Release asset, built by `.github/workflows/agent-release.yml`.

Every setting comes from the hosts' own settings pages. This page lists **names only**. No value is committed;
the web app receives only non-secret `VITE_` settings.

## 1. Database (Neon)

Create a project. In the Neon console, **Connection Details**, choose **Pooled connection** and copy the
connection string. It ends in `?sslmode=require` (keep that; add it if missing). That string is
`DATABASE_URL`. A Neon database scales to zero when idle: the API retries its first connection with
back-off and reconnects once when an idle pooled connection has been closed.

## 2. API (Hugging Face Space)

Create a Space: SDK **Docker**, hardware **CPU basic**. Then, in a terminal with a Hugging Face token that has
write access:

```powershell
pip install huggingface_hub
$env:HF_TOKEN = "<your Hugging Face write token>"     # from huggingface.co/settings/tokens; not stored anywhere
python scripts/deploy_space.py <hf-username>/<space-name>
```

The Space's address is `https://<hf-username>-<space-name>.hf.space` (lower case). In the Space, open
**Settings → Variables and secrets** and add:

| Name | Kind | Value / where to find it |
| --- | --- | --- |
| `DATABASE_URL` | secret | Neon pooled connection string (step 1) |
| `DEMO_PASSWORD` | secret | a new strong password (not `demo-password`); used by the built-in demo accounts |
| `DEMO_JWT_SECRET` | secret | 64 random hex characters; signs sign-in sessions |
| `NODE_TOKEN_SECRET` | secret | 64 random hex characters; hospitals A-D's node tokens are derived from it |
| `DEMO_MODE` | variable | `true` |
| `SIMULATION_END_WEEK` | variable | `2026-11-02` |
| `HOSPITAL_NODES` | variable | `external` |
| `ML_BACKEND` | variable | `pytorch` |
| `CORS_ORIGINS` | variable | the Vercel address, e.g. `https://<project>.vercel.app` |
| `API_BASE_URL` | variable | the Space address |
| `PUBLIC_API_URL` | variable | the Space address (shown to hospitals on "Connect your hospital") |
| `MODEL_KEEP_VERSIONS` | variable | `2` (weights are kept in the database; this bounds its size) |
| `ALLOW_SIGNUP` | variable | `false` (no self-service viewer accounts on the public site; hospital registration stays open) |

Set in the image and not needed here: `API_HOST=0.0.0.0`, `PORT=7860`, `MODEL_WEIGHTS_IN_DATABASE=true`
(a free Space has no persistent disk, so the global model weights live in the database), and
`TRUST_PROXY_HEADERS=true` (the Space sits behind a proxy; registrations are rate-limited by the client's
address).

**Forecasts.** The ensemble forecast is computed once and stored in the database, so a restarted Space reuses it.
Run it once from a laptop against the same database, with the same settings, before the first demo:

```powershell
$env:DATABASE_URL = "<Neon pooled connection string>"; $env:DEMO_MODE = "true"; $env:SIMULATION_END_WEEK = "2026-11-02"; $env:HOSPITAL_NODES = "external"
python scripts/precompute_forecasts.py
```

## 3. Web app (Vercel)

Import the GitHub repository, set **Root Directory** to `frontend`, branch as needed. `frontend/vercel.json`
sends every client route (`/register`, `/my-hospital`, ...) to the app. **Settings → Environment Variables:**

| Name | Value |
| --- | --- |
| `VITE_API_BASE_URL` | the Space address |
| `VITE_AGENT_DOWNLOAD_URL` | optional; defaults to the latest GitHub Release's `MediFed-Hospital-Agent-Windows.zip` |

The sign-in page names the demo password only while the server uses the default `demo-password`; with a new
`DEMO_PASSWORD` it says to ask the administrator.

## 4. Hospital agent (GitHub Release)

`hospital_agent/medifed_agent/defaults.py` holds the address pre-filled in the agent's window. Set it to the
Space address, commit, then push a tag:

```powershell
git tag agent-v1.0.0
git push origin agent-v1.0.0
```

The workflow builds on `windows-latest` and attaches `MediFed-Hospital-Agent-Windows.zip` to the release. The
"Connect your hospital" page links to `releases/latest/download/MediFed-Hospital-Agent-Windows.zip`. HTTPS
certificates are verified by the agent and by `setup_hospital.py`; verification is never disabled.

## 5. Our hospitals A-D against the cloud coordinator

On the hospital laptop, with the tokens derived from the Space's `NODE_TOKEN_SECRET`
(`python scripts/node_token.py` with that secret set, or the list prepared with the secrets):

```powershell
python scripts/setup_hospital.py hospital_a --server https://<hf-username>-<space-name>.hf.space --token <token for hospital_a>
```

and likewise for B-D. **Back to the local coordinator:** each node remembers its server in
`data/nodes/<hospital>.json`, so pass the local address and token once:

```powershell
python scripts/setup_hospital.py hospital_a --server http://<server-laptop-ip>:8000 --token <local token for hospital_a>
```

## 6. Running the tests against PostgreSQL

```powershell
$env:TEST_DATABASE_URL = "postgresql://user:password@localhost:5432/medifed_test"   # a throwaway database
python -m pytest
```

Every test empties that database's `public` schema first, so never point it at a database you need.
