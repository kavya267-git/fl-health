import React from 'react';
import { Line } from 'react-chartjs-2';
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend } from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

export default function ConvergenceChart({ metrics }) {
  const data = {
    labels: metrics.map(m => `R${m.round}`),
    datasets: [{
      label: 'Accuracy (%)',
      data: metrics.map(m => m.accuracy * 100),
      borderColor: '#00d4ff',
      backgroundColor: 'rgba(0, 212, 255, 0.15)',
      borderWidth: 2,
      pointBackgroundColor: '#00d4ff',
      pointRadius: 3,
      fill: true,
      tension: 0.4
    }]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: { mode: 'index', intersect: false }
    },
    scales: {
      y: { min: 40, max: 100, grid: { color: '#1a3555' }, ticks: { color: '#6b8aa8' } },
      x: { grid: { color: '#1a3555' }, ticks: { color: '#6b8aa8' } }
    },
    interaction: { mode: 'nearest', axis: 'x', intersect: false }
  };

  return <Line data={data} options={options} />;
}
