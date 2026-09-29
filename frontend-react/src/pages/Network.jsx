import React, { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import styles from './Learn.module.css';
import { API_URL } from '../config';

export default function Network() {
  const [stats, setStats] = useState(null);
  const [alerts, setAlerts] = useState(null);

  useEffect(() => {
    const loadLiveStats = async () => {
      try {
        const res = await fetch(`${API_URL}/api/public/fl-status`);
        const data = await res.json();
        setStats(data);
      } catch (e) { console.warn("Live stats unavailable"); }
    };

    const loadEarlyDetection = async () => {
      try {
        const res = await fetch(`${API_URL}/api/geospatial/early-alerts`);
        const data = await res.json();
        setAlerts(data);
      } catch (e) { console.warn("Alerts unavailable"); }
    };

    loadLiveStats();
    loadEarlyDetection();
    const interval = setInterval(loadLiveStats, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 50%, #7dd3fc 100%)', color: '#0c4a6e' }}>
      <Navbar />

      <section className={styles.hero}>
        <div className={styles.heroBadge}>🤝 Chapter 3 of 3</div>
        <h1>Join the <span className={styles.accent}>Network</span></h1>
        <p>
          Understand how adaptive privacy and data exchange work — then register your hospital
          and start collaborating with the federated network.
        </p>
      </section>

      <div className={styles.liveBar}>
        <div className={styles.liveStat}>
          <div className={styles.val}>{stats ? `R${stats.current_round}` : '—'}</div>
          <div className={styles.lbl}>FL Round</div>
          <div className={styles.roundBar}>
            <div className={styles.roundFill} style={{ width: `${stats ? stats.round_progress_pct : 0}%` }}></div>
          </div>
        </div>
        <div className={styles.liveStat}>
          <div className={styles.val}>{stats ? stats.approved_hospitals : '—'}</div>
          <div className={styles.lbl}>Hospitals</div>
        </div>
        <div className={styles.liveStat}>
          <div className={styles.val}>{stats ? stats.active_last_24h : '—'}</div>
          <div className={styles.lbl}>Active (24h)</div>
        </div>
        <div className={styles.liveStat}>
          <div className={styles.val}>{stats && stats.avg_accuracy > 0 ? `${stats.avg_accuracy}%` : '—'}</div>
          <div className={styles.lbl}>Avg Accuracy</div>
        </div>
        <div className={styles.liveStat}>
          <div className={styles.val}>{stats ? `ε=${stats.privacy_budget}` : 'ε=1.0'}</div>
          <div className={styles.lbl}>Privacy Budget</div>
        </div>
        <div className={styles.liveStat}>
          <div className={styles.val}>{stats ? stats.dropout_tolerance : '30%+'}</div>
          <div className={styles.lbl}>Dropout Tolerance</div>
        </div>
      </div>

      <div className={styles.progress}>
        <div className={styles.progressDot}></div>
        <div className={styles.progressDot}></div>
        <div className={`${styles.progressDot} ${styles.active}`}></div>
      </div>

      <div className={styles.container}>
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Section 5</div>
          <h2>Adaptive Privacy — Not All Hospitals Are Equal</h2>
          <p>
            Not every hospital has the same quality of data. Some have larger patient populations,
            better labeled records, or more balanced disease distributions.
          </p>
          <p>
            Instead of giving everyone the same noise level, we <strong>adapt the privacy budget
            per hospital</strong> based on their data quality:
          </p>

          <table className={styles.qualityTable}>
            <thead>
              <tr>
                <th>Hospital</th>
                <th>Data Size</th>
                <th>Quality Score</th>
                <th>ε Budget</th>
                <th>Effect</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Hospital A</td>
                <td>1,000 patients</td>
                <td>0.95 (excellent)</td>
                <td>0.95</td>
                <td>Less noise → higher accuracy</td>
              </tr>
              <tr>
                <td>Hospital B</td>
                <td>500 patients</td>
                <td>0.68 (medium)</td>
                <td>0.68</td>
                <td>Moderate noise</td>
              </tr>
              <tr>
                <td>Hospital C</td>
                <td>250 patients</td>
                <td>0.42 (low)</td>
                <td>0.42</td>
                <td>More noise → stronger privacy</td>
              </tr>
            </tbody>
          </table>

          <div className={styles.analogyBox}>
            <h4>🎯 Why This Matters</h4>
            <p>
              A hospital with 1,000 well-labeled patients deserves less noise — its data is
              reliable. A small clinic with 250 patients deserves more noise — its data is
              sparse. This way, <strong>better data contributes more to the model</strong>
              while weaker data is protected more heavily.
            </p>
          </div>
        </div>

        <div className={styles.section}>
          <div className={styles.sectionLabel}>Section 6</div>
          <h2>What Actually Travels?</h2>
          <p>Confusion often arises about what "sharing" means. Here is exactly what happens:</p>

          <div className={styles.analogyGrid}>
            <div className={`${styles.analogyCard} ${styles.bad}`}>
              <h4>❌ What Never Travels</h4>
              <ul>
                <li>Patient names or IDs</li>
                <li>Medical history details</li>
                <li>Lab report values</li>
                <li>X-ray or ECG files</li>
                <li>Any raw patient record</li>
              </ul>
            </div>
            <div className={`${styles.analogyCard} ${styles.good}`}>
              <h4>✅ What Travels</h4>
              <ul>
                <li>Model weights (math arrays)</li>
                <li>Noise-protected weights</li>
                <li>Accuracy metric (a number)</li>
                <li>Data size count (a number)</li>
                <li>Training round number</li>
              </ul>
            </div>
          </div>

          <div className={styles.analogyBox}>
            <h4>🔑 The Bottom Line</h4>
            <p>
              Think of it this way: the AI <em>learns patterns</em> from data — patterns like
              "high glucose correlates with diabetes." It stores those patterns as numbers.
              We share only the <strong>patterns</strong>, never the raw <strong>data</strong>.
              You can't reverse-engineer a patient from a weight array.
            </p>
          </div>
        </div>

        {alerts && (alerts.early_alerts?.length > 0 || alerts.early_detection?.["7day_growth_pct"] > 0) && (
          <div className={styles.detectionPanel}>
            <h3>🚨 7-21 Day Early Detection Alert</h3>
            <p>
              Alert Level: <strong style={{ color: alerts.alert_level === 'RED' ? '#dc2626' : alerts.alert_level === 'YELLOW' ? '#d97706' : '#16a34a' }}>
                {alerts.alert_level || 'GREEN'}
              </strong> · Detection window: {alerts.detection_window} · {alerts.early_alerts?.length || 0} hospital(s) with recent activity
            </p>
            <div className={styles.detectionGrid}>
              <div className={styles.detectionCard}>
                <div className={styles.dVal}>{(alerts.early_detection?.["7day_growth_pct"] || 0)}%</div>
                <div className={styles.dLbl}>7-Day Growth</div>
              </div>
              <div className={styles.detectionCard}>
                <div className={styles.dVal}>{(alerts.early_detection?.["14day_growth_pct"] || 0)}%</div>
                <div className={styles.dLbl}>14-Day Growth</div>
              </div>
              <div className={styles.detectionCard}>
                <div className={styles.dVal}>{(alerts.early_detection?.["21day_growth_pct"] || 0)}%</div>
                <div className={styles.dLbl}>21-Day Growth</div>
              </div>
            </div>
          </div>
        )}

        <div className={styles.ctaBox}>
          <h2>Ready to join the network?</h2>
          <p>Register your hospital and start training AI that respects patient privacy.</p>
          <Link to="/register" className={styles.btnWhite}>🏥 Register Hospital</Link>
        </div>
      </div>

      <div className={styles.pageNav}>
        <Link to="/privacy" className={styles.pageNavBtn}>← Back: Privacy</Link>
        <Link to="/register" className={styles.pageNavBtn} style={{ background: 'linear-gradient(135deg, #0284c7, #38bdf8)', color: 'white' }}>Register Hospital →</Link>
      </div>

      <footer className={styles.footer}>
        <strong>FL-Health</strong> · Data stays local. Only learning travels.
      </footer>
    </div>
  );
}
