# Running the hospitals on separate machines

One laptop is the **coordinator** (API + dashboard). Every other laptop is a **hospital**: it holds its own
simulated records, trains on them, and sends back only model weights, record counts and summary metrics.
The dashboard shows each hospital as *Connected* with its machine name, device and software version, and
drops a hospital from a round if it goes quiet.

```
              same Wi-Fi, a phone hotspot, or Tailscale
 ┌───────────────────────────┐          ┌──────────────────────────────┐
 │ Laptop 1: coordinator     │◀─────────│ Laptop 2: hospital_b         │
 │  API        :8000         │  HTTP    │  data/hospitals/hospital_b/  │
 │  dashboard  :5173         │◀───┐     └──────────────────────────────┘
 │  (optionally hospital_a)  │    │     ┌──────────────────────────────┐
 └───────────────────────────┘    └─────│ Laptop 3: hospital_c  ...    │
                                        └──────────────────────────────┘
```

Hospitals only make outgoing connections to the coordinator. Only the coordinator laptop needs open ports.

Everything shown is **SIMULATED / DEMONSTRATION DATA**: the hospitals and their records are fictional.

---

## 0. Before the day

On **every** laptop (coordinator and hospitals):

1. Copy the **same** version of the repository (same git commit, or the same zip).
2. Install Python 3.10+ and the dependencies. Install PyTorch on every machine, because all of them must use
   the same model backend:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate                       # macOS/Linux: source .venv/bin/activate
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   pip install -r backend/requirements.txt
   ```

   PyTorch is about 200 MB, so download it at home rather than on the venue's Wi-Fi.

The coordinator laptop also needs Node.js 20.19+ and `cd frontend && npm install --legacy-peer-deps`.

Hospital laptops do not need Node.js, a database or any data from the coordinator.

---

## 1. Put the laptops on one network

Use one of these, in order of preference:

1. **A phone hotspot.** Connect every laptop to it. This is the most predictable choice at a review.
2. **The same Wi-Fi network.** This works at home. Campus and guest Wi-Fi often isolate clients from each
   other ("AP isolation"), and then nothing below will connect. If that happens, use a hotspot or Tailscale.
3. **Tailscale** (section 7) when the network blocks laptop-to-laptop traffic, or the laptops are on
   different networks.

Find the coordinator laptop's address:

| OS | Command | Look for |
| --- | --- | --- |
| Windows | `ipconfig` | "IPv4 Address" under the Wi-Fi adapter, e.g. `192.168.43.120` |
| macOS | `ipconfig getifaddr en0` | e.g. `192.168.43.120` |
| Linux | `hostname -I` | the first address |

Below, `SERVER_IP` means that address. It can change when you reconnect to a hotspot, so check it again on
the day.

---

## 2. Coordinator laptop: the API

Edit `backend/.env`:

```ini
DEMO_MODE=true
HOSPITAL_NODES=external          # hospitals are separate processes, not threads in the API
ML_BACKEND=pytorch               # must be the same on every machine (see section 6)

API_HOST=0.0.0.0                 # listen on the network, not just on this laptop
API_PORT=8000

# Fixed secrets. Without them the server invents new ones at every start, which
# invalidates every hospital's token and signs everyone out.
NODE_TOKEN_SECRET=<paste a long random string>
DEMO_JWT_SECRET=<paste another long random string>

