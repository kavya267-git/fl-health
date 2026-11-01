# Verification status

What has actually been executed, and what has not, so you know where to look first if something misbehaves.

The project was first built in a sandbox that blocked the Python and npm package registries, so PyTorch,
FastAPI, Vite and the dashboard libraries could not be installed there. Everything below marked
**1 Nov 2026** was then run for real on a Windows 11 laptop:

| | Version |
| --- | --- |
| Python | 3.13.2 |
| PyTorch / torchvision | 2.15.0+cpu / 0.29.2+cpu (CPU only, no GPU) |
| FastAPI / Starlette / Pydantic / NumPy | 0.162.0 / 1.10.0 / 2.14.2 / 2.5.4 |
| Node.js / Vite | 22.19.0 / 8.3.5 |
| React / React Router / Recharts / Leaflet / React Leaflet | 19.3.1 / 7.18.5 / 3.10.1 / 1.9.4 / 5.0.0 |
| Vitest / Tailwind CSS | 4.1.12 / 4.3.3 |

## Executed and passing

| What | How it was run |
| --- | --- |
| Backend, ML and analytics test suites: **210 tests, 0 skipped** | `pytest`, under real FastAPI, with PyTorch installed (1 Nov 2026) |
| PyTorch models: TabNet, CNN-BiLSTM, EfficientNet-B3, the shared training loop, save/load, FedAvg compatibility, Grad-CAM | `pytest ml/tests/test_torch_models.py`: 16 tests passed on the first run, with no code changes (1 Nov 2026) |
| Federated rounds with the PyTorch models: 10 EHR, 10 ECG, 3 X-ray, in-process nodes, `ML_BACKEND=pytorch` | Against the running API; results below (1 Nov 2026) |
| Four hospital nodes as separate processes over HTTP, each with its own data directory: start-up compatibility check, heartbeat, EHR / ECG / X-ray rounds | `scripts/setup_hospital.py` × 4 against a running API with `HOSPITAL_NODES=external` (1 Nov 2026) |
| A hospital process killed mid-federation: dropped at the round deadline, round completed with the other three, shown as *Disconnected* after 30 s, *Connected* again after restart, `NODE_CONNECTED` in the audit log, audit chain still valid | Same setup, watched in the browser (1 Nov 2026) |
| Node start-up refusals: mismatched ML backend, wrong token, unreachable coordinator | Same setup; each exits with a message that says what to fix (1 Nov 2026) |
| Frontend test suite: 6 files, 70 tests | `npm test` (1 Nov 2026) |
| Production build | `npm run build`, no errors (1 Nov 2026). One warning: the JS bundle is 1.03 MB (304 KB gzipped), above Vite's 500 KB advisory limit |
| Dev server and the real chart, map and icon libraries | `npm run dev`, in Chromium: Dashboard, Disease Surveillance (Leaflet map, region selection, legend, 12-week chart), Forecasting, Models and model detail (Recharts), Explainability (EHR SHAP global, ECG occlusion, X-ray Grad-CAM), Federated Learning, Hospitals (1 Nov 2026) |
| Round failure paths: rejected update, wrong architecture, NaN weights, failed hospital, too few hospitals, restart recovery, manual aggregation, cancel, missed deadline (training and evaluation) | Tests |
| Audit hash chain, including detection of an edited and a deleted entry | Tests |
| Hotspot detection, forecasting (including the no-leakage test), Shapley values (checked against a closed form), occlusion, DP clipping/noise/accounting, suppression, privacy checks | Tests |
| Real-data preparation for the EHR CSV, MIT-BIH heartbeat CSV and ChestX-ray14 index formats | Tests on small files written in those formats (not the real datasets) |
| Real mode (`DEMO_MODE=false`) bootstrap, and the Supabase auth provider | Tests with Supabase's HTTP endpoint mocked |

### PyTorch training results (simulated data, 4 hospitals, default settings)

Default settings: 2 local epochs, batch 32, learning rate 0.003, no DP. Times are from round start to
completion with in-process nodes, which train the four hospitals one after another on one CPU.

