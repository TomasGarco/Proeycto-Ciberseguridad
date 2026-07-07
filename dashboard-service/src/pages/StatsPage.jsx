import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchStats } from "../api";
import { CHART_INK, LEVEL_COLORS, LEVEL_ORDER, SERIES_BLUE } from "../theme";

const POLL_MS = 5000;

const TILE_ICONS = {
  activity: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  ),
  error: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  ),
  warning: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  server: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
      <line x1="6" y1="6" x2="6.01" y2="6" />
      <line x1="6" y1="18" x2="6.01" y2="18" />
    </svg>
  ),
};

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: "#232322",
        border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 6,
        padding: "8px 12px",
        fontSize: "0.8rem",
        color: "#c3c2b7",
      }}
    >
      <strong style={{ color: "#fff" }}>{label}</strong>
      <div>{payload[0].value} eventos</div>
    </div>
  );
}

const axisProps = {
  tick: { fill: CHART_INK.tick, fontSize: 12 },
  axisLine: { stroke: CHART_INK.axis },
  tickLine: false,
};

export default function StatsPage() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const data = await fetchStats();
        if (active) {
          setStats(data);
          setError("");
        }
      } catch {
        if (active) setError("No se pudo conectar con el Analysis Service.");
      }
    }

    load();
    const timer = setInterval(load, POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  if (error) {
    return (
      <div className="card">
        <h2>Estadísticas</h2>
        <p className="error-msg">{error}</p>
      </div>
    );
  }

  if (!stats) {
    return (
      <div className="card">
        <h2>Estadísticas</h2>
        <p className="muted">Cargando estadísticas…</p>
      </div>
    );
  }

  const porNivel = stats.por_nivel || {};
  const porServicio = stats.por_servicio || {};

  // Niveles en orden fijo de severidad; los desconocidos se añaden al final
  const levelKeys = [
    ...LEVEL_ORDER.filter((l) => l in porNivel),
    ...Object.keys(porNivel).filter((l) => !LEVEL_ORDER.includes(l)),
  ];
  const levelData = levelKeys.map((name) => ({ name, total: porNivel[name] }));

  const serviceData = Object.entries(porServicio)
    .map(([name, total]) => ({ name, total }))
    .sort((a, b) => b.total - a.total);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="tiles">
        <div className="tile">
          <div className="tile-label">{TILE_ICONS.activity} Eventos analizados</div>
          <div className="tile-value">{stats.total_eventos}</div>
          <div className="tile-detail">desde RabbitMQ (cola analysis_queue)</div>
        </div>
        <div className="tile">
          <div className="tile-label">{TILE_ICONS.error} Errores</div>
          <div className="tile-value">{porNivel.ERROR || 0}</div>
          <div className="tile-detail">eventos con nivel ERROR</div>
        </div>
        <div className="tile">
          <div className="tile-label">{TILE_ICONS.warning} Warnings</div>
          <div className="tile-value">{porNivel.WARNING || 0}</div>
          <div className="tile-detail">eventos con nivel WARNING</div>
        </div>
        <div className="tile">
          <div className="tile-label">{TILE_ICONS.server} Servicios activos</div>
          <div className="tile-value">{Object.keys(porServicio).length}</div>
          <div className="tile-detail">
            último evento: {stats.ultimo_evento_en ? stats.ultimo_evento_en.replace("T", " ").substring(0, 19) : "—"}
          </div>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Eventos por nivel</h2>
          <p className="subtitle">Conteo acumulado desde el arranque del Analysis Service</p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={levelData} margin={{ top: 20, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke={CHART_INK.grid} />
              <XAxis dataKey="name" {...axisProps} />
              <YAxis allowDecimals={false} {...axisProps} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="total" barSize={40} radius={[4, 4, 0, 0]}>
                <LabelList dataKey="total" position="top" fill={CHART_INK.label} fontSize={12} />
                {levelData.map((d) => (
                  <Cell key={d.name} fill={LEVEL_COLORS[d.name] || CHART_INK.tick} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="card">
          <h2>Eventos por servicio</h2>
          <p className="subtitle">Qué microservicios están generando eventos</p>
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={serviceData} margin={{ top: 20, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke={CHART_INK.grid} />
              <XAxis dataKey="name" {...axisProps} />
              <YAxis allowDecimals={false} {...axisProps} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
              <Bar dataKey="total" barSize={40} radius={[4, 4, 0, 0]} fill={SERIES_BLUE}>
                <LabelList dataKey="total" position="top" fill={CHART_INK.label} fontSize={12} />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
