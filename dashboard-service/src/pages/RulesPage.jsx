import { useEffect, useState } from "react";
import { fetchRules, updateRule } from "../api";
import { useToast } from "../toast";

// Mismas clases de badge que usa AlertsPage para las severidades — la regla
// y las alertas que genera se ven igual en todo el dashboard.
const SEVERITY_CLASS = { baja: "info", media: "warning", alta: "error", critica: "critical" };
const SEVERITY_LABEL = { baja: "BAJA", media: "MEDIA", alta: "ALTA", critica: "CRÍTICA" };
const TYPE_LABEL = { umbral: "Umbral", patron: "Patrón", palabra_clave: "Palabra clave" };

// Resumen legible de los parámetros según el tipo de regla.
function ruleParams(rule) {
  if (rule.type === "umbral") {
    return `${rule.threshold} eventos en ${rule.window_seconds} s${rule.per_service ? " (por servicio)" : ""}`;
  }
  if (rule.type === "patron") return rule.pattern;
  if (rule.type === "palabra_clave") return (rule.keywords || []).join(", ");
  return "—";
}

export default function RulesPage({ user }) {
  const [rules, setRules] = useState([]);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState(null);
  const toast = useToast();
  const isAdmin = user.role === "admin";

  useEffect(() => {
    fetchRules()
      .then(setRules)
      .catch(() => setError("No se pudo conectar con el Analysis Service."));
  }, []);

  async function toggle(rule) {
    setBusyId(rule.id);
    try {
      const updated = await updateRule(rule.id, !rule.enabled);
      setRules((list) => list.map((r) => (r.id === updated.id ? updated : r)));
      toast(
        `Regla «${rule.name}» ${updated.enabled ? "activada" : "desactivada"}.`,
        updated.enabled ? "success" : "warning"
      );
    } catch {
      toast(`No se pudo actualizar la regla «${rule.name}».`, "error");
    } finally {
      setBusyId(null);
    }
  }

  const activas = rules.filter((r) => r.enabled).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="card">
        <h2>Reglas de detección</h2>
        <p className="subtitle">
          Motor de reglas del Analysis Service — cada evento consumido de RabbitMQ se evalúa
          contra las reglas activas; las coincidencias generan alertas con su severidad.
          {isAdmin
            ? " Como admin puedes activarlas o desactivarlas en caliente (el cambio persiste en Redis)."
            : " Solo el rol admin puede activarlas o desactivarlas."}
        </p>

        <div className="tiles" style={{ marginBottom: 16 }}>
          <div className="tile">
            <div className="tile-label">Reglas totales</div>
            <div className="tile-value">{rules.length || "—"}</div>
            <div className="tile-detail">definidas en el motor</div>
          </div>
          <div className="tile">
            <div className="tile-label">Activas</div>
            <div className="tile-value">{rules.length ? activas : "—"}</div>
            <div className="tile-detail">evaluando cada evento</div>
          </div>
          <div className="tile">
            <div className="tile-label">Desactivadas</div>
            <div className="tile-value">{rules.length ? rules.length - activas : "—"}</div>
            <div className="tile-detail">no generan alertas</div>
          </div>
        </div>

        {error && <span className="error-msg">{error}</span>}

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Regla</th>
                <th>Tipo</th>
                <th>Severidad</th>
                <th>Parámetros</th>
                <th>Estado</th>
                {isAdmin && <th>Acciones</th>}
              </tr>
            </thead>
            <tbody>
              {rules.length === 0 && !error ? (
                <tr>
                  <td colSpan={isAdmin ? 6 : 5} className="muted">
                    Cargando reglas…
                  </td>
                </tr>
              ) : (
                rules.map((rule) => (
                  <tr key={rule.id} style={rule.enabled ? undefined : { opacity: 0.55 }}>
                    <td>
                      {rule.name}
                      <div className="mono muted" style={{ fontSize: "0.78rem" }}>{rule.id}</div>
                    </td>
                    <td>
                      <span className="badge neutral">{TYPE_LABEL[rule.type] || rule.type}</span>
                    </td>
                    <td>
                      <span className={`badge ${SEVERITY_CLASS[rule.severity] || "neutral"}`}>
                        {SEVERITY_LABEL[rule.severity] || String(rule.severity || "").toUpperCase()}
                      </span>
                    </td>
                    <td className="mono" style={{ fontSize: "0.82rem" }}>{ruleParams(rule)}</td>
                    <td>
                      <span className={`badge ${rule.enabled ? "info" : "neutral"}`}>
                        {rule.enabled ? "Activa" : "Desactivada"}
                      </span>
                    </td>
                    {isAdmin && (
                      <td className="actions-cell">
                        <button
                          className="btn small"
                          disabled={busyId === rule.id}
                          onClick={() => toggle(rule)}
                        >
                          {rule.enabled ? "Desactivar" : "Activar"}
                        </button>
                      </td>
                    )}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
