import React from 'react';

export default function FeatureImportance() {
  const features = [
    { name: 'Patient Age', value: 0.24 },
    { name: 'Comorbidity Index', value: 0.21 },
    { name: 'Population Density', value: 0.18 },
    { name: 'Mobility Index', value: 0.16 },
    { name: 'Healthcare Capacity', value: 0.12 },
    { name: 'Environmental Factors', value: 0.09 }
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      {features.map((f, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{ width: '140px', fontSize: '0.85em', color: '#c0d0e0' }}>{f.name}</div>
          <div style={{ flex: 1, height: '20px', background: '#0a1628', borderRadius: '10px', overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${f.value * 100}%`, background: 'linear-gradient(90deg, #ffaa00, #ff6b00)', borderRadius: '10px', transition: 'width 0.5s ease' }}></div>
          </div>
          <div style={{ width: '50px', textAlign: 'right', fontSize: '0.85em', color: '#ffaa00', fontWeight: 'bold' }}>{f.value.toFixed(2)}</div>
        </div>
      ))}
    </div>
  );
}
