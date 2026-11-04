# Setup

## Requirements

- Python 3.10 or newer
- Node.js 20.19+ or 22.12+ (required by Vite 8)
- About 3 GB of disk for PyTorch (optional - see below)

## 1. Backend

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
python run.py
```

The API listens on `http://localhost:8000`; `/docs` has interactive documentation. On first start in demo
mode it creates a SQLite database in `backend/var/`, generates the simulated hospital data in
`data/hospitals/`, initialises version 0 of each model in `ml/checkpoints/` and loads simulated
surveillance data.

**CPU-only PyTorch** is enough and much smaller:
`pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu`, then install the rest of
`backend/requirements.txt`.

**Without PyTorch** the server still runs. Leave `ML_BACKEND=auto` and the NumPy stand-in models are used
and labelled on every screen. Set `ML_BACKEND=pytorch` if you would rather the server refuse to train than
fall back.

Optional packages (`backend/requirements-optional.txt`): `shapely` and `geopandas` for real region
boundaries, `statsmodels` for an extra ARIMA candidate, `shap` for the library's KernelExplainer.

## 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev          # http://localhost:5173
```

`VITE_API_BASE_URL` must point at the API. If you serve the frontend from another origin, add it to
`CORS_ORIGINS` in `backend/.env`.

## 3. Sign in (demo)

With Supabase not configured, three demo accounts are available. The password is `DEMO_PASSWORD` from
`backend/.env` (default `demo-password`).

| Email | Role |
| --- | --- |
| `admin@fl-healthcare.demo` | Administrator |
| `coordinator@fl-healthcare.demo` | FL coordinator |
| `viewer@fl-healthcare.demo` | Viewer (read-only; cannot start rounds or read the audit log) |

### Creating accounts

**Create an account** on the sign-in page makes a new account with your own email and password. Every new
account is a viewer. Nobody can sign up as an administrator or coordinator: the administrator is a separate
account (`admin@fl-healthcare.demo` here, or the `ADMIN_EMAILS` addresses with Supabase), and it grants other
roles under **Settings → Users and roles**. An administrator cannot change their own role, and the built-in
demo accounts keep theirs. Sign-ups and role changes are written to the audit log.

Passwords of accounts created this way are stored as salted scrypt hashes in the `local_credentials` table.
Set `ALLOW_SIGNUP=false` in `backend/.env` to remove the option.

## 4. First-run checklist

1. **Federated Learning → Start new round** for EHR. The pipeline diagram should progress to *Completed*
   and show a new model version with metrics.
2. Run two or three more rounds, then one each for ECG and X-ray. With PyTorch, an X-ray round on CPU takes
   the longest (EfficientNet-B3 has about 11 million parameters); set `XRAY_PRETRAINED=true` for faster
   learning.
3. **Models** - metrics by version. **Explainability** - explanations for the trained models.
4. **Disease Surveillance**, **Forecasting** - available immediately in demo mode.
5. **Audit Logs → Verify chain**, **Settings** - privacy checks.
6. Run the tests: `pip install -r backend/requirements-dev.txt && pytest`, and `cd frontend && npm test`.

With the NumPy stand-ins a round finishes in under a second. Set `DEMO_STEP_DELAY_SECONDS=1` to pause
before each hospital's update so the round can be watched; the pause is cosmetic and is included in the
round's displayed duration.

## Supabase

1. Create a project at supabase.com.
2. SQL editor → run `supabase/schema.sql` (creates the tables and enables row level security).
3. Authentication → Users → add your users (or enable sign-up).
4. `backend/.env`:

   ```env
   SUPABASE_URL=https://<project>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<service role key>        # Project Settings → API. Server only.
   DATABASE_URL=postgresql://postgres.<project>:<password>@<host>:5432/postgres
   ADMIN_EMAILS=you@example.org
   ```

5. `frontend/.env`:

   ```env
   VITE_SUPABASE_URL=https://<project>.supabase.co
   VITE_SUPABASE_ANON_KEY=<anon key>
   ```

As soon as `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are set, the API uses Supabase Auth and the demo
accounts are switched off. You can use Supabase for auth and the database while keeping `DEMO_MODE=true`
(simulated data). The sign-in page's **Create an account** then signs up through Supabase Auth (if your project
requires email confirmation, the user confirms first). New users get the `viewer` role; emails in
`ADMIN_EMAILS` become `admin` and cannot be demoted from the dashboard. An administrator changes anyone
else's role under **Settings → Users and roles**.