# Browsers on other laptops open the dashboard at http://SERVER_IP:5173
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://SERVER_IP:5173
```

Generate the two secrets with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Start the API and print one token per hospital:

```bash
python run.py
python scripts/node_token.py
```

```
hospital_a  530e173a...
hospital_b  bdc3b52b...
hospital_c  d11fbcbf...
hospital_d  f6ddfc6e...
```

Each hospital laptop needs only its own line. A token is tied to `NODE_TOKEN_SECRET`; if you change the
secret, print the tokens again.

### Open the firewall (coordinator only)

**Windows.** Run in an *Administrator* terminal:

```powershell
netsh advfirewall firewall add rule name="FL-Healthcare API" dir=in action=allow protocol=TCP localport=8000 profile=any
netsh advfirewall firewall add rule name="FL-Healthcare dashboard" dir=in action=allow protocol=TCP localport=5173 profile=any
```

The first time `python` or `node` listens on the network, Windows may also show an "Allow access" prompt.
Allow it, and tick **both** Private and Public, because Windows usually classes phone hotspots as Public.
Remove the rules after the review:

```powershell
netsh advfirewall firewall delete rule name="FL-Healthcare API"
netsh advfirewall firewall delete rule name="FL-Healthcare dashboard"
```

**macOS.** Click *Allow* when asked whether Python and node may accept incoming connections.
**Linux (ufw).** `sudo ufw allow 8000/tcp && sudo ufw allow 5173/tcp`

---

## 3. Coordinator laptop: the dashboard

Edit `frontend/.env`. The dashboard runs in each viewer's browser, so `localhost` there would mean *their own*
laptop:

```ini
VITE_API_BASE_URL=http://SERVER_IP:8000
```

Start it so other laptops can open it:

```bash
cd frontend
npm run dev -- --host
```

Open `http://SERVER_IP:5173` on any laptop and sign in with `admin@fl-healthcare.demo` / `demo-password`.
Restart `npm run dev` whenever you change `frontend/.env`.

---

## 4. Each hospital laptop

First check the network path. Open `http://SERVER_IP:8000/api/health` in a browser on the hospital laptop. It
must show `"status":"ok"`. If it does not load, go to section 8 before continuing.

Then, with the hospital's own id and token:

```bash
python scripts/setup_hospital.py hospital_b --server http://SERVER_IP:8000 --token <hospital_b token>
```

This:

1. generates **only hospital_b's** simulated records, in `data/hospitals/hospital_b/` on this laptop;
2. saves the server address and token in `data/hospitals/hospital_b/node_config.json`;
3. checks that this laptop would train exactly the model the coordinator expects, and refuses to start
   otherwise;
4. starts the node, which sends a heartbeat every 10 seconds and waits for rounds.

```
[hospital_b] Riverside Medical Centre - SIMULATED hospital, fictional records
    EHR     690 train /  230 held-out  (simulated)
    ECG     390 train /  130 held-out  (simulated)
    XRAY    195 train /   65 held-out  (simulated)
19:26:17 [hospital_b] connected to http://192.168.43.120:8000 (coordinator 1.1.0)
19:26:17 [hospital_b] machine LAPTOP-RIYA, pytorch on cpu
19:26:17 [hospital_b] local records: ECG 520 (simulated), EHR 920 (simulated), XRAY 260 (simulated). They stay on this machine.
19:26:17 [hospital_b] waiting for rounds (Ctrl+C to stop)
```

Next time, the server address and token are remembered:

```bash
python scripts/setup_hospital.py hospital_b
```

Use a different hospital id on each laptop. You have four (`hospital_a` to `hospital_d`). If there are fewer
laptops, run the remaining hospitals on the coordinator laptop, each in its own terminal, with
`--server http://localhost:8000`.

---

## 5. Showing it at the review

1. **Hospitals page.** Every laptop appears as *Connected*, with its machine name, CPU/GPU, backend, node
   version and a "last heartbeat" that refreshes every few seconds.
2. **Federated Learning → Start new round.** Only connected hospitals are ticked. Leave the deadline at 600 s,
   or set it to 60 s to show a drop quickly. Each hospital's terminal prints *joining → training locally →
   update sent → evaluated*, while the round page fills in its lanes.
3. **A hospital fails.** Press Ctrl+C on one hospital laptop, or turn its Wi-Fi off, and start a round
   within 30 seconds. At the deadline the round page shows "1 hospital dropped from this round" with the
   reason, and the round completes with the others. After 30 seconds without a heartbeat, the Hospitals page
   shows that laptop as *Disconnected*.
4. **It comes back.** Run `python scripts/setup_hospital.py hospital_b` again. The laptop turns *Connected*,
   and **Audit Logs** records "Hospital node connected" with its machine name.
