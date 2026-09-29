import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import styles from './Dashboard.module.css';
import { API_URL } from '../config';

import ConvergenceChart from '../components/dashboard/ConvergenceChart';
import PrivacyGauge from '../components/dashboard/PrivacyGauge';
import ForecastChart from '../components/dashboard/ForecastChart';
import DiseaseMap from '../components/dashboard/DiseaseMap';
import FeatureImportance from '../components/dashboard/FeatureImportance';
import HospitalStatus from '../components/dashboard/HospitalStatus';
import ClusterList from '../components/dashboard/ClusterList';
import DatasetInfo from '../components/dashboard/DatasetInfo';
import UploadHistory from '../components/dashboard/UploadHistory';
import TrainingHistory from '../components/dashboard/TrainingHistory';

export default function Dashboard() {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const [hospitalId, setHospitalId] = useState('');
  const [role, setRole] = useState('');
  const [token, setToken] = useState('');
  const [credentialHash, setCredentialHash] = useState(null);

  const [status, setStatus] = useState(null);
  const [convergenceHistory, setConvergenceHistory] = useState([]);
  const [privacyBudget, setPrivacyBudget] = useState({ used: 0, budget: 1.0 });
  const [geospatial, setGeospatial] = useState(null);
  const [auditTrail, setAuditTrail] = useState([]);
  const [hospitals, setHospitals] = useState([]);
  
  const [datasetInfo, setDatasetInfo] = useState(null);
  const [uploadHistory, setUploadHistory] = useState([]);
  const [trainingHistory, setTrainingHistory] = useState([]);

  const [isUploading, setIsUploading] = useState(false);
  const [isTraining, setIsTraining] = useState(false);
  const [actionMessage, setActionMessage] = useState({ text: '', type: '' });
  const [trainMessage, setTrainMessage] = useState({ text: 'Ensure your data is uploaded first. Keep epochs low (2-3) on free hosting.', type: '' });
  const [epochs, setEpochs] = useState(3);
  const [epsilon, setEpsilon] = useState(1.0);

  useEffect(() => {
    const savedToken = localStorage.getItem('fl_token') || sessionStorage.getItem('fl_token');
    const savedRole = localStorage.getItem('fl_role') || sessionStorage.getItem('fl_role');
    const savedId = localStorage.getItem('fl_user') || sessionStorage.getItem('fl_user');

    if (!savedToken) {
      navigate('/login');
      return;
    }

    setToken(savedToken);
    setRole(savedRole);
    setHospitalId(savedId);
  }, [navigate]);

  useEffect(() => {
    if (!token) return;

    const loadHospitalCredentials = async () => {
      if (role !== 'hospital') return;
      try {
        const res = await fetch(`${API_URL}/api/hospital/me`, { headers: { "Authorization": `Bearer ${token}` } });
        if (res.ok) {
          const data = await res.json();
          setCredentialHash(data.hospital?.credential_hash);
          if (!data.hospital?.credential_hash) {
            setTrainMessage({ text: '⚠️ Awaiting admin approval.', type: 'error' });
          }
        }
      } catch (e) { console.error(e); }
    };

    const fetchHospitalData = async () => {
      if (role !== 'hospital') return;
      try {
        const [dsRes, uhRes, thRes] = await Promise.all([
          fetch(`${API_URL}/api/hospital/dataset-info`, { headers: { 'Authorization': `Bearer ${token}` } }),
          fetch(`${API_URL}/api/hospital/uploads`, { headers: { 'Authorization': `Bearer ${token}` } }),
          fetch(`${API_URL}/api/hospital/history`, { headers: { 'Authorization': `Bearer ${token}` } })
        ]);
        
        if (dsRes.ok) setDatasetInfo(await dsRes.json());
        if (uhRes.ok) { const uhData = await uhRes.json(); setUploadHistory(uhData.uploads || []); }
        if (thRes.ok) { const thData = await thRes.json(); setTrainingHistory(thData.history || []); }
      } catch (e) { console.error(e); }
    };

    const fetchDashboardData = async () => {
      try {
        const [statusRes, geoRes, forecastRes, auditRes, hospRes, convRes, pbRes] = await Promise.all([
          fetch(`${API_URL}/api/public/fl-status`),
          fetch(`${API_URL}/api/geospatial/hotspots`),
          fetch(`${API_URL}/api/geospatial/forecast`),
          fetch(`${API_URL}/api/audit/trail`),
          fetch(`${API_URL}/api/dashboard/hospitals`),
          fetch(`${API_URL}/api/dashboard/convergence`),
          fetch(`${API_URL}/api/dashboard/privacy-budget`)
        ]);

        if (statusRes.ok) setStatus(await statusRes.json());
        
        if (convRes.ok) { const convData = await convRes.json(); setConvergenceHistory(convData.history || []); }
        if (pbRes.ok) { const pbData = await pbRes.json(); setPrivacyBudget({ used: pbData.epsilon_used || 0, budget: pbData.epsilon_budget || 1.0 }); }

        let geoData = { hotspots: [], clusters: [] };
        if (geoRes.ok) geoData = await geoRes.json();
        
        let forecastData = null;
        if (forecastRes.ok) forecastData = await forecastRes.json();
        
        setGeospatial({ hotspots: geoData.hotspots, clusters: geoData.clusters, forecast: forecastData });

        if (auditRes.ok) { const auditData = await auditRes.json(); setAuditTrail(auditData.trail || []); }
        
        if (hospRes.ok) { const hospData = await hospRes.json(); setHospitals(hospData.hospitals || []); }
      } catch (err) {
        console.error("Failed to load dashboard data", err);
      }
    };

    loadHospitalCredentials();
    fetchHospitalData();
    fetchDashboardData();
    
    const intervalDash = setInterval(fetchDashboardData, 15000);
    const intervalHosp = setInterval(fetchHospitalData, 30000);
    
    return () => {
      clearInterval(intervalDash);
      clearInterval(intervalHosp);
    };
  }, [token, role]);

  const handleLogout = () => {
    localStorage.removeItem('fl_token');
    localStorage.removeItem('fl_role');
    localStorage.removeItem('fl_user');
    sessionStorage.removeItem('fl_token');
    sessionStorage.removeItem('fl_role');
    sessionStorage.removeItem('fl_user');
    navigate('/login');
  };

  const handleUpload = async () => {
    const file = fileInputRef.current?.files[0];
    if (!file) {
      setActionMessage({ text: 'Please choose a file first.', type: 'error' });
      return;
    }

    setIsUploading(true);
    setActionMessage({ text: 'Uploading...', type: '' });
    
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${API_URL}/api/hospital/upload-data`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Upload failed');
      
      setActionMessage({ text: `✅ ${data.message}`, type: 'success' });
      
      // Refresh hospital data
      const [dsRes, uhRes] = await Promise.all([
        fetch(`${API_URL}/api/hospital/dataset-info`, { headers: { 'Authorization': `Bearer ${token}` } }),
        fetch(`${API_URL}/api/hospital/uploads`, { headers: { 'Authorization': `Bearer ${token}` } })
      ]);
      if (dsRes.ok) setDatasetInfo(await dsRes.json());
      if (uhRes.ok) { const uhData = await uhRes.json(); setUploadHistory(uhData.uploads || []); }
      
    } catch (err) {
      setActionMessage({ text: `❌ ${err.message}`, type: 'error' });
    } finally {
      setIsUploading(false);
    }
  };

  const handleTrain = async () => {
    if (!credentialHash) {
      setTrainMessage({ text: '❌ No valid credential. Awaiting admin approval.', type: 'error' });
      return;
    }

    setIsTraining(true);
    setTrainMessage({ text: '⏳ Training in progress — this may take up to 2 minutes...', type: '' });

    const formData = new FormData();
    formData.append("credential_hash", credentialHash);
    formData.append("epochs", epochs);
    formData.append("epsilon", epsilon);

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 120000);

    try {
      const res = await fetch(`${API_URL}/api/hospital/train`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` },
        body: formData,
        signal: controller.signal
      });
      clearTimeout(timeoutId);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Training failed');
      
      const fileInfo = data.file_name ? ` | File: ${data.file_name}` : '';
      const hashInfo = data.model_hash ? ` | Hash: ${data.model_hash}` : '';
      setTrainMessage({ text: `✅ Trained! Accuracy: ${(data.accuracy * 100).toFixed(1)}% | Privacy: ${(data.privacy_score * 100).toFixed(0)}% | ε=${data.epsilon_used}${fileInfo}${hashInfo}`, type: 'success' });
      
      // Refresh training history
      const thRes = await fetch(`${API_URL}/api/hospital/history`, { headers: { 'Authorization': `Bearer ${token}` } });
      if (thRes.ok) { const thData = await thRes.json(); setTrainingHistory(thData.history || []); }

    } catch (e) {
      clearTimeout(timeoutId);
      if (e.name === "AbortError") {
        setTrainMessage({ text: "❌ Training timed out. The server is taking too long — try reducing Epochs to 2 and retry.", type: 'error' });
      } else if (e.message === "Failed to fetch") {
        setTrainMessage({ text: "❌ Cannot reach the server. The backend may be sleeping. Wait 30 seconds and try again.", type: 'error' });
      } else {
        setTrainMessage({ text: `❌ ${e.message}`, type: 'error' });
      }
    } finally {
      setIsTraining(false);
    }
  };

  const downloadModel = async () => {
    try {
      const res = await fetch(`${API_URL}/api/hospital/model/download`, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Unknown error');
      }
      
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'fl_global_model.pth';
      a.click(); URL.revokeObjectURL(url);
    } catch (err) {
      alert("Download failed: " + err.message);
    }
  };

  // Map the real convergence API history
  const metrics = convergenceHistory.map(h => ({ round: h.round_number, accuracy: h.accuracy || 0 }));
  const finalAcc = metrics.length ? metrics[metrics.length - 1].accuracy : 0;

  const forecast = geospatial?.forecast;
  const alertLevel = forecast?.alert;

  const approvedHospitals = hospitals.filter(h => h.government_approved);
  const activeHospitals = approvedHospitals.filter(h => h.last_active && (Date.now() - new Date(h.last_active).getTime()) < 60 * 60 * 1000);
  const activeCount = activeHospitals.length;
  const approvedCount = approvedHospitals.length;

  return (
    <div className={styles.dashboardWrapper}>
      <header className={styles.header}>
        <div>
          <h1>🏥 FL-Health Dashboard</h1>
          <div className={styles.subtitle}>Federated Learning Based Privacy-Preserving Healthcare System</div>
        </div>
        <div className={styles.headerActions}>
          <div className={styles.badgeLive}>Live</div>
          {role === 'hospital' && (
            <button className={styles.btnAction} style={{ padding: '8px 14px', fontSize: '0.82em' }} onClick={downloadModel}>
              ⬇️ Model
            </button>
          )}
          <button className={styles.btnLogout} onClick={handleLogout}>Logout</button>
        </div>
      </header>

      {alertLevel && alertLevel !== 'GREEN' && forecast?.base_cases > 0 && (
        <div className={styles.alertBanner} style={{ borderColor: alertLevel === 'YELLOW' ? '#ffaa00' : '#ff4444', display: 'flex' }}>
          <div className={styles.iconWrapper} style={{ backgroundColor: alertLevel === 'YELLOW' ? 'rgba(255,170,0,0.2)' : 'rgba(255,68,68,0.2)' }}>
            <div style={{ fontSize: '1.6em' }}>🚨</div>
          </div>
          <div style={{ flex: 1 }}>
            <div className={styles.alertTitle} style={{ color: alertLevel === 'YELLOW' ? '#ffaa00' : '#ff4444' }}>
              {alertLevel === 'RED' ? 'Critical High Alert' : 'Watch'}
            </div>
            <div className={styles.alertText}>
              <strong style={{ color: '#ffffff' }}>{alertLevel === 'RED' ? 'HIGH ALERT:' : 'WATCH:'}</strong> {alertLevel === 'YELLOW' ? `${forecast.base_cases} cases rising across` : `${forecast.base_cases} cases across`} {forecast.total_hospitals} hospitals. Peak expected on Day {forecast.peak_day}.
            </div>
            <div className={styles.alertAction} onClick={(e) => e.currentTarget.parentElement.parentElement.style.display = 'none'}>
              Acknowledge Alert
            </div>
          </div>
        </div>
      )}

      {role === 'hospital' && (
        <div className={styles.actionBar}>
          <div className={styles.actionCard}>
            <h3>📤 Upload Your Patient Data</h3>
            <div className={styles.row}>
              <input type="file" ref={fileInputRef} accept=".csv,.zip,.npy,.png,.jpg,.jpeg,.dat" className={styles.fileInput} />
              <button className={styles.btnAction} onClick={handleUpload} disabled={isUploading}>
                Upload
              </button>
            </div>
            <div className={`${styles.statusMsg} ${styles[actionMessage.type === 'error' ? 'statusMsgError' : actionMessage.type === 'success' ? 'statusMsgSuccess' : '']}`}>
              {actionMessage.text || 'Supports: CSV, ZIP, NPY, PNG, JPG'}
            </div>
          </div>

          <div className={styles.actionCard}>
            <h3>🚀 Train Local Model</h3>
            <div className={styles.row}>
              <label style={{ color: '#6b8aa8', fontSize: '0.85em' }}>Epochs</label>
              <input type="number" value={epochs} onChange={(e) => setEpochs(e.target.value)} min="1" max="10" className={styles.inputSmall} />
              <label style={{ color: '#6b8aa8', fontSize: '0.85em' }}>ε</label>
              <input type="number" value={epsilon} onChange={(e) => setEpsilon(e.target.value)} step="0.1" min="0.1" max="10" className={styles.inputSmall} />
              <button className={`${styles.btnAction} ${styles.btnActionTrain}`} onClick={handleTrain} disabled={isTraining || !credentialHash}>
                Start Training
              </button>
            </div>
            <div className={`${styles.statusMsg} ${styles[trainMessage.type === 'error' ? 'statusMsgError' : trainMessage.type === 'success' ? 'statusMsgSuccess' : '']}`}>
              {trainMessage.text}
            </div>
          </div>
        </div>
      )}

      <div className={styles.grid2x2}>
        <div className={styles.card}>
          <div className={styles.cardTitle}>📈 Accuracy Convergence <span className={styles.cardTitleBadge}>Final: {(finalAcc * 100).toFixed(1)}%</span></div>
          <div className={styles.chartContainer}>
            <ConvergenceChart metrics={metrics} />
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardTitle}>🔐 Privacy Budget Used <span className={styles.cardTitleBadge}>● {privacyBudget.used < 0.5 ? 'Excellent' : privacyBudget.used < 0.8 ? 'Good' : 'High'}</span></div>
          <PrivacyGauge budget={privacyBudget.used} maxBudget={privacyBudget.budget} />
          <div className={styles.gaugeStatus}>Privacy Budget Used</div>
          <div className={styles.progressBar}>
            <div className={styles.progressFill} style={{ width: `${(privacyBudget.used / privacyBudget.budget) * 100}%` }}></div>
          </div>
        </div>
      </div>

      <div className={styles.grid2x2}>
        <div className={styles.card}>
          <div className={styles.cardTitle}>🗺️ Disease Outbreak Heatmap <span className={styles.cardTitleBadge}>{geospatial?.hotspots?.length || 0} hospitals</span></div>
          <div className={styles.chartContainer} style={{ height: '300px' }}>
            <DiseaseMap hotspots={geospatial?.hotspots} />
          </div>
          <div className={styles.mapLegend}>
            <div className={styles.legendItem}><span className={`${styles.legendDot} ${styles.high}`}></span> High Risk</div>
            <div className={styles.legendItem}><span className={`${styles.legendDot} ${styles.medium}`}></span> Medium Risk</div>
            <div className={styles.legendItem}><span className={`${styles.legendDot} ${styles.low}`}></span> Low Risk</div>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardTitle}>📊 Feature Importance (SHAP)</div>
          <FeatureImportance />
        </div>
      </div>

      <div className={styles.grid2x2}>
        <div className={styles.card}>
          <div className={styles.cardTitle}>📉 Outbreak Forecast — 14 Days <span className={styles.cardTitleBadge} style={{ color: alertLevel === 'RED' ? '#ff4444' : alertLevel === 'YELLOW' ? '#ffaa00' : '#00ff88' }}>● {alertLevel || 'GREEN'}</span></div>
          <div className={styles.chartContainer}>
            <ForecastChart forecastData={forecast} />
          </div>
          <div style={{ marginTop: '12px', display: 'flex', gap: '12px', fontSize: '0.75em', justifyContent: 'center' }}>
            <span style={{ color: '#00d4ff' }}>● Actual</span>
            <span style={{ color: '#ffaa00' }}>● Ensemble</span>
            <span style={{ color: '#6b8aa8' }}>— CI Bounds</span>
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardTitle}>🏥 Hospital Participation <span className={styles.cardTitleBadge}>{activeCount} / {approvedCount} Active</span></div>
          <HospitalStatus hospitals={hospitals} />
        </div>
      </div>

      <div className={styles.grid2x2}>
        <div className={styles.card}>
          <div className={styles.cardTitle}>⛓️ Blockchain Audit Trail <span className={styles.cardTitleBadge}>✓ Valid</span></div>
          <div style={{ maxHeight: '250px', overflowY: 'auto', fontSize: '0.8em' }}>
            {auditTrail.length === 0 ? (
              <div style={{ color: '#6b8aa8', padding: '10px' }}>No audit entries yet.</div>
            ) : (
              auditTrail.slice(0, 15).map((log, i) => {
                const colorMap = { TRAIN: '#00ff88', UPLOAD: '#00d4ff', CREDENTIAL_ISSUE: '#ffaa00', AGGREGATE: '#aa80ff' };
                const color = colorMap[log.event_type] || '#6b8aa8';
                return (
                  <div key={i} style={{ padding: '10px', background: '#0a1628', borderRadius: '6px', marginBottom: '6px', borderLeft: `3px solid ${color}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <strong style={{ color: color }}>{log.event_type}</strong>
                      <span style={{ color: '#6b8aa8', fontSize: '0.85em' }}>R{log.round_number}</span>
                    </div>
                    <div style={{ color: '#c0d0e0', marginTop: '4px', fontSize: '0.9em' }}>{log.hospital_name}</div>
                    {log.event_type === 'UPLOAD' && log.metadata?.file_name && (
                      <div style={{ color: '#6b8aa8', fontSize: '0.8em', marginTop: '2px' }}>📄 {log.metadata.file_name} · {log.metadata.total || 0} files</div>
                    )}
                    {log.event_type === 'TRAIN' && log.metadata?.file_name && (
                      <div style={{ color: '#6b8aa8', fontSize: '0.8em', marginTop: '2px' }}>📄 {log.metadata.file_name} · Acc: {((log.metadata.accuracy||0)*100).toFixed(1)}%</div>
                    )}
                    <div style={{ color: '#6b8aa8', fontSize: '0.78em', marginTop: '4px' }}>
                      ε: {log.epsilon_used} · {(log.current_hash || '').slice(0, 14)}…
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className={styles.card}>
          <div className={styles.cardTitle}>🗺️ Geospatial Clusters <span className={styles.cardTitleBadge}>{geospatial?.clusters?.length || 0}</span></div>
          <div style={{ maxHeight: '250px', overflowY: 'auto' }}>
            <ClusterList clusters={geospatial?.clusters} />
          </div>
        </div>
      </div>

      {role === 'hospital' && (
        <>
          <div className={styles.grid2x2} style={{ marginTop: '20px' }}>
            <div className={styles.card}>
              <div className={styles.cardTitle}>📂 Current Dataset on Server <span className={styles.cardTitleBadge}>{datasetInfo?.total_files || '—'} files</span></div>
              <DatasetInfo datasetInfo={datasetInfo} />
            </div>
            <div className={styles.card}>
              <div className={styles.cardTitle}>📤 Upload History <span className={styles.cardTitleBadge}>{uploadHistory?.length || '—'}</span></div>
              <UploadHistory uploads={uploadHistory} />
            </div>
          </div>
          
          <div className={styles.card} style={{ marginTop: '20px', marginBottom: '20px' }}>
            <div className={styles.cardTitle}>🧠 Training History <span className={styles.cardTitleBadge}>{trainingHistory?.length || '—'} sessions</span></div>
            <TrainingHistory sessions={trainingHistory} />
          </div>
        </>
      )}

      <div className={styles.bottomKpis}>
        <div className={styles.bottomKpi}>
          <div className={styles.icon}>📊</div>
          <div className={styles.content}>
            <div className={styles.value}>{(finalAcc * 100).toFixed(1)}%</div>
            <div className={styles.label}>Accuracy — Global Model</div>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${(finalAcc * 100).toFixed(1)}%` }}></div>
            </div>
          </div>
        </div>
        <div className={styles.bottomKpi}>
          <div className={styles.icon}>🔐</div>
          <div className={styles.content}>
            <div className={styles.value}>{privacyBudget.used.toFixed(2)} ε</div>
            <div className={styles.label}>Privacy Budget Used of 1.0</div>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${(privacyBudget.used / privacyBudget.budget) * 100}%` }}></div>
            </div>
          </div>
        </div>
        <div className={styles.bottomKpi}>
          <div className={styles.icon}>🏥</div>
          <div className={styles.content}>
            <div className={styles.value}>{activeCount} / {approvedCount}</div>
            <div className={styles.label}>Hospitals Active in FL</div>
            <div className={styles.progressBar}>
              <div className={styles.progressFill} style={{ width: `${approvedCount > 0 ? (activeCount / approvedCount) * 100 : 0}%` }}></div>
            </div>
          </div>
        </div>
      </div>
      
    </div>
  );
}
