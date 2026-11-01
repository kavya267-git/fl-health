# Architecture

## Components

```
┌──────────────────────── Browser ────────────────────────┐
│ React dashboard (frontend/)                              │
│ Supabase Auth client (or demo sign-in) ─ access token ─┐ │
└────────────────────────────────────────────────────────┼─┘
                                                REST + Bearer token
┌──────────────────── Coordinator (backend/) ────────────▼─┐
│ FastAPI routers ─▶ services                               │
│   auth · hospitals · federated coordinator · registry     │
│   surveillance · forecast · explainability · privacy      │
│   audit (hash chain)                                      │
│ Storage: database (metadata, metrics, aggregates, audit)  │
│          ml/checkpoints (global model weights)            │
└───────▲──────────────────────────────────────────▲───────┘
        │ weights · sample counts · summary metrics │
        │ (in-process call or HTTP + X-Hospital-Token)
┌───────┴───────┐ ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
│ Hospital A    │ │ Hospital B    │ │ Hospital C    │ │ Hospital D    │
│ HospitalNode  │ │ HospitalNode  │ │ HospitalNode  │ │ HospitalNode  │
│ ehr/ecg/xray  │ │ ehr/ecg/xray  │ │ ehr/ecg/xray  │ │ ehr/ecg/xray  │
│ local data    │ │ local data    │ │ local data    │ │ local data    │
└───────────────┘ └───────────────┘ └───────────────┘ └───────────────┘
```

| Package | Responsibility | Knows about patient-level data? |
| --- | --- | --- |
| `frontend/` | Dashboard. Talks only to the API. | No |
| `backend/app` | Coordinator: orchestration, aggregation, registry, analytics APIs, audit | No |
| `ml/` | Models, dataset loaders, local training, the hospital node | Yes - runs at the hospital |
| `analytics/` | Hotspot detection, forecasting, explainability, privacy mechanisms | Only where called from the hospital node |

## The data boundary

The boundary is the `CoordinatorTransport` interface in `ml/training/hospital_node.py`. A hospital node can
call exactly five things on the coordinator, and these are the only payloads that cross:

| Call | Sent by the hospital |
| --- | --- |
| `join_round` | Record **counts** per modality and the data source name |
| `fetch_global_model` | Nothing (downloads weights) |
| `submit_update` | Model weights (`.npz`), number of training samples, per-epoch loss/accuracy, local validation metrics, DP report |
| `submit_evaluation` | Confusion-matrix counts and summed loss; for EHR, mean absolute SHAP per feature |
| `report_failure` | A stage name and an error message |

Two transports implement the interface:

- `LocalTransport` (`backend/app/federated/in_process_nodes.py`) - direct calls, used when
  `HOSPITAL_NODES=in-process`. The four nodes run as threads in the API process, each with its own data
  directory.
- `HttpTransport` (`ml/training/http_transport.py`) - the REST endpoints, used by
  `scripts/run_hospital_node.py` when `HOSPITAL_NODES=external`. Nodes authenticate with `X-Hospital-Token`.

Both reach the same `Coordinator` methods, so the same validation applies either way. The coordinator has no
code path that opens a hospital's data directory; with external nodes it is not even given the path.

Weights travel as NumPy `.npz` archives loaded with `allow_pickle=False`. A pickled checkpoint could run
code on the coordinator; an `.npz` of plain arrays cannot.

Surveillance follows the same rule: hospitals report weekly **totals** per region and disease, with counts
of 1-4 suppressed at the hospital. No patient-level location exists anywhere in the system.

## Round lifecycle

```
CREATED ─▶ WAITING_FOR_CLIENTS ─▶ TRAINING ─▶ UPDATES_RECEIVING ─▶ AGGREGATING ─▶ EVALUATING ─▶ COMPLETED
     └───────────────────────────────── any step ─────────────────────────────────────▶ FAILED
```

1. **Create** - `POST /api/federated/rounds/start` validates the request, selects online hospitals that hold
   the modality, snapshots the configuration and the base model version, writes `FL_ROUND_CREATED`.
2. **Join** - each hospital calls `participate`; the coordinator records `HOSPITAL_JOINED_ROUND`.
3. **Distribute** - the hospital downloads the base global model (`MODEL_ACCESSED`); the round moves to
   `TRAINING`.
4. **Train locally** - the node trains from the global weights on its own data, optionally clips and noises
   the update.
5. **Receive and validate** - `updates` checks size, format, tensor names/shapes/dtypes against the global
   model, the architecture signature, finiteness and the sample count. Rejected updates are recorded with
   the reason and never aggregated (`LOCAL_UPDATE_RECEIVED`, status `REJECTED`).
6. **Aggregate** - when every expected update is in (or a coordinator presses *Aggregate now*), FedAvg
   runs: `W = Σ (n_k / N) · W_k` (`AGGREGATION_STARTED`, `AGGREGATION_COMPLETED`).
