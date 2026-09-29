import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import styles from './Admin.module.css';
import { API_URL } from '../config';

export default function Admin() {
  const navigate = useNavigate();
  const [token, setToken] = useState('');
  
  const [activeTab, setActiveTab] = useState('pending');
  const [status, setStatus] = useState(null);
  const [hospitals, setHospitals] = useState([]);
  const [allHistory, setAllHistory] = useState([]);
  const [convergence, setConvergence] = useState([]);
  const [auditTrail, setAuditTrail] = useState([]);
  
  const [isApproving, setIsApproving] = useState(false);
  const [selectedHospital, setSelectedHospital] = useState(null);
  const [modalAction, setModalAction] = useState(null); // 'approve' | 'revoke'
  const [downloading, setDownloading] = useState(false);

  useEffect(() => {
    const savedToken = localStorage.getItem('fl_token') || sessionStorage.getItem('fl_token');
    const savedRole = localStorage.getItem('fl_role') || sessionStorage.getItem('fl_role');

    if (!savedToken || savedRole !== 'admin') {
      navigate('/login');
      return;
    }
    setToken(savedToken);
  }, [navigate]);

  const fetchData = async () => {
    if (!token) return;
    try {
      const [hospRes, statRes, histRes, convRes, auditRes] = await Promise.all([
        fetch(`${API_URL}/api/admin/all-hospitals`, { headers: { "Authorization": `Bearer ${token}` } }),
        fetch(`${API_URL}/api/public/fl-status`),
        fetch(`${API_URL}/api/admin/all-history`, { headers: { "Authorization": `Bearer ${token}` } }),
        fetch(`${API_URL}/api/dashboard/convergence`),
        fetch(`${API_URL}/api/audit/trail`)
      ]);

      if (hospRes.ok) { const d = await hospRes.json(); setHospitals(d.hospitals || []); }
      if (statRes.ok) setStatus(await statRes.json());
      if (histRes.ok) { const d = await histRes.json(); setAllHistory(d.history || []); }
      if (convRes.ok) { const d = await convRes.json(); setConvergence(d.history || []); }
      if (auditRes.ok) { const d = await auditRes.json(); setAuditTrail(d.trail || []); }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [token]);

  const handleAction = async () => {
    if (!selectedHospital || !modalAction) return;
    setIsApproving(true);
    
    const endpoint = modalAction === 'approve' ? '/api/admin/approve-hospital' : '/api/admin/revoke-hospital';
    
    try {
      const res = await fetch(`${API_URL}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify({ hospital_id: selectedHospital.id })
      });
      if (!res.ok) throw new Error("Action failed");
      
      setSelectedHospital(null);
      setModalAction(null);
      fetchData(); // Refresh immediately
    } catch (err) {
      alert(err.message);
    } finally {
      setIsApproving(false);
    }
  };

  const downloadModel = async () => {
    setDownloading(true);
    try {
      const res = await fetch(`${API_URL}/api/hospital/model/download`, {
        headers: { "Authorization": `Bearer ${token}` }
      });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = "fl_global_model.pth";
      a.click(); URL.revokeObjectURL(url);
    } catch (e) {
      alert(e.message);
    } finally {
      setDownloading(false);
    }
  };

  const pendingHospitals = hospitals.filter(h => !h.government_approved);
  const approvedHospitals = hospitals.filter(h => h.government_approved);
  const active24h = approvedHospitals.filter(h => h.last_active && (Date.now() - new Date(h.last_active).getTime()) < 24 * 60 * 60 * 1000);

  return (
    <div style={{ background: 'linear-gradient(135deg, #e0f2fe 0%, #f0f9ff 100%)', minHeight: '100vh' }}>
      <Navbar />
      
      <div className={styles.adminContainer}>
        <div className={styles.headerCard}>
          <div className={styles.headerLeft}>
            <div className={styles.headerLogo}>🔐</div>
            <div className={styles.headerInfo}>
              <h1>Admin Control Center</h1>
              <p>Federated Learning · Byzantine Tolerance · Privacy-Preserving Healthcare</p>
            </div>
          </div>
          <div className={styles.liveBadge}><div className={styles.liveDot}></div> Live</div>
        </div>

        <div className={styles.stats}>
          <div className={`${styles.statCard} ${styles.pending}`}>
            <div className={styles.statIcon}>⏳</div>
            <div className={styles.statValue}>{pendingHospitals.length}</div>
            <div className={styles.statLabel}>Pending Approval</div>
          </div>
          <div className={`${styles.statCard} ${styles.approved}`}>
            <div className={styles.statIcon}>✅</div>
            <div className={styles.statValue}>{approvedHospitals.length}</div>
            <div className={styles.statLabel}>Approved Hospitals</div>
          </div>
          <div className={`${styles.statCard} ${styles.rounds}`}>
            <div className={styles.statIcon}>🔄</div>
            <div className={styles.statValue}>{status?.current_round || 0}</div>
            <div className={styles.statLabel}>FL Round</div>
            <div className={styles.statSub}>of 100 max</div>
          </div>
          <div className={`${styles.statCard} ${styles.acc}`}>
            <div className={styles.statIcon}>📊</div>
            <div className={styles.statValue}>{status?.avg_accuracy ? `${status.avg_accuracy}%` : '—'}</div>
            <div className={styles.statLabel}>Avg Accuracy</div>
            <div className={styles.statSub}>Target: 65-75%</div>
          </div>
          <div className={`${styles.statCard} ${styles.byz}`}>
            <div className={styles.statIcon}>🛡️</div>
            <div className={styles.statValue}>{allHistory.length}</div>
            <div className={styles.statLabel}>Training Sessions</div>
          </div>
          <div className={styles.statCard}>
            <div className={styles.statIcon}>📤</div>
            <div className={styles.statValue}>{auditTrail.filter(a => a.event_type === 'UPLOAD').length}</div>
            <div className={styles.statLabel}>Total Uploads</div>
          </div>
        </div>

        <div className={styles.tabs}>
          <div className={`${styles.tab} ${activeTab === 'pending' ? styles.active : ''}`} onClick={() => setActiveTab('pending')}>⏳ Pending Approval</div>
          <div className={`${styles.tab} ${activeTab === 'approved' ? styles.active : ''}`} onClick={() => setActiveTab('approved')}>✅ Approved Hospitals</div>
          <div className={`${styles.tab} ${activeTab === 'models' ? styles.active : ''}`} onClick={() => setActiveTab('models')}>🧠 Model Versions</div>
          <div className={`${styles.tab} ${activeTab === 'training' ? styles.active : ''}`} onClick={() => setActiveTab('training')}>📈 All Training Sessions</div>
        </div>

        {(activeTab === 'pending' || activeTab === 'approved') && (
          <div className={styles.hospitalGrid}>
            {(activeTab === 'pending' ? pendingHospitals : approvedHospitals).length === 0 ? (
              <div className={styles.emptyState}>
                <div style={{ fontSize: '48px' }}>🏥</div>
                <h3>No {activeTab} hospitals</h3>
                <p>There are currently no hospitals in this list.</p>
              </div>
            ) : (
              (activeTab === 'pending' ? pendingHospitals : approvedHospitals).map((h, i) => (
                <div key={i} className={`${styles.hospitalCard} ${activeTab === 'pending' ? styles.pending : styles.approved}`}>
                  <div className={styles.cardHeader}>
                    <h3>{h.hospital_name}</h3>
                    <span className={`${styles.statusBadge} ${activeTab === 'pending' ? styles.pending : styles.approved}`}>
                      {activeTab === 'pending' ? 'Pending' : 'Approved'}
                    </span>
                  </div>
                  <div className={styles.cardBody}>
                    <div className={styles.infoRow}><span className={styles.label}>ID</span><span className={styles.value}>{h.id.slice(0, 8)}...</span></div>
                    <div className={styles.infoRow}><span className={styles.label}>Email</span><span className={styles.value}>{h.email}</span></div>
                    {h.city && <div className={styles.infoRow}><span className={styles.label}>Location</span><span className={styles.value}>{h.city} ({h.state})</span></div>}
                    <div className={styles.infoRow}><span className={styles.label}>Joined</span><span className={styles.value}>{new Date(h.created_at).toLocaleDateString()}</span></div>
                  </div>
                  <div className={styles.cardActions}>
                    {activeTab === 'pending' ? (
                      <button className={`${styles.btn} ${styles.btnApprove}`} onClick={() => { setSelectedHospital(h); setModalAction('approve'); }}>Issue Credential</button>
                    ) : (
                      <>
                        <button className={`${styles.btn} ${styles.btnRevoke}`} onClick={() => { setSelectedHospital(h); setModalAction('revoke'); }}>Revoke</button>
                      </>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'models' && (
          <div className={styles.panel}>
            <div className={styles.panelTitle}>
              <div>🧠 Global Model Version History <span className={styles.panelBadge}>{convergence.length}</span></div>
              <button className={`${styles.btn} ${styles.btnApprove}`} style={{ flex: 'none', padding: '6px 16px', fontSize: '12px' }} onClick={downloadModel} disabled={downloading}>
                {downloading ? 'Downloading...' : '⬇️ Download Latest Model'}
              </button>
            </div>
            <div style={{ overflowX: 'auto', maxHeight: '500px', overflowY: 'auto' }}>
              <table className={styles.dataTable}>
                <thead>
                  <tr><th>Round</th><th>Hospitals</th><th>Byzantine Excluded</th><th>Dropout Rate</th><th>Model Hash</th><th>Date</th></tr>
                </thead>
                <tbody>
                  {convergence.length === 0 ? (
                    <tr><td colSpan="6" style={{ textAlign: 'center', color: '#64748b', padding: '30px' }}>No models yet</td></tr>
                  ) : (
                    convergence.map((m, i) => (
                      <tr key={i}>
                        <td style={{ fontWeight: 600 }}>R{m.round_number}</td>
                        <td>{m.hospitals_participated || 1}</td>
                        <td><span className={`${styles.tagSm} ${m.byzantine_excluded > 0 ? styles.yellow : styles.green}`}>{m.byzantine_excluded || 0}</span></td>
                        <td><span className={`${styles.tagSm} ${styles.blue}`}>0%</span></td>
                        <td style={{ fontFamily: 'monospace' }}>{(m.model_hash || 'none').slice(0, 16)}...</td>
                        <td>{new Date(m.created_at).toLocaleString()}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'training' && (
          <div className={styles.panel}>
            <div className={styles.panelTitle}>
              <div>📈 All Training Sessions (Global) <span className={styles.panelBadge}>{allHistory.length}</span></div>
            </div>
            <div style={{ overflowX: 'auto', maxHeight: '500px', overflowY: 'auto' }}>
              <table className={styles.dataTable}>
                <thead>
                  <tr><th>Round</th><th>Hospital</th><th>File</th><th>Data Type</th><th>Samples</th><th>Accuracy</th><th>ε</th><th>Privacy Score</th><th>Date</th></tr>
                </thead>
                <tbody>
                  {allHistory.length === 0 ? (
                    <tr><td colSpan="9" style={{ textAlign: 'center', color: '#64748b', padding: '30px' }}>No training sessions yet</td></tr>
                  ) : (
                    allHistory.map((s, i) => (
                      <tr key={i}>
                        <td style={{ fontWeight: 600 }}>R{s.round_number}</td>
                        <td style={{ fontWeight: 500 }}>{s.hospital_name}</td>
                        <td style={{ maxWidth: '120px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.file_name}>{s.file_name}</td>
                        <td><span className={`${styles.tagSm} ${styles.blue}`}>{s.data_type || 'other'}</span></td>
                        <td>{s.data_size || '—'}</td>
                        <td style={{ color: (s.accuracy||0) > 0.7 ? '#16a34a' : (s.accuracy||0) > 0.5 ? '#d97706' : '#dc2626', fontWeight: 600 }}>
                          {s.accuracy ? (s.accuracy * 100).toFixed(1) + '%' : '—'}
                        </td>
                        <td>{s.epsilon_used}</td>
                        <td>{s.privacy_score ? (s.privacy_score * 100).toFixed(0) + '%' : '—'}</td>
                        <td>{new Date(s.created_at).toLocaleString()}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {(activeTab === 'pending' || activeTab === 'approved') && (
          <div className={styles.bottomGrid}>
            <div className={styles.panel}>
              <div className={styles.panelTitle}>
                <div>🏥 Hospital Activity (24h) <span className={styles.panelBadge}>{approvedHospitals.length} hospitals</span></div>
              </div>
              <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                {approvedHospitals.length === 0 ? (
                  <p style={{ color: '#64748b', fontSize: '13px', padding: '10px' }}>No approved hospitals yet.</p>
                ) : (
                  approvedHospitals.map((h, i) => {
                    const last = h.last_active ? new Date(h.last_active).getTime() : 0;
                    const minsAgo = (Date.now() - last) / 60000;
                    const statusEmoji = minsAgo < 5 ? "🟢" : minsAgo < 60 ? "🟡" : "🔴";
                    const acc = h.local_accuracy ? (h.local_accuracy * 100).toFixed(1) + "%" : "—";
                    const timeStr = last ? (minsAgo < 60 ? `${Math.floor(minsAgo)}m ago` : `${Math.floor(minsAgo/60)}h ago`) : "Never";
                    return (
                      <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', background: '#f8fafc', borderRadius: '8px', marginBottom: '6px', fontSize: '13px' }}>
                        <span>{statusEmoji} <strong>{h.hospital_name}</strong></span>
                        <div style={{ display: 'flex', gap: '10px', color: '#64748b' }}>
                          <span>{acc} acc</span>
                          <span>{timeStr}</span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
            
            <div className={styles.panel}>
              <div className={styles.panelTitle}>
                <div>⛓️ Recent Audit Trail <span className={styles.panelBadge}>{auditTrail.slice(0, 15).length} recent</span></div>
              </div>
              <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                {auditTrail.slice(0, 15).map((e, i) => {
                  const colorMap = { TRAIN: '#10b981', UPLOAD: '#0284c7', CREDENTIAL_ISSUE: '#f59e0b', AGGREGATE: '#7c3aed' };
                  const color = colorMap[e.event_type] || '#64748b';
                  const meta = e.metadata || {};
                  return (
                    <div key={i} style={{ padding: '8px 10px', borderLeft: `3px solid ${color}`, background: '#f8fafc', borderRadius: '6px', marginBottom: '6px', fontSize: '12px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                        <strong style={{ color }}>{e.event_type}</strong>
                        <span style={{ color: '#94a3b8' }}>R{e.round_number}</span>
                      </div>
                      <div style={{ color: '#475569', marginTop: '2px' }}>{e.hospital_name}{meta.file_name ? ' · ' + meta.file_name : ''}</div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {selectedHospital && (
          <div className={styles.modalOverlay}>
            <div className={styles.modal}>
              <h2>{modalAction === 'approve' ? 'Approve Hospital?' : 'Revoke Hospital Access?'}</h2>
              <p>
                {modalAction === 'approve' 
                  ? 'This will instantly issue a W3C Verifiable Credential allowing the hospital to participate in federated training rounds.' 
                  : 'This will revoke the hospital\'s Verifiable Credential and remove their access to the federated learning network.'}
              </p>
              <div className={styles.modalDetails}>
                <div className={styles.row}><span className={styles.label}>Hospital</span><span className={styles.value}>{selectedHospital.hospital_name}</span></div>
                <div className={styles.row}><span className={styles.label}>Email</span><span className={styles.value}>{selectedHospital.email}</span></div>
                <div className={styles.row}><span className={styles.label}>Location</span><span className={styles.value}>{selectedHospital.city || 'N/A'}, {selectedHospital.state || 'N/A'}</span></div>
              </div>
              <div className={styles.modalActions}>
                <button className={styles.btnCancel} onClick={() => { setSelectedHospital(null); setModalAction(null); }}>Cancel</button>
                <button className={`${styles.btnConfirm} ${modalAction === 'revoke' ? styles.danger : ''}`} onClick={handleAction} disabled={isApproving}>
                  {isApproving ? 'Processing...' : modalAction === 'approve' ? 'Yes, Issue Credential' : 'Yes, Revoke Access'}
                </button>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
