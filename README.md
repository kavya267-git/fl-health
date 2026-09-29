# ?? FL-Health  Federated Learning for Privacy-Preserving Healthcare

> **"Data stays local. Only learning travels."**

FL-Health is a full-stack federated learning platform that enables hospitals to collaboratively train disease-prediction AI models **without ever sharing patient data**. Every hospital trains on its own local data; only encrypted, differentially-private model weight updates are sent to the central server. The global model improves with every round while individual patient records never leave the hospital.

---

## ?? Table of Contents

- [Overview](#-overview)
- [Architecture](#-architecture)
- [Key Features](#-key-features)
- [Project Structure](#-project-structure)
- [Tech Stack](#-tech-stack)
- [How It Works](#-how-it-works)
- [API Reference](#-api-reference)
- [Frontend Architecture (React)](#-frontend-architecture-react)
- [Setup & Installation](#-setup--installation)
- [Environment Variables](#-environment-variables)
- [Deployment (Railway)](#-deployment-railway)
- [Data Formats Supported](#-data-formats-supported)
- [Privacy & Security](#-privacy--security)
- [Database Schema](#-database-schema)

---

## ?? Overview

FL-Health solves a fundamental problem in healthcare AI: **hospitals cannot share patient data due to HIPAA / GDPR regulations**, yet AI models need large datasets to be accurate.

**The solution  Federated Learning:**
1. Each hospital trains a local model on its own data.
2. Only the local model weight updates (not raw data) are sent to the server.
3. The server aggregates updates using **FedAvg** (Federated Averaging).
4. The improved global model is distributed back to all hospitals.
5. Every step is logged to an immutable **blockchain-style audit trail**.

---

## ??? Architecture

```
+---------------------------------------------------------+
                     FL-Health Server                    
             FastAPI    Python 3.13    PyTorch         
                                                         
  +----------+  +----------+  +----------+  +--------+  
  FLEngine     Audit      Geospatial   Auth     
   FedAvg     Blockchain   KMeans +   Supabase  
   DP Noise    SHA-256     Forecast     JWT     
  +----------+  +----------+  +----------+  +--------+  
+---------------------------------------------------------+
                                REST API (JSON)
         +--------------------+--------------------+
                                                 
  +------?------+     +------?------+     +------?------+
    Hospital A        Hospital B        Hospital C 
    Local Data        Local Data        Local Data 
    (EHR/ECG/         (EHR/ECG/         (EHR/ECG/  
     X-ray)            X-ray)            X-ray)    
  +-------------+     +-------------+     +-------------+
```

> Only model weight updates travel. Raw patient data never leaves the hospital.

**Supabase** serves as the backend database (PostgreSQL), authentication provider, and row-level-security enforcer.

---

## ? Key Features

| Module | Description |
|--------|-------------|
| ?? **Multi-Modal Federated Learning** | Supports EHR (CSV), ECG (NPY/WAV/DAT), and medical images (PNG/JPG/BMP)  all encoded into 32-dim embeddings before training |
| ?? **Adaptive Differential Privacy** | Laplace mechanism noise injection (e = 1.0 default, configurable per round). Quality-based noise: better data ? less noise |
| ?? **Blockchain Audit Trail** | Every training event (UPLOAD, TRAIN, CREDENTIAL_ISSUE) is written to a SHA-256 hash-linked chain in Supabase for full tamper-evidence |
| ??? **Verifiable Credentials** | Government-simulated W3C Verifiable Credential issuance per hospital. Only credentialed hospitals can participate in training |
| ??? **Geospatial Disease Surveillance** | K-Means clustering of hospital locations + case counts detects outbreak hotspots. Ensemble model (ARIMA + Prophet-style + Logistic) gives 14-day forecasts |
| ?? **Real-Time Dashboard** | Live convergence charts, privacy budget tracker, per-hospital accuracy, outbreak forecasts, and SHAP-style explainability |
| ????? **Admin Panel** | Full hospital approval workflow, credential issuance, audit chain verification, and hospital management |

---

## ?? Project Structure

```
fl-health-main/

+-- run.py                        # Entry point  starts Uvicorn server
+-- Procfile                      # Heroku/Railway process file
+-- railway.json                  # Railway deployment config (Railpack)
+-- nixpacks.toml                 # Nixpacks build config (Python 3.13)
+-- requirements.txt              # Top-level Python dependencies

+-- backend/
   +-- __init__.py
   +-- requirements.txt          # Backend-specific deps (mirrors root)
   +-- app/
       +-- main.py               # FastAPI app, all REST endpoints
       +-- auth.py               # JWT bearer auth, role-based access (hospital / admin)
       +-- fl_engine.py          # FedAvg aggregation, DP noise, local training loop
       +-- encoders.py           # Multi-modal encoders (EHR, ECG, Image, Text ? embeddings)
       +-- credential_manager.py # W3C Verifiable Credential issuance & validation
       +-- audit.py              # SHA-256 blockchain audit trail (Supabase)
       +-- geospatial.py         # K-Means hotspot detection + 14-day outbreak forecast
       +-- supabase_client.py    # Supabase anon + service-role client setup

+-- clients/
   +-- client_template.py        # Python SDK template for hospital-side integration

+-- frontend-react/
   +-- package.json              # Vite & React dependencies (start: serve -s dist)
   +-- index.html                # Vite entry point
   +-- src/
       +-- App.jsx               # React Router config
       +-- config.js             # API base URL configuration
       +-- index.css             # Global styles (fonts, resets, map overrides)
       +-- pages/                # React Page Components (Home, Dashboard, Admin, etc.)
       +-- components/           # Reusable UI (Navbar, Charts, DiseaseMap, etc.)
       +-- assets/               # Images used in frontend

+-- data/
    +-- global_model/             # Saved global model weights (classifier.pth)
    +-- hospitals/                # Per-hospital uploaded data (gitignored)
```

---

## ??? Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.13, FastAPI, Uvicorn |
| **ML / FL** | PyTorch 2.2+, scikit-learn (K-Means), NumPy |
| **Database & Auth** | Supabase (PostgreSQL + Row Level Security + JWT Auth) |
| **Data Processing** | Pandas, Pillow (images), wave (audio/ECG) |
| **Privacy** | Laplace Differential Privacy (custom implementation) |
| **Audit** | SHA-256 blockchain-style chain (stored in Supabase) |
| **Frontend** | React 19, Vite, CSS Modules, Chart.js, React-Leaflet |
| **Deployment** | Railway (Nixpacks for Python Backend & React SPA Frontend) |

---

## ?? How It Works

### Step-by-Step Federated Training Flow

```
1. REGISTER     Hospital registers with name, email, license number, location
                +-? Server creates Supabase auth user + hospitals table entry
                    Status: pending approval

2. APPROVE      Admin reviews and approves hospital via admin panel
                +-? Server issues a W3C Verifiable Credential (valid 1 year)
                    Credential hash stored in hospitals table
                    Event logged to blockchain_audit table

3. UPLOAD       Hospital uploads local dataset (CSV / NPY / images / WAV / ZIP)
                +-? Files saved to data/hospitals/<hospital_id>/

4. TRAIN        Hospital calls /api/hospital/train with credential_hash + epsilon
                +-? Server validates credential (hash match + not expired + approved)
                    encode_file() converts data to 32-dim embeddings
                    SharedClassifier trained locally (Adam optimizer, BCELoss)
                    Laplace noise added (scale = 1/epsilon)
                    Noisy weights stored in memory (client_updates dict)
                    Training history + hospital record updated in Supabase
                    Event logged to blockchain_audit

5. AGGREGATE    Any hospital triggers /api/hospital/aggregate
                +-? FedAvg: weighted average of all stored client updates
                    Global model saved to data/global_model/classifier.pth
                    Round counter incremented

6. MONITOR      Dashboard polls convergence, privacy budget, geospatial hotspots
                +-? K-Means clusters hospitals by (lat, lng, cases)
                    14-day ensemble forecast (ARIMA + growth + logistic)
                    Blockchain audit trail viewable and verifiable
```

### Neural Network Architecture

```
Input Data  ?  Modality Encoder  ?  32-dim Embedding  ?  SharedClassifier  ?  Prediction (0/1)

Modality Encoders:
  EHR (CSV)    ? EHREncoder    (Linear ? ReLU ? Linear ? ReLU)
  ECG (NPY)    ? ECGEncoder    (BiLSTM, 2 layers, hidden=64)
  Image (PNG)  ? ImageEncoder  (3x Conv2d ? AdaptiveAvgPool ? Linear)
  Text (TXT)   ? TextEncoder   (hash-based bag-of-words, normalized)

SharedClassifier:
  Linear(32 ? 16) ? ReLU ? Linear(16 ? 1) ? Sigmoid
```

---

## ?? API Reference

**Base URL:** `https://<your-railway-domain>` or `http://localhost:8000` locally

### Public Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check, lists all endpoints |
| `GET` | `/docs` | Interactive Swagger UI |
| `GET` | `/api/public/hospital-count` | Total registered hospitals |
| `POST` | `/api/auth/register` | Register a new hospital |
| `POST` | `/api/auth/login` | Login, returns JWT access token |

### Hospital Endpoints *(Bearer token required)*

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/hospital/me` | Get current hospital profile |
| `POST` | `/api/hospital/upload-data` | Upload training data file |
| `DELETE` | `/api/hospital/clear-data` | Clear uploaded data |
| `POST` | `/api/hospital/validate-credential` | Validate credential hash |
| `POST` | `/api/hospital/train` | Run local training + submit update |
| `POST` | `/api/hospital/aggregate` | Trigger FedAvg aggregation |
| `GET` | `/api/hospital/history` | Get training history for this hospital |

### Admin Endpoints *(Admin bearer token required)*

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/admin/all-hospitals` | List all registered hospitals |
| `GET` | `/api/admin/pending-hospitals` | List unapproved hospitals |
| `POST` | `/api/admin/approve-hospital/{hospital_id}` | Approve + issue credential |

### Dashboard Endpoints *(Public)*

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/dashboard/hospitals` | Hospital list with accuracy, city, state |
| `GET` | `/api/dashboard/convergence` | Training accuracy per round |
| `GET` | `/api/dashboard/privacy-budget` | Epsilon used vs budget |

### Audit Endpoints *(Public)*

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/audit/trail` | Last 100 audit entries (blockchain) |
| `GET` | `/api/audit/verify` | Verify full SHA-256 chain integrity |

### Geospatial Endpoints *(Public)*

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/geospatial/hotspots` | K-Means disease hotspot clusters |
| `GET` | `/api/geospatial/forecast` | 14-day ensemble outbreak forecast |

---

## 📊 Frontend Architecture (React)

The frontend was recently migrated to a modern **React + Vite** architecture for better component reusability and state management.

| Page (`src/pages/`) | Description |
|------|-------------|
| `Home.jsx` | Landing page - hero, feature cards, outbreak map preview, CTA |
| `Login.jsx` | Sign-in form (hospital or admin) |
| `Register.jsx` | Hospital registration - name, email, password, license, geo-coordinates |
| `Dashboard.jsx` | Hospital dashboard - upload data, train, view accuracy, privacy budget, history, and global model download |
| `Admin.jsx` | Admin portal - approve hospitals, model metrics, 24h audit trail |
| `Network.jsx` | Live federated network map with participant markers |
| `About.jsx` | Educational explainer on Federated Learning |
| `Privacy.jsx` | System privacy policy |

All pages use the API base URL from `frontend-react/src/config.js`.

---

## ?? Setup & Installation

### Prerequisites

- Python 3.13+
- A [Supabase](https://supabase.com) project with the schema described below

### Local Development

```bash
# 1. Clone the repository
git clone https://github.com/your-org/fl-health.git
cd fl-health

# 2. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
copy backend\.env.example backend\.env
# Edit backend\.env with your Supabase credentials

# 5. Start the server
python run.py
```

- Server: **http://localhost:8000**
- Swagger docs: **http://localhost:8000/docs**

### Open the Frontend

```bash
cd frontend-react
npm install
npm run dev
# Open http://localhost:5173
```

Make sure `frontend-react/src/config.js` points to your running backend:

```js
// frontend-react/src/config.js
export const API_URL = "http://localhost:8000"; // Or your Railway production URL
```

---

## ?? Environment Variables

Create `backend/.env`:

```env
# Supabase Project Settings (Project Settings ? API)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_ANON_KEY=your_anon_public_key
SUPABASE_SERVICE_KEY=your_service_role_key   # Keep this secret!

# Admin Account (must exist in Supabase Auth + admins table)
ADMIN_EMAIL=admin@yourdomain.com
ADMIN_USER_ID=your-admin-uuid

# Server
API_HOST=0.0.0.0
API_PORT=8000
SECRET_KEY=your-secret-key-here
```

> ?? **Never commit real keys to Git.** `backend/.env` is listed in `.gitignore`.

---

## ?? Deployment (Railway)

The project is pre-configured for [Railway](https://railway.app):

- **`railway.json`**  Uses Railpack builder, starts with `python run.py`, restarts on failure (max 10 retries)
- **`nixpacks.toml`**  Installs Python 3.13, runs `pip install -r requirements.txt`
- **`Procfile`**  `web: python run.py`
- Railway automatically injects `PORT`; `run.py` reads it via `os.getenv("PORT", 8000)`

### Deploy Steps (Backend & Frontend)

**1. Deploy Backend:**
1. Push this repo to GitHub
2. Create a new Railway project -> "Deploy from GitHub repo"
3. Select your `fl-health` repository. (Railway will automatically use the root `railway.json` to build the Python backend).
4. Set environment variables in the Railway dashboard (same as `.env` above).
5. Railway builds and deploys the backend automatically.

**2. Deploy React Frontend:**
1. In the same Railway project, click **New** -> **GitHub Repo** and select the `fl-health` repo again.
2. Quickly click the newly created service and go to **Settings > Environment**.
3. Under **Build**, change the **Root Directory** to `/frontend-react`.
4. Railway will automatically detect Vite, install dependencies, and run `npm run build`. 
5. Go to **Settings > Networking** and click **Generate Domain** to get your public URL.

---

## ?? Data Formats Supported

| Format | Medical Type | Encoder |
|--------|-------------|---------|
| `.csv` | EHR (Electronic Health Records) | `EHREncoder`  linear autoencoder |
| `.npy`, `.npz`, `.dat` | ECG / Signal data | `ECGEncoder`  2-layer BiLSTM |
| `.wav` | ECG / Audio signals | `ECGEncoder`  reads via `wave` module |
| `.png`, `.jpg`, `.jpeg`, `.bmp` | X-rays / Medical images | `ImageEncoder`  3x Conv2D |
| `.txt`, `.json` | Clinical text / reports | `TextEncoder`  hash bag-of-words |
| `.zip` | Archive of any of the above | Extracted server-side, then encoded |

All formats are encoded into a **32-dimensional embedding** before training  the same `SharedClassifier` works across all data modalities.

---

## ?? Privacy & Security

### Differential Privacy
- **Algorithm**: Laplace Mechanism  noise sampled from `Laplace(0, 1/e)` added to each weight tensor
- **Default e**: `1.0` (configurable per training call via the `epsilon` form field)
- **Privacy score formula**: `min(1/(1+e)  min(data_size/1000, 1), 1.0)`  displayed on dashboard

### Verifiable Credentials
- **Format**: W3C Verifiable Credential standard
- **Contents**: hospital ID, name, license number, approved diseases, expiry date (1 year)
- **Verification**: SHA-256 hash stored in database; credential hash must match + not be expired + hospital must be government-approved before training is allowed
- **Issuer**: `FL-Health Government Authority (Simulated)`

### Blockchain Audit Trail
- Every event (UPLOAD, TRAIN, CREDENTIAL_ISSUE) creates a record in the `blockchain_audit` Supabase table
- Each record contains `previous_hash` (previous entry's hash) + `current_hash` (SHA-256 of this entry's full data chained to previous)
- The `/api/audit/verify` endpoint re-computes the entire chain from genesis and flags any tampered record

### Role-Based Access Control
- **Hospital role**: verified via `hospitals` table lookup (service client bypasses RLS)
- **Admin role**: verified via separate `admins` table lookup
- All protected endpoints use FastAPI `Depends(require_role(...))` pattern

---

## ??? Database Schema

### `hospitals`
| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid PK | Matches Supabase auth user ID |
| `hospital_name` | text | Display name |
| `hospital_id` | text | Auto-generated `HOSP-XXXXXX` |
| `email` | text | Login email |
| `license_number` | text | Medical license number |
| `registration_id` | text | Government registration ID |
| `city`, `state` | text | Location |
| `latitude`, `longitude` | float | GPS coordinates for geospatial clustering |
| `patient_cases` | int | Total case count |
| `local_accuracy` | float | Last training accuracy |
| `privacy_score` | float | Computed privacy score |
| `epsilon_used` | float | e used in last training round |
| `rounds_participated` | int | Number of FL rounds joined |
| `government_approved` | bool | Admin approval status |
| `is_credential_valid` | bool | Active credential status |
| `credential_hash` | text | SHA-256 of issued credential |
| `credential_issued_at` | timestamp | Credential issue time |
| `credential_expires_at` | timestamp | Credential expiry (1 year from issue) |
| `credential_metadata` | jsonb | Full W3C credential object |
| `last_active` | timestamp | Last training timestamp |

### `training_history`
| Column | Type | Description |
|--------|------|-------------|
| `hospital_id` | uuid FK | Reference to hospitals |
| `round_number` | int | FL aggregation round |
| `accuracy` | float | Local model accuracy |
| `epsilon_used` | float | e for this round |
| `data_size` | int | Number of samples used (capped at 512) |
| `created_at` | timestamp | Auto-set by Supabase |

### `blockchain_audit`
| Column | Type | Description |
|--------|------|-------------|
| `round_number` | int | FL round number at event time |
| `hospital_id` | text | Hospital that triggered the event |
| `hospital_name` | text | Hospital display name |
| `event_type` | text | `UPLOAD`, `TRAIN`, or `CREDENTIAL_ISSUE` |
| `epsilon_used` | float | e used (0.0 for non-training events) |
| `model_hash` | text | SHA-256 of model weights or credential |
| `metadata` | jsonb | Event-specific payload |
| `previous_hash` | text | Previous block hash (genesis = `"GENESIS"`) |
| `current_hash` | text | SHA-256 of this block chained to previous |
| `created_at` | timestamp | Event timestamp (UTC) |

### `admins`
| Column | Type | Description |
|--------|------|-------------|
| `id` | uuid PK | Matches Supabase auth user ID |
| `email` | text | Admin login email |

---

## ?? Hospital Client SDK

Use `clients/client_template.py` as a starting point for hospital-side integration:

```python
SERVER_URL = "http://localhost:8000"
HOSPITAL_EMAIL = "hospital@example.com"
HOSPITAL_PASSWORD = "your_password"

# 1. Login to get JWT token
token, user_id = login()

# 2. Trigger server-side training with your credential hash
import requests
r = requests.post(f"{SERVER_URL}/api/hospital/train", data={
    "credential_hash": "YOUR_CREDENTIAL_HASH",   # From admin approval
    "epochs": 5,
    "epsilon": 1.0
}, headers={"Authorization": f"Bearer {token}"})
print(r.json())
# {"success": true, "accuracy": 0.87, "privacy_score": 0.33, ...}
```

---

*Built for privacy-preserving healthcare AI. FL-Health  where data stays local, and only learning travels.*
