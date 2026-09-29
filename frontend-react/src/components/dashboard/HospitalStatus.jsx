import React from 'react';

export default function HospitalStatus({ hospitals }) {
  if (!hospitals || hospitals.length === 0) {
    return <div style={{ color: '#6b8aa8', fontSize: '0.85em', padding: '10px' }}>No hospitals registered yet.</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '260px', overflowY: 'auto' }}>
      {hospitals.map((h, i) => {
        const last = h.last_active ? new Date(h.last_active).getTime() : 0;
        const minsAgo = (Date.now() - last) / 60000;
        let status = 'offline';
        let statusColor = '#ff4444';
        
        if (minsAgo < 5) { status = 'online'; statusColor = '#00ff88'; }
        else if (minsAgo < 60) { status = 'syncing'; statusColor = '#ffaa00'; }

        const acc = h.local_accuracy ? (h.local_accuracy * 100).toFixed(1) : '—';
        
        return (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 15px', background: '#0a1628', borderRadius: '8px', fontSize: '0.85em' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', background: statusColor, boxShadow: status === 'online' ? '0 0 10px #00ff88' : 'none', animation: status === 'syncing' ? 'pulse 1s infinite' : 'none' }}></span>
              <span>{h.hospital_name}</span>
            </div>
            <div style={{ color: statusColor, fontSize: '0.9em' }}>
              {acc}% · {h.rounds_participated || 0} rounds
            </div>
          </div>
        );
      })}
    </div>
  );
}
