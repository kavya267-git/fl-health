# Hospital onboarding

How a hospital joins a MediFed deployment: it registers, an administrator approves it, and it connects its own
computer with the MediFed Hospital Agent. Patient records never leave that computer. Federated learning keeps
raw records local; it is not by itself a guarantee of privacy (model updates can still leak information; see
docs/methodology.md, "Privacy").

## 1. Register (public, no sign-in)

The sign-in page links to **Register your hospital** (`/register`). The form asks for:

- hospital name, the region it serves (from the region list), contact name and email, and a password;
- which kinds of data it will train on (EHR, ECG, X-ray) and roughly how many records of each;
- a required confirmation: *"I confirm we will not upload patient data; training runs on our own machine."*

There is no upload and no field for patient-level data. `POST /api/registrations` validates every field strictly,
refuses unknown fields, and is rate-limited per address (5 an hour, plus a global cap of 60 an hour; behind a
proxy set `TRUST_PROXY_HEADERS=true` so the client's own address is used). The password is stored as a scrypt
hash. The operator account is created **disabled**: signing in says the hospital is waiting for approval.
Requests are visible only to administrators.

## 2. Approve (administrator)

**Hospital requests** (`/hospital-requests`, administrators only, with a badge showing how many are pending) lists
requests as pending, approved, rejected or revoked.

- **Approve** creates the hospital (`hospital_<slug of its name>`, never a built-in id such as `hospital_a`) in the
  chosen region, with the modalities it declared, and enables the account as that hospital's operator.
- **Reject** needs a reason. The account stays disabled.
- **Revoke** (an approved hospital) needs a reason. The operator can no longer sign in, an open session ends, and
  the hospital's node token stops working at once.

Every step is written to the hash-chained audit log: `HOSPITAL_REGISTRATION_SUBMITTED`, `_APPROVED`, `_REJECTED`,
`_REVOKED`, `NODE_TOKEN_ISSUED`, `NODE_DATA_CHECK_REPORTED`.

## 3. Connect (operator)

After approval the operator signs in and lands on **My hospital**, which shows **Connect your hospital**:

1. **Generate node token.** A random token, shown once with a copy button. The server keeps only its SHA-256
   hash. Generating a new token revokes the previous one at once. (The built-in hospitals A-D keep their tokens
   derived from `NODE_TOKEN_SECRET`; that kind of token never works for a registered hospital.)
2. **Download MediFed Hospital Agent for Windows** (the latest GitHub Release asset).
3. Three steps with screenshots: open the agent and paste the token, choose the data folder and click **Check
   data**, click **Connect**.
4. **Data template** (a zip): column lists, accepted ranges, one row of made-up values for EHR and for ECG, and how
   to turn CSV files into the folder the agent reads (`scripts/prepare_real_data.py --hospitals <id> ...`).
5. **Live status:** Not connected → Connected (machine name, backend, last heartbeat) → data check passed (per
   kind of data) → invited to rounds.

## 4. The MediFed Hospital Agent

A Windows program that contains only what a hospital's computer needs: the node client, the model definitions,
the local data check, and the training and evaluation code. It contains nothing of the server, the dashboard or
the database. Window:

- server address (pre-filled with the deployment's API address), node token, **Check token** (shows the
  hospital's name and declared data);
- **Choose data folder…**, or **Use sample data (SIMULATED)**: fictional records generated on that computer and
  labelled simulated everywhere;
- **Check data**: runs on that computer only and shows passed or failed, record counts and problems per kind of
  data;
- **Connect / Disconnect**, **Take part in rounds** (off: every invitation is declined), and a live activity log
  (connected, invited, training, update sent with its size, evaluated F1).

Headless: `medifed-agent.exe --server <address> --token <token> --data <folder>` (or `--sample-data`).

The server address and hospital id are saved in `%APPDATA%\MediFed Agent\settings.json`. The token is kept in
Windows Credential Manager, or, where no credential store is available, in a file in the same folder that only
the current user can read. It is never written to the settings file or to the log. HTTPS certificates are always
verified.

**What leaves the computer:** model weights, record counts and summary metrics (as for every node), and for the
data check only pass or fail, counts per label and short problem notes. When the agent connects it reports the
check; the hospital is invited only to the kinds of data it declared **and** whose check passed. The
coordinator's architecture-signature check is unchanged: a node whose model does not match is refused before it
trains.

**Surveillance counts:** the hospital's region is recorded at approval. The agent does not send weekly case
totals, so a registered hospital does not contribute to the surveillance map. (The map's counts are the
coordinator's simulated reports for hospitals A-D.)

### Building the agent

```powershell
python -m venv agent-venv
agent-venv\Scripts\pip install -r hospital_agent\requirements.txt pyinstaller --extra-index-url https://download.pytorch.org/whl/cpu
agent-venv\Scripts\python hospital_agent\build_agent.py --server https://<your-api-address>
```

This writes `hospital_agent\dist\MediFed-Hospital-Agent-Windows.zip`. Pushing a tag `agent-v<version>` runs
`.github/workflows/agent-release.yml`, which builds the same zip on `windows-latest` and attaches it to a GitHub
Release; the repository variable `MEDIFED_API_URL` sets the pre-filled address. The agent's PyTorch,
torchvision and NumPy versions are pinned to the coordinator's so that the models match exactly.

Our own demo hospitals A-D can still run from a repository checkout with `scripts/setup_hospital.py`
(`requirements-node.txt` has only the node's packages).
