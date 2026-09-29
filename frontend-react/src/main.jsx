import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'
import { Chart as ChartJS } from 'chart.js'

ChartJS.defaults.color = '#6b8aa8';
ChartJS.defaults.font.family = "'Inter', sans-serif";

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