| Model | Seconds per round | F1 after round 1 → 5 → 10 | Recall after round 10 | Accuracy after round 10 |
| --- | --- | --- | --- | --- |
| EHR, TabNet (24 k parameters) | 9.5 (9.2–10.2) | 0.00 → 0.10 → 0.39 | 0.30 | 0.83 |
| ECG, CNN-BiLSTM (91 k) | 1.6 (1.5–2.1) | 0.46 → 0.93 → 0.99 | 0.98 | 0.99 |
| X-ray, EfficientNet-B3 (10.8 M), 3 rounds | 31.9 (30.5–33.1) | 0.00 → 0.00 (round 3) | 0.00 | 0.60 |

- **EHR** predicts only the majority class for rounds 1–4 (F1 0), then rises to about 0.39 by round 7 and
  stays there. Accuracy barely moves (0.82 → 0.83) because 18% of records are positive. Validation loss
  falls steadily (0.52 → 0.375). F1 is low because of the class imbalance and the 0.5 decision threshold,
  not because training has stopped.
- **ECG** learns the simulated beats almost perfectly. The simulated ECG task is easy; do not read this as
  real-world performance.
- **X-ray** predicts "No finding" for every image (accuracy 0.60 = the share of negatives). EfficientNet-B3
  is trained from random weights on about 750 64×64 images, which it shrinks to a 2×2 feature map. Expect
  progress only with `XRAY_PRETRAINED=true`, larger images or many more rounds.
- With the four hospitals as separate processes training in parallel, rounds were faster: EHR 7.2 s, X-ray
  26.2 s.

## Problems found while running it, and what changed

| Problem | Fix |
| --- | --- |
| `npm install` crashed inside npm 10.9 ("Cannot read properties of null (reading 'edgesOut')") | Install with `npm install --legacy-peer-deps`. That skips peer dependencies, so `react-is` (needed by Recharts) and `@testing-library/dom` (needed by the tests) were added to `package.json` explicitly |
| Errors on the round dialog were not announced to screen readers (`Note` had no `role="alert"`); one frontend test failed because of it | `Note` with `tone="alert"` now has `role="alert"` |
| Grad-CAM on the 64×64 phantoms used EfficientNet-B3's last block, a 2×2 map, so the heat map was a wash over the whole image | Grad-CAM uses the deepest block whose map is at least 7×7 (8×8 here; the last block for 224 px images), and the page names the layer used. Cached explanations are recomputed |
| The empty-heat-map note described occlusion ("when hidden") even for Grad-CAM | The wording now depends on the method |
| `python run.py` read `API_HOST`/`API_PORT` before loading `backend/.env`, so `API_HOST=0.0.0.0` in `.env` was ignored | `run.py` loads `backend/.env` first |
| An external hospital that went silent left its round waiting until someone aggregated by hand | Rounds now have a deadline (default 600 s per stage). Late hospitals are dropped; the round aggregates if `min_participants` updates arrived and fails otherwise |

## Still not executed

| What | Risk and what to do |
| --- | --- |
| Hospital nodes on physically separate laptops | The four-process test used one laptop and `localhost`. The network path (firewall, `API_HOST=0.0.0.0`, CORS, `VITE_API_BASE_URL`) is described in [multi-machine.md](multi-machine.md) but has not been tried across machines |
| CUDA | Only CPU was available. `FL_DEVICE=auto` picks CUDA when present |
| `XRAY_PRETRAINED=true` (ImageNet weights) | Not run; needs a one-time download |
| Supabase sign-in from the browser, and PostgreSQL through `psycopg` | Not run against a real Supabase project; SQLite was used throughout |
| Optional adapters: `shap` library, `statsmodels` ARIMA, `shapely` adjacency, `geopandas` boundary loading | Not installed; each is isolated behind a check for the package |
| Real datasets (MIMIC-IV, MIT-BIH, NIH ChestX-ray14) | Not available; nothing was trained on real data |

## Re-running the checks

```bash
pip install -r backend/requirements-dev.txt
pytest                                   # 210 tests; PyTorch tests run when torch is installed

cd frontend
npm install --legacy-peer-deps
npm test
npm run build
```

If a PyTorch round fails, the round's page shows each hospital's error message, and the server log has the
full traceback.