7. **Evaluate** - hospitals download the aggregate, score it on their local held-out split and return
   confusion matrices, which are pooled into global metrics.
8. **Register** - the aggregate becomes the next model version (`GLOBAL_MODEL_CREATED`), metrics are stored,
   the round is `COMPLETED`, temporary update files are deleted.

Failure handling: a hospital that fails or sends an invalid update is marked and skipped. The round
continues if at least `min_participants` valid updates remain; otherwise it fails and the registry is left
untouched. A round interrupted by a restart is marked failed on the next start (in-process nodes).

One round per modality can be active at a time. EHR, ECG and X-ray rounds are independent.

## Model registry and compatibility

Each modality has one lineage of versions: `v0` is the untrained initial model, and each completed round adds
one. A version stores architecture, backend, parameter count, the SHA-256 of its weights, its metrics and
the dataset description. Weight files are kept for the newest `MODEL_KEEP_VERSIONS` versions.

Every model has an **architecture signature**: a hash of its tensor names, shapes and numeric kinds, plus
`<backend>:<architecture>`. An update is aggregated only if its recomputed signature equals the round's
model signature, and `federated_average` independently refuses tensors that do not line up. That is what
keeps TabNet, CNN-BiLSTM and EfficientNet-B3 (and the NumPy stand-ins) from ever being mixed.

If the architecture for a modality changes (for example PyTorch is installed after the demo first ran with
stand-ins), the registry starts a fresh untrained version rather than loading incompatible weights.

## Model backends

`ml/registry.py` picks the implementation per modality behind one interface (`ModelAdapter`):

| `ML_BACKEND` | EHR | ECG | X-ray |
| --- | --- | --- | --- |
| `pytorch` (or `auto` with PyTorch installed) | TabNet | CNN-BiLSTM | EfficientNet-B3 |
| `numpy-reference` (or `auto` without PyTorch) | NumPy MLP | NumPy MLP | NumPy MLP |

The stand-ins exist so the whole workflow runs on a machine without PyTorch. They are real models trained
by real gradient descent, but they are not the target architectures, and the API and UI label them as
"NumPy reference MLP" wherever their results appear.

## Database

One schema (`backend/app/models/tables.py`) rendered for SQLite (demo) and PostgreSQL (Supabase;
`supabase/schema.sql`).

| Table | Contents |
| --- | --- |
| `users` | Identity (from the auth provider) and role |
| `hospitals` | Name, availability, modalities, record counts |
| `fl_rounds`, `fl_participants` | Round state, configuration, per-hospital status and summary metrics |
| `model_registry` | Model versions, hashes, metrics |
| `model_updates` | Update metadata: hash, size, norm, DP report, accepted or rejected |
| `training_metrics` | Local and global metrics per round |
| `regions`, `surveillance_reports` | Region boundaries; hospital-level weekly totals |
| `analytics_results`, `forecasts` | Cached hotspot results, explanations, forecasts |
| `audit_logs` | Hash-chained audit entries |

There is no table for patient records. The privacy check on the Settings page inspects the live schema for
patient-identifier-like columns on every load.

## Authentication and roles

The browser signs in with Supabase Auth and sends the access token as a Bearer token. The API verifies it
with Supabase (`GET /auth/v1/user`) and looks up the role in its own `users` table. New users start as
`viewer`; emails listed in `ADMIN_EMAILS` become `admin`.

| Role | Can |
| --- | --- |
| `viewer` | Read dashboards, models, surveillance, forecasts, explanations |
| `coordinator` | Also start, aggregate, finalise and cancel rounds; change hospital availability; read the audit log |
| `admin` | Everything a coordinator can |

When Supabase is not configured and `DEMO_MODE=true`, a demo provider issues short-lived tokens for three
built-in accounts so the prototype runs with no external services. It is disabled as soon as Supabase is
configured.

The Supabase **service-role key**, the database URL and the node-token secret exist only in `backend/.env`.
The frontend receives the Supabase URL and anon key, nothing else.

## Demo mode and real mode

| | Demo (`DEMO_MODE=true`) | Real (`DEMO_MODE=false`) |
| --- | --- | --- |
| Hospital data | Generated by `ml/simulation` | Prepared by `scripts/prepare_real_data.py` |
| Surveillance | Simulated regions and counts | `REGIONS_GEOJSON_PATH`, `SURVEILLANCE_REPORTS_CSV` |
| Auth | Supabase if configured, else demo accounts | Supabase (required) |
| Database | SQLite by default | Supabase Postgres (required) |
| Labelling | Everything marked SIMULATED / DEMONSTRATION DATA | Marked by actual data source |

The services, the round lifecycle, the transports and the UI are the same in both modes. Whether a result
is labelled simulated is decided by the data that produced it (the manifests of the hospitals that
trained), not by the mode flag.
