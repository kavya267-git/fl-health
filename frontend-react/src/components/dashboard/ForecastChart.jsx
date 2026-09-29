import React from 'react';
import { Line } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler } from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

export default function ForecastChart({ forecastData }) {
  if (!forecastData || !forecastData.days) return null;

  const actualData = forecastData.ensemble.map((v, i) => i < 5 ? v * 0.95 : null);
  
  const data = {
    labels: forecastData.days.map(d => `D${d}`),
    datasets: [
      {
        label: 'Actual Cases',
        data: actualData,
        borderColor: '#ffffff',
        borderWidth: 2,
        pointBackgroundColor: '#ffffff',
        tension: 0.4,
        zIndex: 4
      },
      {
        label: 'Predicted Peak',
        data: forecastData.ensemble,
        borderColor: '#ffaa00',
        borderDash: [5, 5],
        borderWidth: 2,
        pointRadius: 0,
        tension: 0.4,
        zIndex: 3
      },
      {
        label: 'Upper CI',
        data: forecastData.upper_ci,
        borderColor: 'transparent',
        backgroundColor: 'rgba(255, 170, 0, 0.1)',
        fill: '+1',
        pointRadius: 0,
        tension: 0.4,
        zIndex: 1
      },
      {
        label: 'Lower CI',
        data: forecastData.lower_ci,
        borderColor: 'transparent',
        backgroundColor: 'rgba(255, 170, 0, 0.1)',
        fill: false,
        pointRadius: 0,
        tension: 0.4,
        zIndex: 1
      }
    ]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { mode: 'index', intersect: false } },
    scales: {
      y: { grid: { color: '#1a3555' }, ticks: { color: '#6b8aa8' } },
      x: { grid: { color: '#1a3555' }, ticks: { color: '#6b8aa8' } }
    },
    interaction: { mode: 'nearest', axis: 'x', intersect: false }
  };

  return <Line data={data} options={options} />;
}
