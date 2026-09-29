import React from 'react';
import { Link } from 'react-router-dom';
import Navbar from '../components/Navbar';
import styles from './Learn.module.css';

export default function About() {
  return (
    <div style={{ minHeight: '100vh', background: 'linear-gradient(135deg, #e0f2fe 0%, #bae6fd 50%, #7dd3fc 100%)', color: '#0c4a6e' }}>
      <Navbar />

      <section className={styles.hero}>
        <div className={styles.heroBadge}>📚 Chapter 1 of 3</div>
        <h1>What is <span className={styles.accent}>Federated Learning</span>?</h1>
        <p>
          Understand the basic idea behind FL-Health — how multiple hospitals train AI together
          without ever sharing patient data. No ML background required.
        </p>
      </section>

      <div className={styles.progress}>
        <div className={`${styles.progressDot} ${styles.active}`}></div>
        <div className={styles.progressDot}></div>
        <div className={styles.progressDot}></div>
      </div>

      <div className={styles.container}>
        <div className={styles.section}>
          <div className={styles.sectionLabel}>Section 1</div>
          <h2>The Basic Idea</h2>
          <p>
            Federated Learning is a technique where multiple organizations (hospitals, in our case)
            train a shared AI model together — <strong>without ever sharing their raw data</strong>.
          </p>
          <p>
            Instead of sending patient records to a central server, each hospital trains a copy of
            the AI on its own data. Only the <strong>mathematical updates</strong> (called "weights")
            travel to the server. The server combines them into a better global model and sends it back.
          </p>

          <img src="/assets/images/about_hero.png" alt="Federated Learning Overview" className={styles.sectionImage} />

          <div className={styles.analogyBox}>
            <h4>🍩 Simple Analogy</h4>
            <p>
              Imagine 4 friends each have a secret recipe for the best cake. They can't share
              their recipes. But they <em>can</em> each bake a cake, taste-test all 4 versions,
              and agree on a <strong>combined recipe</strong> that uses the best parts of each —
              without ever revealing any single original recipe.
            </p>
          </div>
        </div>

        <div className={styles.section}>
          <div className={styles.sectionLabel}>Section 2</div>
          <h2>How Does It Work? — 4 Steps</h2>
          <p>
            Each training round follows the same 4-step cycle. After 50-100 rounds, the global
            model becomes significantly more accurate than any single hospital could achieve alone.
          </p>

          <img src="/assets/images/fl_process.png" alt="Federated Learning Process" className={styles.sectionImage} />

          <div className={styles.analogyBox}>
            <h4>📚 Simple Analogy</h4>
            <p>
              Think of 5 students preparing for an exam. Each has their own notes they can't
              share. Instead, they each solve a practice problem, then discuss <em>the method</em>
              they used. Everyone updates their notes with the better method. No one's notes
              are ever seen by anyone else — but everyone improves.
            </p>
          </div>
        </div>
      </div>

      <div className={styles.pageNav}>
        <Link to="/" className={styles.pageNavBtn}>← Home</Link>
        <Link to="/privacy" className={`${styles.pageNavBtn} ${styles.pageNavBtnPrimary}`}>Next: Privacy →</Link>
      </div>

      <footer className={styles.footer}>
        <strong>FL-Health</strong> · Data stays local. Only learning travels.
      </footer>
    </div>
  );
}
