# API reference

Base URL: `http://localhost:8000`. Interactive documentation is served at `/docs` (Swagger UI).

All requests and responses are JSON unless noted, and are described by Pydantic schemas in
`backend/app/schemas/`. Errors always have the form `{"detail": "..."}`.

| Status | Meaning |
| --- | --- |
| 401 | No session, or it has expired |
| 403 | Signed in, but the role (or node token) is not allowed |
| 404 | The round, hospital, model, region or disease does not exist |
| 409 | The request conflicts with current state (e.g. a round is already running) |
| 422 | The request is invalid, or a model update was rejected |
| 503 | A dependency is unavailable (database, authentication service, unconfigured data) |

**Authentication.** Dashboard endpoints need `Authorization: Bearer <access token>` (a Supabase access
token, or a demo token from `/api/auth/demo-login`). Hospital-node endpoints need
`X-Hospital-Token: <token>` for the hospital named in the request.

Roles: **viewer** can read; **hospital** (hospital operator, linked to one hospital) reads like a viewer, sees detailed pages and per-hospital results only for its own hospital, has `/api/my-hospital` and its hospital's participation switch, and cannot start rounds or read the audit log; **coordinator** and **admin** can also change state. Endpoints marked ✎ need
coordinator or admin.

## System

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/api/health` | none | Liveness and database check |
| GET | `/api/system/config` | none | Mode, auth provider, whether sign-up is open, hospital node mode, `ml_backend`, active model backends with their architecture signatures (nodes compare theirs at start-up), demo accounts (never passwords) |

## Authentication

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/auth/me` | The signed-in user and role |
| POST | `/api/auth/session` | Call once after a Supabase sign-in so the login is audited (`USER_LOGIN`) |
| POST | `/api/auth/demo-login` | `{email, password}` → `{access_token, expires_in, user}`. Built-in demo accounts and accounts created with `/register`. Only when Supabase is not configured |
| POST | `/api/auth/register` | `{email, password, display_name?}` → same response as a sign-in. The new account is always a `viewer`; a role cannot be requested. 409 if the email is taken, 422 for an invalid email or a password under 8 characters, 403 if `ALLOW_SIGNUP=false` or Supabase is configured (the web app then signs up through Supabase Auth) |

## Users (administrators only)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/users` | Every account with its role, and whether the role can be changed here |
| POST | `/api/users/{id}/role` | `{role, hospital_id?}`: `viewer`, `hospital`, `coordinator` or `admin`. `hospital_id` is required for `hospital` (422 without it or for an unknown hospital) and cleared for every other role. 409 for your own account, a built-in demo account or an `ADMIN_EMAILS` administrator. Audited as `USER_ROLE_CHANGED` |

