import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import styles from './Login.module.css';
import { API_URL } from '../config';

export default function Login() {
  const [currentTab, setCurrentTab] = useState('hospital');
  const [showPassword, setShowPassword] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(false);
  const [alert, setAlert] = useState({ show: false, message: '', type: '' });
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();

  const showAlert = (message, type) => {
    setAlert({ show: true, message, type });
    setTimeout(() => setAlert({ show: false, message: '', type: '' }), 5000);
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const res = await fetch(`${API_URL}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password })
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Login failed");

      const token = data.access_token;
      const userId = data.user.id;
      console.log('[Login] Auth succeeded, user:', userId, '| checking role...');

      // Determine role by probing both endpoints so the user doesn't need to
      // pick the right tab manually. We check the selected tab first and fall
      // back gracefully with a helpful error.
      const [adminCheck, hospitalCheck] = await Promise.all([
        fetch(`${API_URL}/api/admin/all-hospitals`, {
          headers: { "Authorization": `Bearer ${token}` }
        }),
        fetch(`${API_URL}/api/hospital/me`, {
          headers: { "Authorization": `Bearer ${token}` }
        })
      ]);

      const isAdmin = adminCheck.ok;
      const isHospital = hospitalCheck.ok;
      console.log('[Login] Role check — isAdmin:', isAdmin, '(status:', adminCheck.status, ') | isHospital:', isHospital, '(status:', hospitalCheck.status, ') | selectedTab:', currentTab);

      let detectedRole = null;
      if (currentTab === "admin" && isAdmin) {
        detectedRole = "admin";
      } else if (currentTab === "hospital" && isHospital) {
        detectedRole = "hospital";
      } else if (isAdmin) {
        // User selected "hospital" tab but they're actually an admin
        throw new Error("This is an admin account. Please select the 🔐 Admin tab and try again.");
      } else if (isHospital) {
        // User selected "admin" tab but they're actually a hospital
        throw new Error("This is a hospital account. Please select the 🏥 Hospital tab and try again.");
      } else {
        // Neither check passed — log what the backend actually said
        let adminErr = '', hospitalErr = '';
        try { adminErr = await adminCheck.text(); } catch {}
        try { hospitalErr = await hospitalCheck.text(); } catch {}
        console.error('[Login] Both role checks failed:', { adminErr, hospitalErr });
        throw new Error("Role verification failed. Please check your credentials or contact support.");
      }

      if (rememberMe) {
        localStorage.setItem("fl_token", token);
        localStorage.setItem("fl_user", userId);
        localStorage.setItem("fl_role", detectedRole);
        sessionStorage.removeItem("fl_token");
        sessionStorage.removeItem("fl_user");
        sessionStorage.removeItem("fl_role");
      } else {
        sessionStorage.setItem("fl_token", token);
        sessionStorage.setItem("fl_user", userId);
        sessionStorage.setItem("fl_role", detectedRole);
        localStorage.removeItem("fl_token");
        localStorage.removeItem("fl_user");
        localStorage.removeItem("fl_role");
      }
      
      console.log('[Login] Stored — role:', detectedRole, '| storage:', rememberMe ? 'localStorage' : 'sessionStorage');

      showAlert("Login successful! Redirecting...", "success");
      setTimeout(() => {
        navigate(detectedRole === "admin" ? "/admin" : "/dashboard");
      }, 800);
    } catch (err) {
      showAlert(err.message || "Login failed.", "error");
      setIsLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', background: 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 50%, #7dd3fc 100%)' }}>
      <Navbar />
      <div className={styles.loginContainer}>
        <div className={styles.loginWrapper}>
          <div className={styles.logoSection}>
            <div className={styles.logoIcon}>🏥</div>
            <h1>Welcome Back</h1>
            <p>Sign in to your FL-Health account</p>
          </div>

          <div className={styles.tabs}>
            <div 
              className={`${styles.tab} ${currentTab === 'hospital' ? styles.active : ''}`}
              onClick={() => setCurrentTab('hospital')}
            >
              🏥 Hospital
            </div>
            <div 
              className={`${styles.tab} ${currentTab === 'admin' ? styles.active : ''}`}
              onClick={() => setCurrentTab('admin')}
            >
              🔐 Admin
            </div>
          </div>

          {alert.show && (
            <div className={`${styles.alert} ${styles[alert.type]}`}>
              {alert.message}
            </div>
          )}

          <form onSubmit={handleLogin}>
            <div className={styles.formGroup}>
              <label>Email Address</label>
              <div className={styles.inputWrapper}>
                <span className={styles.inputIcon}>📧</span>
                <input 
                  type="email" 
                  placeholder={currentTab === 'hospital' ? "hospital@example.com" : "admin@fl-health.com"}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required 
                />
              </div>
            </div>

            <div className={styles.formGroup}>
              <label>Password</label>
              <div className={styles.inputWrapper}>
                <span className={styles.inputIcon}>🔒</span>
                <input 
                  type={showPassword ? "text" : "password"} 
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required 
                />
                <button 
                  type="button" 
                  className={styles.passwordToggle} 
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? "🙈" : "👁️"}
                </button>
              </div>
            </div>

            <div className={styles.formExtras}>
              <label className={styles.remember}>
                <input 
                  type="checkbox" 
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                />
                <span>Remember me</span>
              </label>
              <a href="#" className={styles.forgotLink}>Forgot password?</a>
            </div>

            <button type="submit" className={styles.btnLogin} disabled={isLoading}>
              {isLoading ? "Signing in..." : "Sign In"}
            </button>
          </form>

          <div className={styles.footerLink}>
            Don't have an account? <Link to="/register">Register Hospital</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
