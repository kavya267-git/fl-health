import React from 'react';
import { Doughnut } from 'react-chartjs-2';
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from 'chart.js';
import styles from '../../pages/Dashboard.module.css';

ChartJS.register(ArcElement, Tooltip, Legend);

export default function PrivacyGauge({ budget, maxBudget }) {
  const data = {
    labels: ['Used', 'Remaining'],
    datasets: [{
      data: [budget, Math.max(0, maxBudget - budget)],
      backgroundColor: ['#00ff88', '#1a3555'],
      borderWidth: 0,
      cutout: '80%',
      circumference: 180,
      rotation: 270,
    }]
  };

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
  };

  return (
    <div className={styles.gaugeContainer}>
      <Doughnut data={data} options={options} />
      <div className={styles.gaugeValue}>
        <div className={styles.number}>{budget.toFixed(2)}</div>
        <div className={styles.label}>/ {maxBudget ? maxBudget.toFixed(1) : '1.0'}</div>
      </div>
    </div>
  );
}
