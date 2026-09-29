import React from 'react';

export default function ClusterList({ clusters }) {
  if (!clusters || clusters.length === 0) {
    return <div style={{ color: '#6b8aa8', padding: '10px' }}>No clusters yet.</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {clusters.map((c, i) => {
        const color = c.risk === 'High' ? '#ff4444' : c.risk === 'Medium' ? '#ffaa00' : '#00ff88';
        const badgeBg = c.risk === 'High' ? 'rgba(255,68,68,0.2)' : c.risk === 'Medium' ? 'rgba(255,170,0,0.2)' : 'rgba(0,255,136,0.2)';

        return (
          <div key={i} style={{ padding: '12px', background: '#0a1628', borderRadius: '8px', borderLeft: `4px solid ${color}` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong style={{ color: color }}>Cluster {c.cluster_id}</strong>
              <span style={{ display: 'inline-block', padding: '4px 10px', borderRadius: '6px', fontSize: '0.7em', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.5px', background: badgeBg, color: color }}>
                {c.risk}
              </span>
            </div>
            <div style={{ color: '#c0d0e0', fontSize: '0.85em', marginTop: '6px' }}>
              {c.hospitals} hospital(s) · {c.total_cases} cases
            </div>
          </div>
        );
      })}
    </div>
  );
}
