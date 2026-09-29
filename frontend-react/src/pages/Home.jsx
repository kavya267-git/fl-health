import React from 'react';
import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import styles from './Home.module.css';

export default function Home() {
  return (
    <div className={styles.homeWrapper}>
      <Navbar />
      
      <section className={styles.hero}>
        <div className={styles.heroText}>
            <h1>Healthcare AI that<br/><span className={styles.accent}>never moves patient data</span></h1>
            <p>
                FL-Health enables hospitals to train disease prediction models together —
                without ever sharing patient records. Each hospital trains locally.
                Only encrypted model updates travel.
            </p>
            <div className={styles.heroQuote}>"Data stays local. Only learning travels."</div>
            <div className={styles.heroCta}>
                <Link to="/register" className={styles.btnPrimary}>🏥 Register Your Hospital</Link>
                <Link to="/about" className={styles.btnSecondary}>📚 Learn How It Works</Link>
            </div>
        </div>
          <div className={styles.heroImage}>
            <img src="/assets/images/Hero Illustration for Home Page.png" alt="Federated Learning Hero" />
          </div>
        </section>

        <section className={styles.features}>
          <h2 className={styles.featuresTitle}>6 Integrated Modules</h2>
          <p className={styles.featuresSubtitle}>Every module works together to deliver privacy-preserving collaborative learning</p>

          <div className={styles.featureGrid}>
            <div className={styles.featureCard}>
              <div className={styles.featureIcon}>🧠</div>
              <h3>Multi-Modal Federated Learning</h3>
              <p>Combines EHR, ECG, and medical images. Each hospital trains locally using FedAvg aggregation.</p>
            </div>
            <div className={styles.featureCard}>
              <div className={styles.featureIcon}>🔐</div>
              <h3>Adaptive Differential Privacy</h3>
              <p>Quality-based noise allocation. Better data gets less noise, weaker data gets more protection. ε = 1.0.</p>
            </div>
            <div className={styles.featureCard}>
              <div className={styles.featureIcon}>🛡️</div>
              <h3>Dynamic Masking & Recovery</h3>
              <p>Hospitals can disconnect mid-training. KNN imputation keeps the network learning without restarts.</p>
            </div>
            <div className={styles.featureCard}>
              <div className={styles.featureIcon}>⛓️</div>
              <h3>Blockchain Audit Trail</h3>
              <p>Every training round is logged immutably with SHA-256 chain linking. HIPAA and GDPR ready.</p>
            </div>
            <div className={styles.featureCard}>
              <div className={styles.featureIcon}>🗺️</div>
              <h3>Geospatial Disease Surveillance</h3>
              <p>K-means clustering detects disease hotspots. Ensemble forecasting gives 7-21 day early warning.</p>
            </div>
            <div className={styles.featureCard}>
              <div className={styles.featureIcon}>📊</div>
              <h3>Real-Time Dashboard</h3>
              <p>SHAP explainability, privacy budget tracking, accuracy charts, and outbreak forecasts — all live.</p>
            </div>
          </div>
        </section>

        <section className={styles.mapPreview}>
          <div className={styles.mapPreviewCard}>
            <div className={styles.mapPreviewText}>
              <div className={styles.tag}>Live Outbreak Detection</div>
              <h2>Real-Time Disease Surveillance</h2>
              <p>
                Hospitals across India report disease case counts to the federated network.
                Our geospatial engine clusters this data by location — detecting hotspots
                and predicting outbreaks 2-4 weeks before they peak.
              </p>
              <p>
                No individual patient data is exposed. Only aggregate counts and model weights travel.
              </p>
            </div>
            <div className={styles.mapPreviewImg}>
              <img src="/assets/images/Disease Outbreak Map Illustration.png" alt="Disease Outbreak Map of India" />
            </div>
          </div>
        </section>

        <section className={styles.ctaFinal}>
          <h2>Ready to join the network?</h2>
          <p>Register your hospital today and start training AI that respects patient privacy by design.</p>
          <Link to="/register" className={styles.btnPrimary} style={{ display: 'inline-flex' }}>🏥 Register Hospital</Link>
        </section>

        <footer className={styles.footer}>
          <strong>FL-Health</strong> · Federated Learning Based Privacy-Preserving Healthcare System<br />
          Data stays local. Only learning travels.
        </footer>
    </div>
  );
}