## Hospitals

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/hospitals` | All hospitals: availability, modalities, record counts, current round, latest update |
| GET | `/api/hospitals/{id}` | One hospital. 403 for a hospital operator asking about another hospital |
| GET | `/api/hospitals/{id}/metrics` | Local training and validation metrics per round, and the global model's metrics on this hospital's data. 403 for a hospital operator asking about another hospital |
| POST ✎ | `/api/hospitals/{id}/availability` | `{online: bool}` - take a node offline or bring it back (in-process nodes only) |
| POST | `/api/hospitals/{id}/participation` | `{participating: bool}`: "Take part in future rounds". Allowed for that hospital's operator, a coordinator or an administrator. Off: the hospital is not invited, and its node declines rounds it was already invited to. Audited as `HOSPITAL_PARTICIPATION_CHANGED` |
| GET | `/api/my-hospital` | Hospital operators only: their hospital (with node status), its metrics, and its latest round seen from its side (own status, update size, local and global F1 on its held-out data) |

## Federated learning

### Dashboard

| Method | Path | Description |
| --- | --- | --- |
| POST ✎ | `/api/federated/rounds/start` | Create a round. Returns 201 with the round once it exists; training then proceeds in the background |
| GET | `/api/federated/rounds` | Rounds, newest first. Query: `modality`, `limit` |
| GET | `/api/federated/rounds/{id}` | Round with participants and progress counts |
| GET | `/api/federated/rounds/{id}/metrics` | Local metrics per hospital, global metrics, global-on-local metrics |
| POST ✎ | `/api/federated/rounds/{id}/aggregate` | Run FedAvg now on the valid updates received; hospitals that have not reported are dropped |
| POST ✎ | `/api/federated/rounds/{id}/finalize` | `{allow_partial}` - complete an evaluating round with the evaluations received |
| POST ✎ | `/api/federated/rounds/{id}/cancel` | Stop a round; it is recorded as failed |

`POST /api/federated/rounds/start` body:

```json
{
  "modality": "ehr",
  "hospital_ids": ["hospital_a", "hospital_b", "hospital_c", "hospital_d"],
  "local_epochs": 2,
  "batch_size": 32,
  "learning_rate": 0.003,
  "min_participants": 2,
  "auto_aggregate": true,
  "differential_privacy": { "enabled": false, "clip_norm": 1.0, "noise_multiplier": 0.0, "delta": 1e-5 },
  "simulated_missing_rate": 0.0,
  "deadline_seconds": 600
}
```

`simulated_missing_rate` (EHR only, 0 to 0.5, default 0 = off) is a test setting: each hospital blanks that
share of its feature values completely at random and fills them in by KNN imputation fitted on its own
training split (docs/methodology.md, "Missing values"). It is stored in the round's
`config.training.missingness`; a non-zero value for another modality is refused with 422.

Only `modality` is required. `hospital_ids` defaults to every online hospital that holds the modality (with
`HOSPITAL_NODES=external`: every hospital whose node sent a heartbeat in the last 30 s).

`deadline_seconds` (10 to 86400): hospitals with no update this long after the round starts are set to
`DROPPED`; the round then aggregates if at least `min_participants` updates arrived, and fails otherwise.
After aggregation, the same allowance applies to evaluations; hospitals that miss it are set to
`EVALUATION_FAILED` and the round completes with the evaluations it has. The round's `config.deadline` holds
`seconds`, `training_deadline_at` and `evaluation_deadline_at`.

Round statuses: `CREATED`, `WAITING_FOR_CLIENTS`, `TRAINING`, `UPDATES_RECEIVING`, `AGGREGATING`,
`EVALUATING`, `COMPLETED`, `FAILED`.

Participant statuses: `INVITED`, `JOINED`, `TRAINING`, `UPDATE_SUBMITTED`, `UPDATE_REJECTED`, `EVALUATED`,
`EVALUATION_FAILED`, `DROPPED`, `FAILED`.

### Hospital nodes (`X-Hospital-Token`)

| Method | Path | Description |
| --- | --- | --- |
| POST | `/api/federated/node/heartbeat` | `{hospital_id, hostname, ml_backend, device, software_version, architectures, data_summary}`, sent every ~10 s. `data_summary` is reduced to counts and source names. The hospital is online while these arrive |
| GET | `/api/federated/node/rounds?hospital_id=` | Open rounds this hospital is invited to and has not joined |
| POST | `/api/federated/rounds/{id}/participate` | `{hospital_id, data_summary}` - join; returns the training configuration. `data_summary` is reduced to counts and source names |
| GET | `/api/federated/rounds/{id}/global-model?hospital_id=&which=base\|result` | Weights as an `.npz` archive (binary): the round's base model, or the aggregate for evaluation |
| POST | `/api/federated/rounds/{id}/updates` | Multipart: `hospital_id`, `num_samples`, `metrics` (JSON), `dp_report` (JSON), `architecture_signature`, file `weights` (`.npz`). 422 with the reason if the update is rejected |
| POST | `/api/federated/rounds/{id}/evaluations` | `{hospital_id, evaluation: {confusion, loss_sum, num_samples}, explanation}` |
| POST | `/api/federated/rounds/{id}/failures` | `{hospital_id, stage, message}` |
| GET | `/api/federated/rounds/{id}/node-status?hospital_id=` | Round status, for polling between training and evaluation |

## Models

A model is identified by its modality: `ehr`, `ecg` or `xray`.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/models` | The three models: architecture in use and target architecture, backend, version, status, latest metrics |
| GET | `/api/models/{id}` | The model with its version history (status, round, weights hash, metrics) |
| GET | `/api/models/{id}/metrics` | Metric series by version, task and metric definitions, dataset and evaluation split, per-class results and confusion matrix for the latest version, local training loss per hospital |

`latest_metrics` is `null` until a round has completed; no placeholder numbers are returned.

