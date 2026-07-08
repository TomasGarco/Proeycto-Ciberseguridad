import { useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fetchAlerts, fetchAlertStats, updateAlertStatus } from "../api";
import { useToast } from "../toast";
import { CHART_INK } from "../theme";

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
// Mismos tonos que los badges de severidad, para que el gráfico y la tabla coincidan visualmente.
const SEVERITY_COLOR = { baja: "#0ca30c", media: "#fab219", alta: "#d03b3b", critica: "#d03b3b" };

const SEVERITY_LABEL = Object.fromEntries(SEVERITIES);
const STATUS_LABEL = Object.fromEntries(STATUSES);

const SORTABLE_COLUMNS = [
  ["created_at", "Fecha y hora"],
  ["severity", "Severidad"],
  ["service", "Servicio"],
  ["status", "Estado"],
];

function formatTs(ts) {
  if (!ts) return "—";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: "#232322", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, padding: "8px 12px", fontSize: "0.8rem", color: "#c3c2b7" }}>
      <strong style={{ color: "#fff" }}>{SEVERITY_LABEL[label] || label}</strong>
      <div>{payload[0].value} alertas</div>
    </div>
  );
}

export default function AlertsPage({ user }) {
  const [alerts, setAlerts] = useState([]);
  const [stats, setStats] = useState(null);
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState({ key: "created_at", dir: "desc" });
  const [expandedId, setExpandedId] = useState(null);
  const [error, setError] = useState("");
  const toast = useToast();
  const isAdmin = user.role === "admin";
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

  function toggleSort(key) {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  }

  const porSeveridad = useMemo(() => stats?.por_severidad || {}, [stats]);
  const porEstado = useMemo(() => stats?.por_estado || {}, [stats]);

  const severityChartData = useMemo(
    () => SEVERITIES.map(([key, label]) => ({ key, label, total: porSeveridad[key] || 0 })),
    [porSeveridad]
  );

  // Búsqueda y orden son client-side: ya tenemos hasta 100 alertas cargadas
  // (fetchAlerts), no vale la pena un roundtrip de red por cada tecla.
  const visibleAlerts = useMemo(() => {
    const term = search.trim().toLowerCase();
    let rows = !term
      ? alerts
      : alerts.filter((a) =>
          [a.message, a.rule_name, a.service].some((v) => String(v || "").toLowerCase().includes(term))
        );

    rows = [...rows].sort((a, b) => {
      const va = a[sort.key] ?? "";
      const vb = b[sort.key] ?? "";
      const cmp = String(va).localeCompare(String(vb));
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [alerts, search, sort]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
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

        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={severityChartData} layout="vertical" margin={{ top: 0, right: 24, left: 8, bottom: 0 }}>
            <CartesianGrid horizontal={false} stroke={CHART_INK.grid} />
            <XAxis type="number" allowDecimals={false} tick={{ fill: CHART_INK.tick, fontSize: 12 }} axisLine={{ stroke: CHART_INK.axis }} tickLine={false} />
            <YAxis type="category" dataKey="label" tick={{ fill: CHART_INK.tick, fontSize: 12 }} axisLine={{ stroke: CHART_INK.axis }} tickLine={false} width={70} />
            <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
            <Bar dataKey="total" barSize={20} radius={[0, 4, 4, 0]}>
              <LabelList dataKey="total" position="right" fill={CHART_INK.label} fontSize={12} />
              {severityChartData.map((d) => (
                <Cell key={d.key} fill={SEVERITY_COLOR[d.key]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <div className="controls">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por mensaje, regla o servicio…"
            style={{ minWidth: 220 }}
          />
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
                {SORTABLE_COLUMNS.map(([key, label]) => (
                  <th key={key} className="sortable" onClick={() => toggleSort(key)}>
                    {label} {sort.key === key ? (sort.dir === "asc" ? "▲" : "▼") : ""}
                  </th>
                ))}
                <th>Regla</th>
                <th>Mensaje</th>
                {isAdmin && <th>Acciones</th>}
              </tr>
            </thead>
            <tbody>
              {visibleAlerts.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 7 : 6} className="muted">
                    No hay alertas que coincidan con los filtros.
                  </td>
                </tr>
              ) : (
                visibleAlerts.map((alert) => (
                  <>
                    <tr
                      key={alert.id}
                      onClick={() => setExpandedId((id) => (id === alert.id ? null : alert.id))}
                      style={{ cursor: "pointer" }}
                    >
                      <td className="mono">{formatTs(alert.created_at)}</td>
                      <td>
                        <span className={`badge ${SEVERITY_CLASS[alert.severity] || "neutral"}`}>
                          {SEVERITY_LABEL[alert.severity] || String(alert.severity || "").toUpperCase()}
                        </span>
                      </td>
                      <td>{alert.service || "—"}</td>
                      <td>
                        <span className={`badge ${STATUS_CLASS[alert.status] || "neutral"}`}>
                          {STATUS_LABEL[alert.status] || alert.status}
                        </span>
                      </td>
                      <td className="mono">{alert.rule_id}</td>
                      <td>{alert.message}</td>
                      {isAdmin && (
                        <td className="actions-cell" onClick={(e) => e.stopPropagation()}>
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
                      )}
                    </tr>
                    {expandedId === alert.id && (
                      <tr className="detail-row">
                        <td colSpan={isAdmin ? 7 : 6}>
                          <strong>Evento que disparó la alerta:</strong>
                          <pre>{JSON.stringify(alert.triggering_event, null, 2)}</pre>
                        </td>
                      </tr>
                    )}
                  </>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
