import React from 'react';
import styles from '../../pages/Dashboard.module.css';

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export default function DatasetInfo({ datasetInfo }) {
  if (!datasetInfo) {
    return <div className={styles.emptyState}>Loading dataset info…</div>;
  }
  
  if (!datasetInfo.has_data) {
    return <div className={styles.emptyState}>No data on server. Upload a dataset to begin.</div>;
  }

  return (
    <div>
      <div className={styles.datasetBar}>
        {datasetInfo.ehr_files > 0 && <span className={`${styles.datasetPill} ${styles.ehr}`}>📋 EHR: {datasetInfo.ehr_files}</span>}
        {datasetInfo.ecg_files > 0 && <span className={`${styles.datasetPill} ${styles.ecg}`}>📈 ECG: {datasetInfo.ecg_files}</span>}
        {datasetInfo.xray_files > 0 && <span className={`${styles.datasetPill} ${styles.xray}`}>🩻 X-Ray: {datasetInfo.xray_files}</span>}
        {datasetInfo.other_files > 0 && <span className={`${styles.datasetPill} ${styles.other}`}>📄 Other: {datasetInfo.other_files}</span>}
      </div>
      <div style={{ marginTop: '8px', color: '#6b8aa8', fontSize: '0.8em' }}>Total: {formatBytes(datasetInfo.size_bytes || 0)}</div>
      
      <div style={{ marginTop: '12px', maxHeight: '160px', overflowY: 'auto' }}>
        {(datasetInfo.files || []).slice(0, 10).map((f, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 8px', background: '#0a1628', borderRadius: '6px', marginBottom: '4px', fontSize: '0.82em' }}>
            <span style={{ color: '#c0d0e0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '200px' }} title={f.name}>{f.name}</span>
            <span style={{ color: '#6b8aa8', flexShrink: 0, marginLeft: '8px' }}>{formatBytes(f.size_bytes)}</span>
          </div>
        ))}
      </div>
      {datasetInfo.total_files > 10 && (
        <div style={{ color: '#6b8aa8', fontSize: '0.8em', marginTop: '6px' }}>
          +{datasetInfo.total_files - 10} more files…
        </div>
      )}
    </div>
  );
}