Never put the service-role key or the database URL in the frontend. Only `VITE_`-prefixed values reach the
browser, and those must be the project URL and the anon key.

## Real mode

```env
DEMO_MODE=false
```

Requires Supabase Auth and `DATABASE_URL`, and hospital data prepared with
`scripts/prepare_real_data.py` (see [data/README.md](../data/README.md)). Nothing is simulated to fill
gaps: a modality with no prepared data cannot be trained, and surveillance pages report that they are not
configured until `REGIONS_GEOJSON_PATH` and `SURVEILLANCE_REPORTS_CSV` are set.

For real chest images use `--size 224` (or larger) when preparing and `XRAY_PRETRAINED=true`. The loaders
hold a hospital's split in memory; very large image sets need a streaming loader, which this prototype does
not include.

## Real region boundaries

Simulated regions are the default. To draw real districts instead, point `REGIONS_GEOJSON_PATH` at a
GeoJSON FeatureCollection. The repository includes one public file: Karnataka's 30 districts from
geoBoundaries (ODbL 1.0; source and credit in [data/boundaries/README.md](../data/boundaries/README.md)).

```bash
# backend/.env
REGIONS_GEOJSON_PATH=data/boundaries/karnataka_districts.geojson
REGION_ID_FIELD=region_id
REGION_NAME_FIELD=name
```

Restart the API.
- **Map:** the surveillance map shows only these districts. It cannot be panned away or zoomed out past
  them, and it shows the file's credit line underneath. Base-map tiles appear only if `VITE_MAP_TILE_URL` is
  set in `frontend/.env`.
- **Case reports:** in demo mode the weekly reports are still simulated (for these districts) and labelled
  SIMULATED.
- **Population:** the file has no population field, so the map shows counts rather than rates.
- **Health officers:** give them jurisdictions with the file's region ids (for example `KA-MYSORE`) under
  Settings → Users. The built-in demo officers cover the simulated regions only.

`backend/tests/test_real_boundaries.py` loads this file through the API.

## External hospital nodes

To run each hospital as its own process (on this machine or others):

```bash
# backend/.env
HOSPITAL_NODES=external
NODE_TOKEN_SECRET=<long random string>

python run.py
python scripts/node_token.py                      # prints one token per hospital

# one terminal (or machine) per hospital: generates that hospital's simulated data, then starts its node
python scripts/setup_hospital.py hospital_a --server http://localhost:8000 --token <token>
```

Each node needs the repository and the Python dependencies; it keeps its own `data/hospitals/<hospital_id>/`
directory, and the coordinator machine needs no hospital data. At start-up a node checks that it would train
the same model as the coordinator and refuses to start otherwise. It then sends a heartbeat every 10 s
(the Hospitals page shows it as connected), polls for rounds, trains, uploads and evaluates. Hospitals that
miss a round's deadline are dropped. For laptops on a network, see [multi-machine.md](multi-machine.md).
Use HTTPS between machines.

## Configuration reference

All backend settings are documented in `backend/.env.example`; frontend settings in
`frontend/.env.example`.

## Deployment

- **API**: any host that runs Python. `Procfile` starts it with `API_HOST=0.0.0.0`; the platform's `PORT`
  is honoured. Set the variables from `backend/.env.example` in the host's environment, including a fixed
  `NODE_TOKEN_SECRET` and `DATABASE_URL`. Run a single process: round state transitions are serialised
  with in-process locks, so multiple workers are not supported.
- **Frontend**: `npm run build` produces static files in `frontend/dist`. Serve them from any static host
  with a fallback to `index.html` for client-side routes, and set `VITE_API_BASE_URL` at build time.
- Serve both over HTTPS and set `CORS_ORIGINS` to the frontend's origin.
- Model weights are written to `MODEL_STORAGE_PATH`; use a persistent disk.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| Sign-in page says sign-in is not configured | The API uses Supabase but `frontend/.env` has no `VITE_SUPABASE_*` values |
| "Server unavailable" on every page | The API is not running, or `VITE_API_BASE_URL` / `CORS_ORIGINS` do not match |
| Models show "NumPy reference MLP" | PyTorch is not installed in the API's environment (or `ML_BACKEND=numpy-reference`) |
| A round fails with "Only N valid update(s)" | Hospitals failed or sent invalid updates; each hospital's error is shown in its lane on the round |
| Version numbers jump and metrics restart | The model backend changed (e.g. PyTorch installed later); the registry started a fresh lineage |
| Demo sessions end when the server restarts | `DEMO_JWT_SECRET` is empty, so a new signing key is generated at each start |
