# PrivaFuse

**Privacy-preserving collaborative healthcare intelligence.**

PrivaFuse is a working prototype of multimodal federated learning between hospitals. Four hospitals train
shared models on their own EHR, ECG and chest X-ray data; only model updates travel to a coordinator, which
averages them into a global model and sends it back. Aggregated surveillance, forecasting, explainability,
privacy checks and an audit trail sit on top, and a React dashboard shows the whole system.

> Federated learning reduces the need to centralise raw patient data. It does not, on its own, guarantee
> privacy. This is a research prototype, not a medical device, and nothing it shows is clinical evidence.

```
Hospital A ── local training ──┐
Hospital B ── local training ──┤                          FedAvg
Hospital C ── local training ──┼── model updates ──▶ coordinator ──▶ global model ──▶ back to hospitals
Hospital D ── local training ──┘    (weights, sample counts, summary metrics - never records)
```

## What is in the box

| Area | What it does |
| --- | --- |
| Federated learning | Round lifecycle (created → waiting → training → receiving updates → aggregating → evaluating → completed / failed), update validation, FedAvg weighted by sample count, federated evaluation, model versioning |
| Modalities | EHR → TabNet, ECG → CNN-BiLSTM, X-ray → EfficientNet-B3. Separate registries and aggregation; incompatible architectures are never averaged |
| Hospitals | Four nodes, each with its own data directory. Run in-process for a demo or as separate processes over HTTP |
| Surveillance | Regional weekly counts from hospital-reported totals with small-count suppression, choropleth map, hotspot *candidates* (z-score), never "outbreaks" |
| Forecasting | Naive, seasonal and autoregressive models compared by rolling-origin validation (MAE, RMSE), forecast with 80% / 95% intervals |
| Explainability | SHAP (Shapley) values for EHR, global and per prediction; occlusion sensitivity for ECG; Grad-CAM (PyTorch) or occlusion for X-ray |
| Privacy | Data stays on hospital nodes; optional clipping + Gaussian noise on updates (prototype DP with stated accounting); automated validation checks |
| Audit | Hash-chained log of every significant event, with chain verification |
| Auth | Supabase Auth with roles (admin, coordinator, viewer); built-in demo accounts when Supabase is not configured. Anyone can create an account, which is always a read-only viewer; the administrator is a separate account and is the only one who can change roles |

## Quick start (demo mode, no external services)

Requirements: Python 3.10+ and Node.js 20.19+ (or 22.12+).

```bash
# 1. Backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env                      # defaults are fine for the demo
python run.py                                             # http://localhost:8000  (API docs at /docs)

# 2. Frontend (second terminal)
cd frontend
npm install --legacy-peer-deps                            # plain npm install trips an npm 10 bug
cp .env.example .env
npm run dev                                               # http://localhost:5173
```

Sign in with `admin@fl-healthcare.demo` and the password `demo-password`, open **Federated Learning**, and
press **Start new round**. Run a few rounds per modality, then look at Models, Explainability and the rest.

Optional: `python scripts/seed_demo.py --rounds 3` (with the API stopped) runs three rounds per modality up
front so the dashboards have history when you first open them.

PyTorch is a large download. If you skip it (`pip install` everything in `backend/requirements.txt` except
`torch` and `torchvision`), the app still runs: small NumPy stand-in models take the place of TabNet,
CNN-BiLSTM and EfficientNet-B3, and every screen says so.

## Demo mode and real mode

`DEMO_MODE=true` (the default) simulates the hospitals, their records and the surveillance counts. Training,
aggregation, evaluation, forecasting and explanations are computed for real on that simulated data - no
metric is hard-coded - and everything derived from it is labelled **SIMULATED / DEMONSTRATION DATA**.

`DEMO_MODE=false` uses datasets you have prepared (`scripts/prepare_real_data.py`), Supabase Auth and
Supabase Postgres. The architecture and code paths are the same; only the data sources and the identity
provider change. See [docs/setup.md](docs/setup.md).

## Repository layout

```
frontend/      React + Vite + Tailwind dashboard (React Router, Recharts, React Leaflet, Axios)
backend/       FastAPI coordinator: routers, schemas, services, federated engine, database layer, tests
ml/            Models, dataset loaders, simulated data, local training and the hospital node
analytics/     Geospatial surveillance, hotspot detection, forecasting, explainability, privacy
data/          Hospital data lives here at runtime (never committed)
supabase/      PostgreSQL schema for Supabase
scripts/       Data preparation, external hospital node, demo seeding, node tokens
docs/          Architecture, API reference, setup guide, methodology
```

## Tests

```bash
pip install -r backend/requirements-dev.txt
pytest                      # backend, ml and analytics suites

cd frontend && npm test     # frontend suite (Vitest + Testing Library)
```

The PyTorch model tests are skipped automatically when PyTorch is not installed.

## Documentation

- [docs/setup.md](docs/setup.md) - installation, configuration, Supabase, real datasets, external nodes, deployment
- [docs/multi-machine.md](docs/multi-machine.md) - coordinator on one laptop, hospitals on others: network, firewall, demo script
- [docs/architecture.md](docs/architecture.md) - components, data boundaries, round lifecycle, database
- [docs/api.md](docs/api.md) - every endpoint
- [docs/permissions.md](docs/permissions.md) - roles (including health officers, researchers and hospital managers), what each may do, and the demo accounts
- [data/boundaries/README.md](data/boundaries/README.md) - the Karnataka district boundaries (geoBoundaries, ODbL 1.0) and how to load them
- [docs/methodology.md](docs/methodology.md) - models, FedAvg, evaluation, hotspot and forecast methods, explainability, privacy, and their limits
- [docs/verification.md](docs/verification.md) - what has been executed (including PyTorch training results), and what has not
