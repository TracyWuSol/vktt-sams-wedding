import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom';
import AdminPage from './pages/AdminPage';
import GuestPage from './pages/GuestPage';
import { fetchStatus } from './services/api';
import { StatusStats } from './types';

function NavBar({ stats }: { stats: StatusStats | null }) {
  return (
    <nav className="navbar">
      <div className="navbar__brand">
        <span className="navbar__logo">✦</span>
        <span className="navbar__title">
          Wedding Photos <em>&</em> Memories
        </span>
      </div>
      <div className="navbar__links">
        <NavLink
          to="/"
          end
          className={({ isActive }) => `nav-link${isActive ? ' nav-link--active' : ''}`}
        >
          Admin
        </NavLink>
        <NavLink
          to="/upload"
          className={({ isActive }) => `nav-link${isActive ? ' nav-link--active' : ''}`}
        >
          Upload Photos
        </NavLink>
      </div>
      {stats && (
        <div className="navbar__stats">
          <span>{stats.registeredGuests} guests</span>
          <span className="navbar__sep">·</span>
          <span>{stats.notificationsSent} notified</span>
        </div>
      )}
    </nav>
  );
}

export default function App() {
  const [stats, setStats] = useState<StatusStats | null>(null);

  useEffect(() => {
    // Poll status every 10 s so the navbar stats stay current
    const load = () => fetchStatus().then(setStats).catch(() => {});
    load();
    const id = setInterval(load, 10_000);
    return () => clearInterval(id);
  }, []);

  return (
    <BrowserRouter>
      <NavBar stats={stats} />
      <main className="main-content">
        <Routes>
          <Route path="/" element={<AdminPage />} />
          <Route path="/upload" element={<GuestPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
