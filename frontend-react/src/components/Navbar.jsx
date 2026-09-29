import { Link, useLocation } from 'react-router-dom';
import styles from './Navbar.module.css';

export default function Navbar() {
  const location = useLocation();
  const path = location.pathname;

  return (
    <nav className={styles.nav}>
      <Link to="/" className={styles.navBrand}>
        <div className={styles.navBrandIcon}>🏥</div>
        <div className={styles.navBrandText}>FL-Health</div>
      </Link>
      <div className={styles.navLinks}>
        <Link to="/" className={`${styles.navLink} ${path === '/' ? styles.active : ''}`}>Home</Link>
        <Link to="/about" className={`${styles.navLink} ${path === '/about' ? styles.active : ''}`}>Learn FL</Link>
        <Link to="/privacy" className={`${styles.navLink} ${path === '/privacy' ? styles.active : ''}`}>Privacy</Link>
        <Link to="/network" className={`${styles.navLink} ${path === '/network' ? styles.active : ''}`}>Join</Link>
        
        {path !== '/login' && (
          <Link to="/login" className={`${styles.navLink} ${path === '/login' ? styles.active : ''}`}>Sign In</Link>
        )}
        
        {path !== '/register' && (
          <Link to="/register" className={`${styles.navLink} ${styles.primary}`}>Register</Link>
        )}
      </div>
    </nav>
  );
}
