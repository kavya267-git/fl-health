import React from 'react';
import styles from '../../pages/Dashboard.module.css';

export default function TrainingHistory({ sessions }) {
  return (
    <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
      <table className={styles.historyTable}>
        <thead>
          <tr>
            <th>Round</th>
            <th>File Used</th>
            <th>Data Type</th>
            <th>Samples</th>
            <th>Accuracy</th>
            <th>ε</th>
            <th>Privacy Score</th>
            <th>Date</th>
          </tr>
        </thead>
        <tbody>
          {!sessions || sessions.length === 0 ? (
            <tr><td colSpan="8" className={styles.emptyState}>No training sessions yet. Upload data and click Start Training.</td></tr>
          ) : (
            sessions.map((s, i) => {
              const acc = s.accuracy != null ? (s.accuracy * 100).toFixed(1) + '%' : '—';
              const ps  = s.privacy_score != null ? (s.privacy_score * 100).toFixed(0) + '%' : '—';
              const dt  = s.data_type || '—';
              const date = s.created_at ? new Date(s.created_at).toLocaleString() : '—';
              const accColor = s.accuracy > 0.7 ? '#00ff88' : s.accuracy > 0.5 ? '#ffaa00' : '#ff6b6b';

              return (
                <tr key={i}>
                  <td style={{ color: '#00d4ff', fontWeight: 600 }}>R{s.round_number}</td>
                  <td style={{ color: '#ffffff', maxWidth: '140px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={s.file_name || '—'}>
                    {s.file_name || '—'}
                  </td>
                  <td><span className={`${styles.tag} ${styles[dt] || styles.other}`}>{dt}</span></td>
                  <td style={{ color: '#c0d0e0' }}>{s.data_size || '—'}</td>
                  <td style={{ color: accColor, fontWeight: 600 }}>{acc}</td>
                  <td style={{ color: '#ffaa00' }}>{s.epsilon_used ?? '—'}</td>
                  <td style={{ color: '#6b8aa8' }}>{ps}</td>
                  <td style={{ color: '#6b8aa8', fontSize: '0.82em' }}>{date}</td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
