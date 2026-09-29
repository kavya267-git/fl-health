import React from 'react';
import styles from '../../pages/Dashboard.module.css';

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export default function UploadHistory({ uploads }) {
  return (
    <div style={{ maxHeight: '260px', overflowY: 'auto' }}>
      <table className={styles.historyTable}>
        <thead>
          <tr>
            <th>File</th>
            <th>Type</th>
            <th>Files</th>
            <th>Date</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {!uploads || uploads.length === 0 ? (
            <tr><td colSpan="5" className={styles.emptyState}>No uploads yet. Upload your first dataset above.</td></tr>
          ) : (
            uploads.map((u, i) => {
              const date = u.created_at ? new Date(u.created_at).toLocaleString() : '—';
              const fileTypeClass = u.file_type || 'other';
              const statusClass = u.upload_status || 'completed';
              
              return (
                <tr key={i}>
                  <td style={{ color: '#ffffff', maxWidth: '160px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={u.file_name}>
                    {u.file_name}
                  </td>
                  <td><span className={`${styles.tag} ${styles[fileTypeClass] || styles.other}`}>{u.file_type || 'unknown'}</span></td>
                  <td style={{ color: '#00d4ff' }}>
                    {u.file_count || 0} <span style={{ color: '#6b8aa8', fontSize: '0.85em' }}>({formatBytes(u.file_size)})</span>
                  </td>
                  <td style={{ color: '#6b8aa8', fontSize: '0.85em' }}>{date}</td>
                  <td><span className={`${styles.tag} ${styles[statusClass] || styles.completed}`}>{u.upload_status || 'completed'}</span></td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
