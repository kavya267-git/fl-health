# Multi-laptop demo: one server, two hospital laptops

This is the setup for the project review. Three Windows laptops on one network:

| Laptop | Runs | Who signs in there |
| --- | --- | --- |
| **Laptop 1, server** | Coordinator API (port 8000) and dashboard (port 5173) | `admin@fl-healthcare.demo` |
| **Laptop 2, hospitals A + B** | Two hospital nodes, each in its own console window | `hospital_a@…` and `hospital_b@…` (two browser windows) |
| **Laptop 3, hospitals C + D** | Two hospital nodes, each in its own console window | `hospital_c@…` and `hospital_d@…` |

```
                 phone hotspot / same Wi-Fi / Tailscale

  Laptop 2                                         Laptop 1 (server)
    window "Hospital A"  data\hospitals\hospital_a ──┐
    window "Hospital B"  data\hospitals\hospital_b ──┤
                                                     ├──▶  API :8000, dashboard :5173
  Laptop 3                                           │
    window "Hospital C"  data\hospitals\hospital_c ──┤
    window "Hospital D"  data\hospitals\hospital_d ──┘
```

Every hospital's records are generated **on its own laptop** and never leave it. Nodes send only model weights,
record counts and summary metrics, and they only make outgoing connections. Only the server laptop needs
open ports. Everything shown is **SIMULATED / DEMONSTRATION DATA**.

Two hospitals on one laptop are two separate processes. Each has its own settings file
(`data/nodes/hospital_a.json`, `data/nodes/hospital_b.json`), its own data folder (`data/hospitals/hospital_a/`,
`data/hospitals/hospital_b/`) and its own console window, titled with the hospital's name. Every line it
prints starts with the hospital's name.

---

## 0. The day before (all three laptops)

1. Copy the **same** version of the project folder to each laptop (same git commit, or one zip).
2. Install Python 3.10+ and, in the project folder:

   ```powershell
   python -m venv .venv
   .venv\Scripts\activate
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   pip install -r backend/requirements.txt
   ```

   Install PyTorch on **all three** laptops: every machine must use the same model backend (section 6). It is
   about 200 MB, so download it at home, not on the venue's network.
3. On the server laptop only: install Node.js 20.19+ and run `cd frontend` then `npm install --legacy-peer-deps`.

---

## 1. Network