## Analytics

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/analytics/overview` | Dashboard summary: KPIs, model status, rounds, hospitals, surveillance and forecast highlights, recent activity |
| GET | `/api/analytics/options` | Diseases, regions and weeks available |
| GET | `/api/analytics/hotspots?disease=&period=` | Regional statistics and hotspot candidates for one disease and week (`period` = week start, `YYYY-MM-DD`), with GeoJSON |
| GET | `/api/analytics/forecast?region_id=&disease=&horizon=` | Forecast (1-26 weeks) with model, MAE, RMSE, intervals and the candidates compared |
| GET | `/api/analytics/explainability?modality=&scope=global\|individual&case_id=` | Explanation for the modality's current global model |
| GET | `/api/analytics/privacy` | Privacy statement, what is shared, DP configuration and accounting, validation checks |

Each hotspot region record contains `region_id`, `disease`, `time_period`, `case_count`, `case_rate`
(per 100,000; `null` without a population), `anomaly_score`, `hotspot_flag` and `status`
(`NORMAL`, `ELEVATED`, `CANDIDATE_HOTSPOT`, `INSUFFICIENT_DATA`), plus the baseline and the reason.

A forecast contains `region_id`, `disease`, `forecast_horizon`, `predicted_values`, `model_name`,
`evaluation_metrics` and `uncertainty_interval`. When the series is too short or too incomplete the
response has `available: false` and a `reason` instead of values.

An explanation response always has `available`. When it is `false`, `reason` says why (for example the
model has not been trained yet) and `explanation` is `null`.

Responses built from simulated data carry `data_status: {"simulated": true, "label": "SIMULATED / DEMONSTRATION DATA"}`.

## Health officer

Scoped to a health officer's jurisdiction; administrators and coordinators see every region (see
[permissions.md](permissions.md)).

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/officer/situation` | Per disease and region: this week's count (and rate per 100,000 when populations are loaded), the usual level, the ratio, the status, hospitals reported out of hospitals that report there, and the ensemble forecast for 2-4 weeks with its likely range; plus `about_forecast` |
| GET | `/api/officer/forecast-status` | About this forecast: data date, validation window, members and weights per week ahead, or `available: false` while it is computed |
| GET | `/api/officer/situation.csv` | The report as CSV. While the data is simulated the first line is `# SIMULATED DATA – NOT REAL CASES` and every row's `data_flag` column carries the same text |
| GET | `/api/officer/situation.pdf` | The report as PDF; the same watermark is printed across and at the top of every page |
| GET | `/api/alerts?state=OPEN\|ACKNOWLEDGED\|CLOSED` | Alerts: a region that became a potential hotspot in a week |
| POST | `/api/alerts/{id}/acknowledge` | Acknowledge an open alert (✎) |
| POST | `/api/alerts/{id}/outcome` | Body `{"outcome": "CONFIRMED"\|"NOT_CONFIRMED"\|"REPORTING_ARTEFACT", "note": "..."}`; only after acknowledging (✎) |

An alert id outside the officer's jurisdiction answers `404 No such alert.`, exactly like an unknown id, so
the response does not reveal that the alert exists or which region it concerns. Hotspot precision
(`scripts/hotspot_precision.py`) counts only outcomes recorded by health officers; outcomes an administrator
records are listed separately.

Exports, acknowledgements and outcomes are written to the audit log (`SITUATION_REPORT_EXPORTED`,
`ALERT_ACKNOWLEDGED`, `ALERT_OUTCOME_RECORDED`; alerts themselves are logged as `ALERT_CREATED`).

## Resource planning

See [resource-planning.md](resource-planning.md) for the method. Hospital managers see their own hospital;
administrators pass `hospital_id`.

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/planning?hospital_id=` | Capacity, assumptions and the bed projection per disease for weeks 1-4 (admissions, beds, ICU beds and total beds, low / central / high, with over-capacity flags), weeks grouped for plain sentences, and all diseases together. `available: false` with a `reason` until capacity is entered and the forecast is ready |
| POST | `/api/planning/capacity` | Body `{"total_beds", "icu_beds", "occupancy_percent"}`; hospital managers only, for their own hospital; every entry is kept (✎) |
| GET | `/api/planning/capacity/history?hospital_id=` | Every capacity entry, newest first |
| GET | `/api/planning/assumptions` | Per disease: `admission_rate`, `icu_share`, `length_of_stay_days`, `is_default` and the label ("Assumed values, replace with local figures" for defaults) |
| POST | `/api/planning/assumptions/{disease}` | Administrators only; same three fields (✎) |

## Audit (✎)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/api/audit` | Entries, newest first. Query: `search`, `action`, `status`, `hospital_id`, `round_id`, `date_from`, `date_to`, `limit`, `offset` |
| GET | `/api/audit/verify` | Recompute the hash chain; reports the first altered, removed or reordered entry |

Entry fields: `timestamp`, `actor`, `action`, `hospital_id`, `round_id`, `model_version`, `status`,
`details`, `previous_hash`, `current_hash`.

Actions: `USER_LOGIN`, `FL_ROUND_CREATED`, `HOSPITAL_JOINED_ROUND`, `LOCAL_UPDATE_RECEIVED`,
`AGGREGATION_STARTED`, `AGGREGATION_COMPLETED`, `GLOBAL_MODEL_CREATED`, `FL_ROUND_COMPLETED`,
`FL_ROUND_FAILED`, `ANALYTICS_GENERATED`, `FORECAST_GENERATED`, `MODEL_ACCESSED`,
`HOSPITAL_STATUS_CHANGED`.
