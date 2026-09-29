import React from 'react';
import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import styles from './Learn.module.css';

export default function Privacy() {
  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 50%, #7dd3fc 100%)', color: '#0c4a6e' }}>
      <Navbar />

      <section className={styles.hero}>
        <div className={styles.heroBadge}>🔐 Chapter 2 of 3</div>
        <h1>Why Privacy <span className={styles.accent}>Matters</span></h1>
        <p>
          Understand why centralized AI fails for healthcare — and how Differential Privacy
          protects patient data even when model weights travel.
        </p>
      </section>

      <div className={styles.progress}>
        <div className={styles.progressDot}></div>
        <div className={`${styles.progressDot} ${styles.active}`}></div>
        <div className={styles.progressDot}></div>
      </div>

      <div className={styles.container}>
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Section 3</div>
          <h2>Why Not Just Use Normal AI?</h2>
          <p>
            Traditional centralized AI would require all hospitals to send their patient data
            to one server. That creates serious problems:
          </p>

          <img src="/assets/images/Privacy-Preserving Analogy.png" alt="Locked Data Vault Analogy" className={styles.sectionImage} />

          <div className={styles.analogyGrid}>
            <div className={`${styles.analogyCard} ${styles.bad}`}>
              <h4>❌ Centralized AI</h4>
              <p style={{ fontSize: '14px', color: '#64748b' }}>All data goes to one server.</p>
              <ul>
                <li>Violates HIPAA & GDPR</li>
                <li>Single point of breach</li>
                <li>Patients lose control</li>
                <li>Hospitals refuse to participate</li>
              </ul>
            </div>
            <div className={`${styles.analogyCard} ${styles.good}`}>
              <h4>✅ Federated Learning</h4>
              <p style={{ fontSize: '14px', color: '#64748b' }}>Only weights travel — never data.</p>
              <ul>
                <li>100% HIPAA & GDPR compliant</li>
                <li>Data stays inside each hospital</li>
                <li>Patients keep full control</li>
                <li>Hospitals willingly collaborate</li>
              </ul>
            </div>
          </div>

          <div className={styles.analogyBox}>
            <h4>🏥 Real-World Example</h4>
            <p>
              In 2015, the Anthem data breach exposed <strong>78.8 million patient records</strong>
              in a single attack on a centralized database. With federated learning, that attack
              would have been impossible — no central database exists to breach.
            </p>
          </div>
        </div>

        <div className={styles.section}>
          <div className={styles.sectionLabel}>Section 4</div>
          <h2>Privacy Budget — How We Protect Data</h2>
          <p>
            Even with Federated Learning, weights can theoretically leak patient info.
            To prevent this, we add <strong>mathematical noise</strong> to the weights before
            sending them — a technique called <strong>Differential Privacy</strong>.
          </p>
          <p>
            The amount of noise is controlled by a <strong>privacy budget (ε)</strong>.
            Lower ε = more noise = stronger privacy, but less accuracy.
          </p>

          <img src="/assets/images/Privacy Budget Explanation.png" alt="Privacy Budget Scale" className={styles.sectionImage} />

          <div className={styles.analogyBox}>
            <h4>📊 Why ε = 1.0?</h4>
            <p>
              We chose <strong>ε = 1.0</strong> because it sits at the perfect balance — strong
              privacy (mathematically proven) while keeping accuracy high enough for clinical
              decision support. Lower ε values protect more but degrade accuracy too much.
              Higher ε values are less safe. ε = 1.0 is the industry standard for healthcare FL.
            </p>
          </div>
        </div>
      </div>

      <div className={styles.pageNav}>
        <Link to="/about" className={styles.pageNavBtn}>← Back: Learn FL</Link>
        <Link to="/network" className={`${styles.pageNavBtn} ${styles.pageNavBtnPrimary}`}>Next: Join →</Link>
      </div>

      <footer className={styles.footer}>
        <strong>FL-Health</strong> · Data stays local. Only learning travels.
      </footer>
    </div>
  );
}