Connect all three laptops to **one phone hotspot**. That is the most predictable option at a review. The same
home Wi-Fi also works. Campus and guest Wi-Fi often stop laptops from reaching each other ("client
isolation"); if section 4's check fails there, switch to the hotspot or to Tailscale (section 7).

Windows asks whether a new network is *Private* or *Public*. Either works with the firewall rules below.

---

## 2. Laptop 1: server

Open a terminal in the project folder (`.venv\Scripts\activate` first) and run:

```powershell
python scripts\print_demo_setup.py
```

It prints this laptop's address (call it `SERVER_IP`, e.g. `192.168.43.120`), checks both `.env` files, and
marks each required value `OK` or `CHANGE`. Make `backend\.env` contain:

```ini
DEMO_MODE=true
HOSPITAL_NODES=external
ML_BACKEND=pytorch
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://SERVER_IP:5173
NODE_TOKEN_SECRET=<long random value, fixed>
DEMO_JWT_SECRET=<another long random value, fixed>
SIMULATION_END_WEEK=2026-11-02
```

and `frontend\.env`:

```ini
VITE_API_BASE_URL=http://SERVER_IP:8000
```

### Fixed demo week

`SIMULATION_END_WEEK=2026-11-02` pins the simulated surveillance data to the 104 weeks ending with the week
starting Monday 2 November 2026. Without it the data moves on every Monday, and so do the hotspots, alerts,
forecasts and bed projections. With it, the rehearsal and the review day show the same thing. Use a fresh
database for the demo, or one that has only ever used this setting.

Before the demo, compute the forecasts once on the server laptop (about 7 minutes) so that nothing waits on
training:

```powershell
python scripts\precompute_forecasts.py
```

**Why this week.** It was chosen on 10 November 2026 because it shows both things the review needs. A scan of
every week from 1 June to 2 November 2026 found potential hotspots in every week. This one (the example week
in the brief) has:

- **potential hotspots in the latest week:** dengue in Ashgrove (R01) and Eastholm (R05), both in
  `officer_north`'s jurisdiction (R01–R06), and influenza-like illness in Larchmont (R11), in
  `officer_south`'s (R07–R12). They also appear as open alerts;
- **a bed shortfall for hospital A** (Northfield General Hospital) once `manager_a@fl-healthcare.demo` enters
  the demo capacity on the Resource planning page: **184 beds, 14 ICU beds, 75% in use**. With the default
  (assumed) disease figures and the stored forecast:
  - dengue, weeks 1–3: "you may need 176–189 of your 184 beds", highlighted as a possible shortfall
    (the high end is above 184 by 5.3, 4.5 and 2.4 beds);
  - dengue, week 4: 170–181 beds, not highlighted;
  - all diseases together: above 184 beds in all four weeks;
  - no ICU shortfall (at most 13.1 of 14 ICU beds).

These capacity figures are demo inputs, chosen so that the page has a shortfall to show. They are not
Northfield's (fictional) real capacity. The bed numbers come from the precompute run on 10 November 2026. A
recompute on another machine can differ slightly in the last decimal of the forecast (floating point), so
the week-3 margin of 2.4 beds is the one to check at rehearsal.

`print_demo_setup.py` suggests a random value when `NODE_TOKEN_SECRET` is missing. Keep it fixed: the hospital
tokens are derived from it, so changing it invalidates every laptop's saved token. `DEMO_JWT_SECRET` keeps
everyone signed in across a server restart.

**Firewall.** In an *Administrator* terminal, once:

```powershell
netsh advfirewall firewall add rule name="PrivaFuse API" dir=in action=allow protocol=TCP localport=8000 profile=any
netsh advfirewall firewall add rule name="PrivaFuse dashboard" dir=in action=allow protocol=TCP localport=5173 profile=any
```

The first time Python and Node listen on the network, Windows also shows **"Windows Defender Firewall has
blocked some features"**. Tick **both** Private and Public networks and click *Allow access*, once for
`python.exe` and once for `node.exe`.

**Start** (two terminals):

```powershell
python run.py                              # terminal 1: the API
cd frontend; npm run dev -- --host         # terminal 2: the dashboard
```

Run `python scripts\print_demo_setup.py` again: now everything should say `OK`, and it prints one block of
commands per hospital laptop.

---

## 3. Laptops 2 and 3: hospitals

On each hospital laptop, open a terminal in the project folder and paste **that laptop's block** from
`print_demo_setup.py`. For laptop 2 it looks like:

```powershell
start "Hospital A" cmd /k .venv\Scripts\python scripts\setup_hospital.py hospital_a --server http://192.168.43.120:8000 --token 530e…  --ml-backend pytorch
start "Hospital B" cmd /k .venv\Scripts\python scripts\setup_hospital.py hospital_b --server http://192.168.43.120:8000 --token bdc3…  --ml-backend pytorch
```

Each line opens a new console window named after its hospital. In each window, the script:

1. generates **only that hospital's** simulated records into `data\hospitals\hospital_a\` (or `_b`);
2. saves the server address and token in `data\nodes\hospital_a.json` (git-ignored);
3. checks that this laptop would train exactly the coordinator's model, and that the token is right;
4. starts the node: a heartbeat every 10 s, then waits for rounds.

```
Hospital A · Northfield General Hospital · SIMULATED hospital, fictional records
Hospital A · EHR      900 train /   300 held-out (simulated)
...
21:40:12 Hospital A · connected to http://192.168.43.120:8000 (coordinator 1.1.0)
21:40:12 Hospital A · machine LAPTOP-RIYA · pytorch on CPU
21:40:12 Hospital A · waiting for rounds (Ctrl+C to stop)
21:41:03 Hospital A · round 4 (EHR) · invited, joining
21:41:03 Hospital A · round 4 (EHR) · training locally…
21:41:06 Hospital A · round 4 (EHR) · update sent (0.1 MB, trained in 2.4 s)
21:41:09 Hospital A · round 4 (EHR) · evaluated F1 0.41 on local held-out data
```

**Later runs** (the address and token are remembered):

```powershell
start "Hospital A" cmd /k .venv\Scripts\python scripts\setup_hospital.py hospital_a
start "Hospital B" cmd /k .venv\Scripts\python scripts\setup_hospital.py hospital_b
```

To use prepared real data instead of simulated data, add `--data <folder>` once (a folder written by
`scripts/prepare_real_data.py`, with `ehr/`, `ecg/` or `xray/` inside).

---

## 4. Check before the audience arrives

1. On each hospital laptop, open `http://SERVER_IP:8000/api/health` in a browser. It must show
   `"status":"ok"`. If not, see section 8.
2. On the server, the dashboard's **Hospitals** page shows all four hospitals as **Connected**, with the
   laptop's machine name, CPU/GPU, backend and node version, and a "last heartbeat" a few seconds ago.
   Hospitals A and B show laptop 2's machine name; C and D show laptop 3's.
3. On laptop 2, open the dashboard (`http://SERVER_IP:5173`) in two browser windows: sign in as
   `hospital_a@fl-healthcare.demo` in one and `hospital_b@fl-healthcare.demo` in the other. Sign-ins are kept
   per browser tab, so two windows of the same browser are two separate sessions. Do the same for C and D on
   laptop 3. All demo accounts use the password `demo-password`. Operators land on **My hospital**.

---

## 5. Showing it at the review

1. **Server laptop, as admin: Hospitals.** Four hospitals on two other laptops, all *Connected*.
2. **Federated Learning → Start new round** (EHR or ECG). Leave the deadline at 600 s, or set 60 s to show a
   drop quickly. Watch it happen in three places at once:
   - the server's round page: lanes fill in per hospital, FedAvg, new model version;
   - each hospital console: *invited → training locally… → update sent (… MB) → evaluated F1 …*;
   - each operator's **My hospital** page: the same four steps, live, and the F1 of the new global model on
     *that hospital's* held-out data.
3. **Privacy point.** On **My hospital**, an operator sees their own data counts and results, never another
   hospital's. Open laptop 2's `data\hospitals\` folder: only A and B are there. The server's `data\hospitals\`
   has neither. Under Settings, the privacy checks confirm the central database has no patient-level columns.
4. **A hospital opts out.** On laptop 3, Hospital D's operator switches **Take part in future rounds** off.
   Start a round: D is not invited, and its console says rounds will be declined. **Audit Logs** (admin) shows
   *Hospital participation changed*. Switch it back on.
5. **A hospital fails.** Close Hospital C's console window (or turn laptop 3's Wi-Fi off) and start a round
   within 30 seconds. At the deadline the round page shows *1 hospital dropped from this round* with the
   reason, and the round completes with the others. After 30 s without a heartbeat, C shows *Disconnected*.
   Run `setup_hospital.py hospital_c` again: *Connected*, and the audit log records *Hospital node connected*.

---

## 6. The ML backend must match everywhere

The coordinator averages the hospitals' weights layer by layer, so everyone must train the same network. At
start-up each node compares its backend, architecture and every layer's shape with the coordinator's, and
refuses to start on a mismatch:

```
Hospital B · not starting:
This node does not match the coordinator, so its updates would be rejected:
  - EHR: the coordinator trains TabNet (pytorch); this machine would train NumPy reference MLP (numpy-reference).
Every machine must use the same ML_BACKEND. The coordinator's is 'pytorch'; this machine's is 'numpy-reference'.
To use the PyTorch models here:  pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

The commands from `print_demo_setup.py` already pass the server's `--ml-backend`. If the check reports
"different shapes", the laptops run different copies of the code or different torch/torchvision versions.

---

## 7. Tailscale (when the network gets in the way)

[Tailscale](https://tailscale.com/download) gives the laptops private addresses that reach each other across
client-isolated Wi-Fi, hotspots or different networks.

1. Install it on all three laptops and sign in to **the same account**.
2. On the server laptop, `tailscale ip -4` prints an address like `100.101.102.103`.
3. Run `python scripts\print_demo_setup.py --ip 100.101.102.103` and use what it prints: the `.env` values
   and the hospital commands now use the Tailscale address. Restart the API and the dashboard after editing
   the `.env` files.

The firewall rules from section 2 still apply.

---

## 8. Troubleshooting

| What you see | Cause and fix |
| --- | --- |
| Node: "Cannot reach the coordinator at http://…" | API not running; `API_HOST` is not `0.0.0.0`; wrong or changed `SERVER_IP` (it can change when you reconnect to a hotspot); firewall (section 2); Wi-Fi isolates clients (use the hotspot or Tailscale). Test with `http://SERVER_IP:8000/api/health` in the hospital laptop's browser. |
| Node: "rejected the token for hospital_b" | Token from another hospital or an old `NODE_TOKEN_SECRET`. Run `print_demo_setup.py` on the server again and paste the new block. |
| Node: "has no hospital 'hospital_x'" | Typo in the hospital id. Use `hospital_a` … `hospital_d`. |
| Node: "does not match the coordinator" | Different `ML_BACKEND`, PyTorch missing, or different code versions (section 6). |
| Node: "runs its hospitals inside the API" | `HOSPITAL_NODES=in-process` on the server. Set it to `external` and restart. |
| Two hospitals on one laptop interfere | They should not: each has its own `data\nodes\<id>.json` and `data\hospitals\<id>\`. Check each window's title and line prefix to see which hospital it is. |
| Dashboard on a hospital laptop: "Server unavailable" | `VITE_API_BASE_URL` still says `localhost`, or `CORS_ORIGINS` lacks `http://SERVER_IP:5173`. Restart both after editing. |
| Operator sees "only open their own hospital's details" | Expected: operators cannot open other hospitals' detail pages. |
| Everyone is signed out after a server restart | `DEMO_JWT_SECRET` is empty. Set a fixed value. |
| Signed out after reloading in a new tab | Sign-ins are kept per tab (closing the tab signs out). Sign in again; duplicate the tab instead of opening a new one to keep the session. |
| A laptop went to sleep | Its nodes stop sending heartbeats and show *Disconnected* after 30 s; on waking they reconnect by themselves (the audit log shows *Hospital node connected*). Set the laptops' power settings to "never sleep when plugged in" before the review. |
| A hospital stays *Disconnected* although its window looks fine | Its heartbeats do not get through; its window says "heartbeat failed". Check the network path as in the first row. |
| A round waits a long time | A hospital is invited but silent. It is dropped at the deadline (default 600 s, set in *Start new round*); *Aggregate now* on the round page skips the wait. |
| A hospital is never invited | Its operator switched participation off (*Opted out of rounds* on the Hospitals page), or its node is not connected. |

---

## What crosses the network

| From a hospital to the server | Never sent |
| --- | --- |
| Model weights after local training | Records, images, ECG traces |
| Number of training records; record counts per modality | Anything identifying a patient |
| Training loss/accuracy; confusion matrix on the local held-out split | The local data files |
| For EHR: per-feature mean SHAP values, averaged locally | Per-record explanations |
| Heartbeat: hospital id, machine name, ML backend, device, software version | |

Traffic is plain HTTP on the local network. On a network you do not control, use Tailscale (encrypted) or put
the API behind HTTPS.
