import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import styles from './Register.module.css';
import { API_URL } from '../config';

export default function Register() {
  const [showPassword1, setShowPassword1] = useState(false);
  const [showPassword2, setShowPassword2] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [alert, setAlert] = useState({ show: false, message: '', type: '' });
  const navigate = useNavigate();

  const [formData, setFormData] = useState({
    hospitalName: '', licenseNumber: '', registrationId: '',
    city: '', state: '', latitude: '', longitude: '',
    email: '', password: '', confirmPassword: ''
  });

  const showAlert = (message, type) => {
    setAlert({ show: true, message, type });
    setTimeout(() => setAlert({ show: false, message: '', type: '' }), 6000);
  };

  const handleChange = (e) => setFormData({ ...formData, [e.target.id]: e.target.value });

  const detectLocation = () => {
    if (!navigator.geolocation) {
      showAlert("Geolocation not supported.", "error");
      return;
    }
    showAlert("📍 Detecting location...", "success");
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setFormData(prev => ({
          ...prev,
          latitude: pos.coords.latitude.toFixed(4),
          longitude: pos.coords.longitude.toFixed(4)
        }));
        showAlert("✅ Location detected! Please enter City and State.", "success");
      },
      () => showAlert("Could not detect location.", "error"),
      { timeout: 10000 }
    );
  };

  const handleRegister = async (e) => {
    e.preventDefault();
    if (formData.password !== formData.confirmPassword) {
      showAlert("Passwords do not match.", "error");
      return;
    }
    if (formData.password.length < 6) {
      showAlert("Password must be at least 6 characters.", "error");
      return;
    }

    setIsLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          hospital_name: formData.hospitalName.trim(),
          email: formData.email.trim(),
          password: formData.password,
          license_number: formData.licenseNumber.trim(),
          registration_id: formData.registrationId.trim(),
          city: formData.city.trim(),
          state: formData.state.trim(),
          latitude: parseFloat(formData.latitude) || 0,
          longitude: parseFloat(formData.longitude) || 0
        })
      });

      const result = await res.json();
      if (!res.ok) throw new Error(result.detail || "Registration failed");

      showAlert("✅ Registration successful! Awaiting admin approval.", "success");
      setTimeout(() => { navigate('/login'); }, 3000);
    } catch (err) {
      showAlert(err.message || "Registration failed.", "error");
      setIsLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', background: 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 50%, #7dd3fc 100%)' }}>
      <Navbar />
      <div className={styles.container}>
        <div className={styles.registerWrapper}>
          <div className={styles.logoSection}>
            <div className={styles.logoIcon}>🏥</div>
            <h1>Register Your Hospital</h1>
            <p>Join the FL-Health federated network</p>
          </div>

          {alert.show && (
            <div className={`${styles.alert} ${styles[alert.type]}`}>
              {alert.message}
            </div>
          )}

          <form onSubmit={handleRegister}>
            <div className={styles.sectionLabel}>🏥 Hospital Details</div>
            
            <div className={styles.formGroup}>
              <label>Hospital Name <span className={styles.required}>*</span></label>
              <div className={styles.inputWrapper}>
                <span className={styles.inputIcon}>🏢</span>
                <input type="text" id="hospitalName" value={formData.hospitalName} onChange={handleChange} placeholder="e.g., City General Hospital" required />
              </div>
            </div>

            <div className={styles.row}>
              <div className={styles.formGroup}>
                <label>License Number <span className={styles.required}>*</span></label>
                <div className={styles.inputWrapper}>
                  <span className={styles.inputIcon}>📋</span>
                  <input type="text" id="licenseNumber" value={formData.licenseNumber} onChange={handleChange} placeholder="LIC-2026-001" required />
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>Registration ID <span className={styles.required}>*</span></label>
                <div className={styles.inputWrapper}>
                  <span className={styles.inputIcon}>🔖</span>
                  <input type="text" id="registrationId" value={formData.registrationId} onChange={handleChange} placeholder="REG-2026-001" required />
                </div>
              </div>
            </div>

            <div className={styles.sectionLabel}>📍 Location (for outbreak map)</div>
            
            <div className={styles.row}>
              <div className={styles.formGroup}>
                <label>City <span className={styles.required}>*</span></label>
                <div className={styles.inputWrapper}>
                  <span className={styles.inputIcon}>🌆</span>
                  <input type="text" id="city" value={formData.city} onChange={handleChange} placeholder="e.g., Bangalore" required />
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>State <span className={styles.required}>*</span></label>
                <div className={styles.inputWrapper}>
                  <span className={styles.inputIcon}>🗺️</span>
                  <input type="text" id="state" value={formData.state} onChange={handleChange} placeholder="e.g., Karnataka" required />
                </div>
              </div>
            </div>

            <div className={styles.row}>
              <div className={styles.formGroup}>
                <label>Latitude</label>
                <div className={styles.inputWrapper}>
                  <span className={styles.inputIcon}>🧭</span>
                  <input type="number" id="latitude" step="0.0001" value={formData.latitude} onChange={handleChange} placeholder="12.9716" />
                </div>
              </div>
              <div className={styles.formGroup}>
                <label>Longitude</label>
                <div className={styles.inputWrapper}>
                  <span className={styles.inputIcon}>🧭</span>
                  <input type="number" id="longitude" step="0.0001" value={formData.longitude} onChange={handleChange} placeholder="77.5946" />
                </div>
              </div>
            </div>

            <button type="button" className={styles.btnDetect} onClick={detectLocation}>
              📍 Auto-detect my location
            </button>

            <div className={styles.sectionLabel}>🔐 Account Details</div>
            
            <div className={styles.formGroup}>
              <label>Official Email <span className={styles.required}>*</span></label>
              <div className={styles.inputWrapper}>
                <span className={styles.inputIcon}>📧</span>
                <input type="email" id="email" value={formData.email} onChange={handleChange} placeholder="hospital@example.com" required />
              </div>
            </div>

            <div className={styles.formGroup}>
              <label>Password <span className={styles.required}>*</span></label>
              <div className={styles.inputWrapper}>
                <span className={styles.inputIcon}>🔒</span>
                <input type={showPassword1 ? "text" : "password"} id="password" value={formData.password} onChange={handleChange} placeholder="Minimum 6 characters" required />
                <button type="button" className={styles.passwordToggle} onClick={() => setShowPassword1(!showPassword1)}>
                  {showPassword1 ? "🙈" : "👁️"}
                </button>
              </div>
            </div>

            <div className={styles.formGroup}>
              <label>Confirm Password <span className={styles.required}>*</span></label>
              <div className={styles.inputWrapper}>
                <span className={styles.inputIcon}>🔒</span>
                <input type={showPassword2 ? "text" : "password"} id="confirmPassword" value={formData.confirmPassword} onChange={handleChange} placeholder="Re-enter password" required />
                <button type="button" className={styles.passwordToggle} onClick={() => setShowPassword2(!showPassword2)}>
                  {showPassword2 ? "🙈" : "👁️"}
                </button>
              </div>
            </div>

            <div className={styles.infoBox}>
              <strong>ℹ️ What happens next?</strong><br />
              After registration, our admin will verify your hospital license. Once approved, you'll receive a <strong>Verifiable Credential</strong> and can begin federated training.
            </div>

            <label className={styles.terms}>
              <input type="checkbox" required />
              <span>I confirm the information provided is accurate and agree to the <Link to="#">Terms</Link> and <Link to="#">Privacy Policy</Link>.</span>
            </label>

            <button type="submit" className={styles.btnRegister} disabled={isLoading}>
              {isLoading ? "Registering..." : "Register Hospital"}
            </button>
          </form>

          <div className={styles.footerLink}>
            Already have an account? <Link to="/login">Sign In</Link>
          </div>
        </div>
      </div>
    </div>
  );
}
