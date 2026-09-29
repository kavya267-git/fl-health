import React from 'react';
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

// Fix leaflet icon issue in react-leaflet by importing CSS above
export default function DiseaseMap({ hotspots }) {
  const riskColors = { High: '#ff4444', Medium: '#ffaa00', Low: '#00ff88' };

  // Center around India roughly if hotspots are empty, else fit to bounds dynamically or use fixed center for simplicity.
  const center = [20.5937, 78.9629];
  
  return (
    <MapContainer attributionControl={false} center={center} zoom={4} style={{ height: '100%', width: '100%', borderRadius: '12px', background: '#0a1628' }}>
      <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution="&copy; OpenStreetMap"
        className="dark-tiles"
      />
      {hotspots && hotspots.map((h, i) => (
        <React.Fragment key={i}>
          {h.risk === 'High' && (
            <CircleMarker 
              center={[h.lat, h.lng]} 
              pathOptions={{ color: riskColors[h.risk], fillColor: riskColors[h.risk], fillOpacity: 0.15, weight: 0 }} 
              radius={22} 
            />
          )}
          <CircleMarker 
            center={[h.lat, h.lng]} 
            pathOptions={{ color: riskColors[h.risk], fillColor: riskColors[h.risk], fillOpacity: 0.85, weight: 2 }} 
            radius={12}
          >
            <Popup>
              <div style={{ color: '#000' }}>
                <strong>{h.hospital_name}</strong><br/>
                City: {h.city || 'N/A'}<br/>
                Risk: <span style={{ color: riskColors[h.risk], fontWeight: 'bold' }}>{h.risk}</span><br/>
                Cases: {h.cases}
              </div>
            </Popup>
          </CircleMarker>
        </React.Fragment>
      ))}
    </MapContainer>
  );
}
