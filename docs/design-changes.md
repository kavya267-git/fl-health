# Design changes from the approved plan

The approved MediFed plan named two technologies that the built system does not use. This page records each
change and its reason, so that the report can quote it. Everything else in the plan was built as planned or is
listed as a remaining gap in the project's review notes.

## 1. React web app instead of Flutter

**Plan:** a Flutter client.
**Built:** one React web application (Vite, Tailwind), in `frontend/`.

**Reason.** One web app serves every role from any browser: administrators, coordinators, hospital operators
and managers, health officers, researchers and viewers. Each signs in to the same app and sees only the pages
their role allows (`docs/permissions.md`). That matters most for the multi-machine demo
(`docs/multi-machine.md`): the server laptop runs the API and the app, and every other laptop, phone or tablet
in the room opens it at `http://SERVER_IP:5173` with nothing to install. A Flutter client would need a build
per platform, or Flutter's web target, which would then be a second web front end to keep in step with the
first.

**What this costs.** No native mobile app and no offline mode. The pages are responsive and are checked at
phone width (390 px) in the step screenshots, which covers the planned use on a phone in a browser.

## 2. Our own coordinator instead of Flower

**Plan:** the Flower federated-learning framework for the server and the hospital clients.
**Built:** our own coordinator (`backend/app/federated/coordinator.py`) and hospital node
(`ml/training/hospital_node.py`), talking over the platform's HTTP API (`ml/training/http_transport.py`), or
in process for the single-laptop demo.

**Reason.** The platform needs things around each round that Flower's server loop does not give us without
replacing most of it:

- **Full control of the round lifecycle.** Every round moves through stored states (`CREATED`,
  `WAITING_FOR_CLIENTS`, `TRAINING`, `UPDATES_RECEIVING`, `AGGREGATING`, `EVALUATING`, `COMPLETED`, `FAILED`)
  and every hospital through its own (`INVITED`, `JOINED`, `UPDATE_SUBMITTED`, `UPDATE_REJECTED`,
  `EVALUATED`, `DROPPED`, ...). The states live in the database, so the dashboard shows them live, deadlines
  drop a hospital that stops answering, a server restart marks interrupted rounds instead of losing them, and
  a coordinator can finish a round with the hospitals that did report.
- **Update validation.** Before any update is aggregated, the coordinator checks its size, format, tensor
  structure, an architecture signature it recomputes from the tensors (it does not trust the hospital's),
  finite values and the sample count (`backend/app/federated/validation.py`). A rejected update is stored with
  its reason and shown on the round page.
- **Audit logging.** Round creation (with its full configuration, including the DP settings), each hospital
  joining, declining or being dropped, every update received or rejected, aggregation, the new global model
  and the round's completion or failure are written to the audit log with who did it and when. They sit next
  to the platform's other audited actions (sign-ins, model access, alerts, exports, capacity changes).
- **Role-scoped access.** Hospitals authenticate with their own node token and can reach only their own
  round endpoints; dashboard users see rounds according to their role. These checks share one permission
  table with the rest of the API (`backend/app/services/permissions.py`, tested against
  `docs/permissions.md`).

FedAvg itself is a short, tested function (`backend/app/federated/fedavg.py`), so writing it ourselves cost
little. The same coordinator code runs in the platform and in the experiment harness
(`experiments/harness.py`), so the reported results come from the code the platform runs.

**What this costs.** We do not get Flower's ready-made strategies or its simulation tooling. The strategies
the project needs (FedAvg, FedProx through the local loss, the DP prototype) are implemented and tested here.