5. **Privacy point.** Records were generated on each hospital laptop and never left it: the coordinator's
   `data/` folder has no data for the remote hospitals. **Privacy** on the Settings page checks that the
   central database has no patient-level columns.

---

## 6. The ML backend must match everywhere

The coordinator averages the hospitals' weights layer by layer, which only works if everyone trains the same
network. At start-up each node compares its model with the coordinator's (backend, architecture and the
shapes of every layer) and refuses to start on a mismatch:

```
[hospital_b] not starting:
This node does not match the coordinator, so its updates would be rejected:
  - EHR: the coordinator trains TabNet (pytorch); this machine would train NumPy reference MLP (numpy-reference).
  ...
Every machine must use the same ML_BACKEND. The coordinator's is 'pytorch'; this machine's is 'numpy-reference'.
To use the PyTorch models here:  pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
```

The node's setting is `--ml-backend` (remembered; default `auto`, which means PyTorch when it is installed).
To fix a mismatch, install PyTorch on that laptop, or pass `--ml-backend pytorch`.

If the check reports "different shapes" with the same model name, the laptops have different versions of
the code or of torch/torchvision.

---

## 7. Tailscale (when the network gets in the way)

[Tailscale](https://tailscale.com/download) puts the laptops on a private network that works across campus
Wi-Fi, hotspots and different networks.

1. Install it on every laptop and sign in to **the same account** (or share the coordinator laptop with the
   others from the Tailscale admin page).
2. On the coordinator, `tailscale ip -4` prints an address like `100.101.102.103`. Use it as `SERVER_IP`
   everywhere above: in `CORS_ORIGINS`, in `VITE_API_BASE_URL`, and in `--server`.
3. Restart the API and `npm run dev -- --host`, then start the hospitals.

The firewall rules from section 2 are still needed on Windows.

---

## 8. Troubleshooting

| What you see | Cause and fix |
| --- | --- |
| Node: "Cannot reach the coordinator" | API not running; `API_HOST` is not `0.0.0.0`; wrong or changed `SERVER_IP`; firewall (section 2); network isolates clients (use a hotspot or Tailscale). Test with `http://SERVER_IP:8000/api/health` in the hospital laptop's browser. |
| Node: "rejected the token" | Wrong hospital's token, or `NODE_TOKEN_SECRET` changed. Run `python scripts/node_token.py` on the coordinator again. |
| Node: "does not match the coordinator" | Different `ML_BACKEND`, PyTorch missing, or different code versions. See section 6. |
| Node: "runs its hospitals inside the API" | The coordinator has `HOSPITAL_NODES=in-process`. Set it to `external` and restart. |
| Dashboard on another laptop: "Server unavailable" | `VITE_API_BASE_URL` still says `localhost`, or `CORS_ORIGINS` lacks `http://SERVER_IP:5173`. Restart both after editing. |
| Everyone is signed out after a restart | `DEMO_JWT_SECRET` is empty. Set it to a fixed value. |
| Hospital stays *Disconnected* although its terminal looks fine | Its heartbeats are not getting through. Its terminal will show "heartbeat failed". Check the network path as in the first row. |
| A round waits a long time | A hospital is invited but silent. It is dropped at the deadline (600 s by default; set it in the *Start new round* dialog). *Aggregate now* on the round page skips the wait. |
| Version warning at node start-up | The coordinator and the node run different copies of the repository. Use the same commit everywhere. |

---

## What crosses the network

| From a hospital to the coordinator | Never sent |
| --- | --- |
| Model weights after local training (`.npz`) | Records, images, ECG traces |
| Number of training records; per-modality record counts | Anything identifying a patient |
| Training loss/accuracy; confusion matrix on the local held-out split | The local dataset files |
| For EHR: per-feature mean SHAP values, averaged locally | Per-record explanations |
| Heartbeat: hospital id, machine name, ML backend, device, software version | |

Use HTTPS (a reverse proxy, or Tailscale's encrypted tunnel) if the network is not one you control.
