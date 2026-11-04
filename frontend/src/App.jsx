import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from './components/layout/AppShell'
import { ErrorState, LoadingState } from './components/ui/StateViews'
import { AuthProvider, useAuth } from './context/AuthContext'
import { SystemProvider, useSystem } from './context/SystemContext'
import AuditLogs from './pages/AuditLogs'
import Dashboard from './pages/Dashboard'
import Explainability from './pages/Explainability'
import FederatedLearning from './pages/FederatedLearning'
import Forecasting from './pages/Forecasting'
import HospitalDetail from './pages/HospitalDetail'
import HowItWorks from './pages/HowItWorks'
import Hospitals from './pages/Hospitals'
import Login from './pages/Login'
import ModelDetail from './pages/ModelDetail'
import Models from './pages/Models'
import MyHospital from './pages/MyHospital'
import NotFound from './pages/NotFound'
import SettingsPage from './pages/Settings'
import Surveillance from './pages/Surveillance'
import { homePathFor } from './utils/constants'

/** Blocks the app until the server's public configuration is known. */
function SystemGate({ children }) {
  const { status, error, reload } = useSystem()
  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingState label="Connecting to PrivaFuse" />
      </div>
    )
  }
  if (status === 'error') {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <ErrorState error={error} what="the server configuration" onRetry={reload} />
      </div>
    )
  }
  return children
}

/** Only signed-in users get past this point; everyone else is sent to the sign-in page. */
function RequireAuth({ children }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <LoadingState label="Checking your session" />
      </div>
    )
  }
  if (status !== 'signedIn') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

/** The dashboard, except for roles whose home page is elsewhere (health officers have no dashboard access). */
function Home() {
  const { user } = useAuth()
  const home = homePathFor(user)
  return home === '/' || home === '/my-hospital' ? <Dashboard /> : <Navigate to={home} replace />
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<Home />} />
        <Route path="my-hospital" element={<MyHospital />} />
        <Route path="hospitals" element={<Hospitals />} />
        <Route path="hospitals/:hospitalId" element={<HospitalDetail />} />
        <Route path="federated" element={<FederatedLearning />} />
        <Route path="models" element={<Models />} />
        <Route path="models/:modelId" element={<ModelDetail />} />
        <Route path="surveillance" element={<Surveillance />} />
        <Route path="forecasting" element={<Forecasting />} />
        <Route path="explainability" element={<Explainability />} />
        <Route path="audit" element={<AuditLogs />} />
        <Route path="how-it-works" element={<HowItWorks />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <SystemProvider>
        <SystemGate>
          <AuthProvider>
            <AppRoutes />
          </AuthProvider>
        </SystemGate>
      </SystemProvider>
    </BrowserRouter>
  )
}
