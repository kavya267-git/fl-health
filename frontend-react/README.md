# FL-Health React Frontend

This directory contains the modernized React + Vite frontend for the FL-Health Federated Learning platform.

## 🚀 Architecture

The application was built using a modular component architecture:

*   **Vite & React 19:** Lightning-fast HMR and build tools.
*   **CSS Modules:** Scoped, highly-maintainable styling (e.g., `Home.module.css`).
*   **React Router:** Client-side routing for instantaneous page transitions.
*   **Chart.js & React-Leaflet:** Complex data visualization for training convergence, privacy budgets, and geospatial outbreak tracking.

## 📁 Directory Structure

```
src/
├── components/          # Reusable UI components
│   ├── dashboard/       # Specialized charts and maps for the hospital dashboard
│   └── Navbar.jsx       # Global responsive navigation
├── pages/               # Top-level route components (Home, Dashboard, Admin)
├── config.js            # Environment variables and API URL
├── main.jsx             # React entry point and Chart.js global defaults
└── index.css            # Global CSS resets and map styling overrides
```

## 💻 Local Development

1.  **Install Dependencies:**
    ```bash
    npm install
    ```
2.  **Run Development Server:**
    ```bash
    npm run dev
    ```
    The server will start at `http://localhost:5173`.

3.  **Configure API Connection:**
    By default, the frontend expects the Python backend to be running at `http://localhost:8000`. You can change this in `src/config.js` or via `.env` variables if configured.

## 🛠 Production Build

To test the production build locally:

```bash
npm run build
npm start
```
*(Note: `npm start` uses the `serve` library to correctly handle SPA routing).*
