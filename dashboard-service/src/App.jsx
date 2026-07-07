import { useEffect, useState } from "react";
import { fetchMe, getToken, setToken } from "./api";
import { useToast } from "./toast";
import Logo from "./logo";
import LoginPage from "./pages/LoginPage";
import LogsPage from "./pages/LogsPage";
import StatsPage from "./pages/StatsPage";
import AlertsPage from "./pages/AlertsPage";
import UsersPage from "./pages/UsersPage";

const TABS = [
  { id: "logs", label: "Logs" },
  { id: "stats", label: "Estadísticas" },
  { id: "alerts", label: "Alertas" },
  { id: "users", label: "Usuarios", adminOnly: true },
];

export default function App() {
  const toast = useToast();
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(Boolean(getToken()));
  const [tab, setTab] = useState("logs");

  // Si hay un token guardado, validar la sesión contra /auth/me al cargar
  useEffect(() => {
    if (!getToken()) return;
    fetchMe()
      .then(setUser)
      .catch(() => {
        setToken(null);
        toast("Tu sesión expiró. Inicia sesión de nuevo.", "warning");
      })
      .finally(() => setChecking(false));
  }, [toast]);

  function logout() {
    setToken(null);
    setUser(null);
    setTab("logs");
    toast("Sesión cerrada correctamente.", "success");
  }

  if (checking) {
    return <div className="centered muted">Cargando sesión…</div>;
  }

  if (!user) {
    return <LoginPage onLogin={setUser} />;
  }

  const visibleTabs = TABS.filter((t) => !t.adminOnly || user.role === "admin");

  return (
    <div className="layout">
      <header className="topbar">
        <div className="brand">
          <span className="brand-logo"><Logo size={22} /></span>
          <div>
            <h1>SOC Dashboard</h1>
            <span>plataforma de monitoreo de eventos</span>
          </div>
        </div>
        <div className="userbox">
          <span className="live-dot" title="Conectado" />
          <span>
            {user.username} · <span className="badge neutral">{user.role}</span>
          </span>
          <button className="btn" onClick={logout}>
            Cerrar sesión
          </button>
        </div>
      </header>

      <nav className="tabs">
        {visibleTabs.map((t) => (
          <button
            key={t.id}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main>
        {tab === "logs" && <LogsPage />}
        {tab === "stats" && <StatsPage />}
        {tab === "alerts" && <AlertsPage />}
        {tab === "users" && user.role === "admin" && <UsersPage />}
      </main>

      <footer className="footer muted">
        Auth Service :8000 · Log Service :8010 · Analysis Service :8002 · RabbitMQ :15672
      </footer>
    </div>
  );
}
