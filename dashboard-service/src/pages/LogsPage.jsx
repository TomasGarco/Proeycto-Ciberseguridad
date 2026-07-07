import { useEffect, useMemo, useRef, useState } from "react";
import { fetchLogs } from "../api";

const LEVELS = ["INFO", "WARNING", "ERROR", "DEBUG"];
const POLL_MS = 3000;

function levelClass(level) {
  const l = String(level || "").toLowerCase();
  return ["info", "warning", "error", "debug"].includes(l) ? l : "neutral";
}

function formatTs(ts) {
  return ts ? ts.replace("T", " ").substring(0, 19) : "—";
}

export default function LogsPage() {
  const [logs, setLogs] = useState([]);
  const [level, setLevel] = useState("");
  const [service, setService] = useState("");
  const [error, setError] = useState("");
  const filtersRef = useRef({ level, service });
  filtersRef.current = { level, service };

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const data = await fetchLogs({ limit: 100, ...filtersRef.current });
        if (active) {
          setLogs(data);
          setError("");
        }
      } catch {
        if (active) setError("No se pudo conectar con el Log Service.");
      }
    }

    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [level, service]);

  // Opciones del filtro de servicio derivadas de los logs recibidos
  const services = useMemo(() => {
    const set = new Set(logs.map((l) => String(l.service || "").toLowerCase()));
    if (service) set.add(service);
    return [...set].sort();
  }, [logs, service]);

  const rows = useMemo(() => [...logs].reverse(), [logs]); // más reciente primero

  return (
    <div className="card">
      <h2 style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span className="live-dot" /> Eventos registrados
      </h2>
      <p className="subtitle">
        Últimos 100 eventos del Log Service (MongoDB) — se actualiza cada {POLL_MS / 1000} s
      </p>

      <div className="controls">
        <select value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="">Todos los niveles</option>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l}
            </option>
          ))}
        </select>
        <select value={service} onChange={(e) => setService(e.target.value)}>
          <option value="">Todos los servicios</option>
          {services.map((s) => (
            <option key={s} value={s}>
              {s}
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
              <th>Servicio</th>
              <th>Nivel</th>
              <th>Mensaje</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={4} className="muted">
                  No hay eventos que coincidan con los filtros.
                </td>
              </tr>
            ) : (
              rows.map((log) => (
                <tr key={log._id}>
                  <td className="mono">{formatTs(log.timestamp)}</td>
                  <td>{log.service}</td>
                  <td>
                    <span className={`badge ${levelClass(log.level)}`}>
                      {String(log.level || "").toUpperCase()}
                    </span>
                  </td>
                  <td>{log.message}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
