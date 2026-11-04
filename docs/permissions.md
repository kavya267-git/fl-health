# Roles and permissions

PrivaFuse serves several kinds of user. The backend enforces every rule below. The dashboard only hides what
the server would refuse anyway. The rules live in one table, `backend/app/services/permissions.py`, and
`backend/tests/test_permissions.py` checks that this page matches it.

## Roles

| Role | Who | Linked to |
| --- | --- | --- |
| Administrator | Runs the platform and manages accounts and roles. | — |
| FL coordinator | Starts and manages federated training rounds. | — |
| Viewer | Read-only access to the federation and the surveillance views. Every new account starts here. | — |
| Hospital operator | Runs one hospital's training node. | One hospital (`hospital_id`) |
| Hospital manager | Plans resources for one hospital (Phase 3). | One hospital (`hospital_id`) |
| Health officer | Government health officer who watches a jurisdiction. | One or more regions (`jurisdiction`) |
| Researcher | Works with aggregated data and model results. Access is granted by an administrator. | — |

Only an administrator can change a role (Settings → Users, or `POST /api/users/{id}/role`), and every change
is written to the audit log. A hospital operator or manager must be given a hospital, and a health officer at
least one known region. Any other role loses its hospital and jurisdiction links. Built-in demo accounts keep
their roles.

## Permissions

`yes` = allowed. `-` = refused with 403. `own` = only for the user's own hospital; another hospital's id gets
403. `jurisdiction` = only regions in the user's jurisdiction. Region lists, hotspot maps and the hotspot
summary are cut to those regions, and a forecast for any other region gets 403.

| Permission | Endpoints | Administrator | FL coordinator | Viewer | Hospital operator | Hospital manager | Health officer | Researcher |
| --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `dashboard_overview` | GET /api/analytics/overview | yes | yes | yes | yes | yes | - | yes |
| `surveillance_read` | GET /api/analytics/options, /hotspots, /forecast | yes | yes | yes | yes | yes | jurisdiction | yes |
| `explainability_read` | GET /api/analytics/explainability, /privacy | yes | yes | yes | yes | yes | - | yes |
| `hospitals_list` | GET /api/hospitals | yes | yes | yes | yes | yes | - | yes |
| `hospital_detail` | GET /api/hospitals/{id}, /{id}/metrics | yes | yes | yes | own | own | - | - |
| `hospital_participation` | POST /api/hospitals/{id}/participation | yes | yes | - | own | - | - | - |
| `hospital_availability` | POST /api/hospitals/{id}/availability | yes | yes | - | - | - | - | - |
| `my_hospital` | GET /api/my-hospital | - | - | - | own | own | - | - |
| `rounds_read` | GET /api/federated/rounds, /rounds/{id}, /rounds/{id}/metrics | yes | yes | yes | yes | yes | - | yes |
| `rounds_manage` | POST /api/federated/rounds/start, /aggregate, /finalize, /cancel | yes | yes | - | - | - | - | - |
| `models_read` | GET /api/models, /models/{id}, /models/{id}/metrics | yes | yes | yes | yes | yes | - | yes |
| `audit_read` | GET /api/audit, /api/audit/verify | yes | yes | - | - | - | - | - |
| `users_manage` | GET /api/users, POST /api/users/{id}/role | yes | - | - | - | - | - | - |

These need no role:
- **Anyone:** `GET /api/health`, `GET /api/system/config` and sign-in.
- **Any signed-in user:** `GET /api/auth/me`.
- **Hospital node endpoints:** these use the node's own token, not a user role.

### Scope details

- **Own hospital.** An operator or manager sees per-hospital round results only for their own hospital. The
  results of other hospitals in the same round are removed, and the global figures stay.
- **Jurisdiction.** Hotspot detection always runs on every region, so a region's status is the same whoever
  asks. The health officer's response is then cut to their regions. A region's list of flagged neighbours
  keeps only neighbours inside the jurisdiction.
- **Recent audit activity** on the dashboard is included only for roles with `audit_read`.

## Demo accounts

All demo accounts use the `DEMO_PASSWORD` set on the server (default `demo-password`):

| Account | Role | Scope |
| --- | --- | --- |
| admin@fl-healthcare.demo | Administrator | — |
| coordinator@fl-healthcare.demo | FL coordinator | — |
| viewer@fl-healthcare.demo | Viewer | — |
| hospital_a@ … hospital_d@fl-healthcare.demo | Hospital operator | hospital_a … hospital_d |
| manager_a@fl-healthcare.demo | Hospital manager | hospital_a |
| officer_north@fl-healthcare.demo | Health officer | regions R01–R06 |
| officer_south@fl-healthcare.demo | Health officer | regions R07–R12 |
| researcher@fl-healthcare.demo | Researcher | — |

The two health officers' jurisdictions use the simulated region ids (R01–R12). With real boundaries loaded
through `REGIONS_GEOJSON_PATH`, the region ids are the file's. Give real health officer accounts a
jurisdiction under Settings in that case.
