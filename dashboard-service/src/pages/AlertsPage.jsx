import { useEffect, useMemo, useRef, useState } from "react";
import { fetchAlerts, fetchAlertStats, updateAlertStatus } from "../api";
import { useToast } from "../toast";

const POLL_MS = 3000;

// Severidades y estados que maneja el Alert Service (valores sin acento en la
// API; la etiqueta con acento es solo presentación).
const SEVERITIES = [
  ["baja", "BAJA"],
  ["media", "MEDIA"],
  ["alta", "ALTA"],
  ["critica", "CRÍTICA"],
];
const STATUSES = [
  ["nueva", "Nueva"],
  ["reconocida", "Reconocida"],
  ["cerrada", "Cerrada"],
];

const SEVERITY_CLASS = { baja: "info", media: "warning", alta: "error", critica: "critical" };
// Reutiliza las clases de badge existentes: azul (debug) para lo pendiente,
// ámbar para lo reconocido, gris para lo cerrado.
const STATUS_CLASS = { nueva: "debug", reconocida: "warning", cerrada: "neutral" };

const SEVERITY_LABEL = Object.fromEntries(SEVERITIES);
const STATUS_LABEL = Object.fromEntries(STATUSES);

function formatTs(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState([]);
  const [stats, setStats] = useState(null);
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const toast = useToast();
  const filtersRef = useRef({ severity, status });
  filtersRef.current = { severity, status };

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const [alertsData, statsData] = await Promise.all([
          fetchAlerts({ limit: 100, ...filtersRef.current }),
          fetchAlertStats(),
        ]);
        if (active) {
          setAlerts(alertsData);
          setStats(statsData);
          setError("");
        }
      } catch {
        if (active) setError("No se pudo conectar con el Alert Service.");
      }
    }

    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [severity, status]);

  async function changeStatus(alert, newStatus) {
    try {
      const updated = await updateAlertStatus(alert.id, newStatus);
      setAlerts((list) => list.map((a) => (a.id === updated.id ? updated : a)));
      toast(`Alerta #${alert.id} marcada como ${STATUS_LABEL[newStatus].toLowerCase()}.`, "success");
    } catch {
      toast(`No se pudo actualizar la alerta #${alert.id}.`, "error");
    }
  }

  const porSeveridad = useMemo(() => stats?.por_severidad || {}, [stats]);
  const porEstado = useMemo(() => stats?.por_estado || {}, [stats]);

  return (
    <div className="card">
      <h2 style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="live-dot" /> Alertas activas
      </h2>
      <p className="subtitle">
        Alertas del motor de reglas (Analysis Service → RabbitMQ → Alert Service) — se actualiza
        cada {POLL_MS / 1000} s
      </p>

      <div className="tiles" style={{ marginBottom: 16 }}>
        <div className="tile">
          <div className="tile-label">Alertas totales</div>
          <div className="tile-value">{stats ? stats.total_alertas : "—"}</div>
          <div className="tile-detail">persistidas en PostgreSQL (alerts_db)</div>
        </div>
        <div className="tile">
          <div className="tile-label">Nuevas</div>
          <div className="tile-value">{porEstado.nueva || 0}</div>
          <div className="tile-detail">pendientes de reconocer</div>
        </div>
        <div className="tile">
          <div className="tile-label">Críticas</div>
          <div className="tile-value">{porSeveridad.critica || 0}</div>
          <div className="tile-detail">máxima severidad</div>
        </div>
        <div className="tile">
          <div className="tile-label">Cerradas</div>
          <div className="tile-value">{porEstado.cerrada || 0}</div>
          <div className="tile-detail">incidentes resueltos</div>
        </div>
      </div>

      <div className="controls">
        <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
          <option value="">Todas las severidades</option>
          {SEVERITIES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Todos los estados</option>
          {STATUSES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        {error && <span className="error-msg">{error}</span>}
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Fecha y hora</th>
              <th>Severidad</th>
              <th>Regla</th>
              <th>Servicio</th>
              <th>Mensaje</th>
              <th>Estado</th>
              <th>Acciones</th>
            </tr>
          </thead>
          <tbody>
            {alerts.length === 0 ? (
              <tr>
                <td colSpan={7} className="muted">
                  No hay alertas que coincidan con los filtros.
                </td>
              </tr>
            ) : (
              alerts.map((alert) => (
                <tr key={alert.id}>
                  <td className="mono">{formatTs(alert.created_at)}</td>
                  <td>
                    <span className={`badge ${SEVERITY_CLASS[alert.severity] || "neutral"}`}>
                      {SEVERITY_LABEL[alert.severity] || String(alert.severity || "").toUpperCase()}
                    </span>
                  </td>
                  <td className="mono">{alert.rule_id}</td>
                  <td>{alert.service || "—"}</td>
                  <td>{alert.message}</td>
                  <td>
                    <span className={`badge ${STATUS_CLASS[alert.status] || "neutral"}`}>
                      {STATUS_LABEL[alert.status] || alert.status}
                    </span>
                  </td>
                  <td className="actions-cell">
                    {alert.status === "nueva" && (
                      <button className="btn small" onClick={() => changeStatus(alert, "reconocida")}>
                        Reconocer
                      </button>
                    )}
                    {alert.status !== "cerrada" && (
                      <button className="btn small" onClick={() => changeStatus(alert, "cerrada")}>
                        Cerrar
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
