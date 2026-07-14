import { useEffect, useState } from "react";
import { fetchSessions, fetchUsers, getTokenPayload, revokeSession, updateUserRole } from "../api";
import { useToast } from "../toast";

// Las sesiones expiran solas (TTL en Redis): refrescar seguido mantiene la
// cuenta regresiva y hace visible al instante un logout desde otro navegador.
const SESSIONS_POLL_MS = 5000;

function formatTs(ts) {
  return ts ? String(ts).replace("T", " ").substring(0, 19) : "—";
}

function formatTtl(seconds) {
  if (seconds == null || seconds < 0) return "—";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m} min ${s} s` : `${s} s`;
}

export default function UsersPage({ user }) {
  const [users, setUsers] = useState([]);
  const [sessions, setSessions] = useState(null);
  const [error, setError] = useState("");
  const [sessionsError, setSessionsError] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [pendingRole, setPendingRole] = useState("");
  const toast = useToast();
  // jti del token con el que está logueado este navegador — su sesión se
  // marca como "actual" y no se puede revocar desde aquí (para eso está
  // el botón Cerrar sesión).
  const ownJti = getTokenPayload()?.jti;

  useEffect(() => {
    fetchUsers()
      .then(setUsers)
      .catch((err) => {
        const detail = err.response?.data?.detail;
        setError(detail || "No se pudo obtener la lista de usuarios.");
      });
  }, []);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const data = await fetchSessions();
        if (active) {
          setSessions(data);
          setSessionsError("");
        }
      } catch {
        if (active) setSessionsError("No se pudieron obtener las sesiones activas.");
      }
    }

    load();
    const timer = setInterval(load, SESSIONS_POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  function startEdit(u) {
    setEditingId(u.id);
    setPendingRole(u.role);
  }

  async function confirmRole(u) {
    try {
      const updated = await updateUserRole(u.id, pendingRole);
      setUsers((list) => list.map((x) => (x.id === updated.id ? updated : x)));
      toast(`Rol de '${updated.username}' actualizado a ${updated.role}.`, "success");
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast(detail || `No se pudo actualizar el rol de '${u.username}'.`, "error");
    } finally {
      setEditingId(null);
    }
  }

  async function revoke(session) {
    try {
      await revokeSession(session.jti);
      setSessions((prev) =>
        prev
          ? { ...prev, total: prev.total - 1, sesiones: prev.sesiones.filter((s) => s.jti !== session.jti) }
          : prev
      );
      toast(`Sesión de '${session.username}' revocada — su token ya no se acepta.`, "success");
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast(detail || `No se pudo revocar la sesión de '${session.username}'.`, "error");
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div className="card">
        <h2>Usuarios registrados</h2>
        <p className="subtitle">Cuentas del Auth Service (solo visible para administradores)</p>
        {error && <p className="error-msg">{error}</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Usuario</th>
                <th>Email</th>
                <th>Rol</th>
                <th>Creado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="mono">{u.id}</td>
                  <td>{u.username}</td>
                  <td>{u.email}</td>
                  <td>
                    <span className={`badge ${u.role === "admin" ? "debug" : "neutral"}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="mono">{formatTs(u.created_at)}</td>
                  <td className="actions-cell">
                    {u.id === user.id ? (
                      "—"
                    ) : editingId === u.id ? (
                      <>
                        <select value={pendingRole} onChange={(e) => setPendingRole(e.target.value)}>
                          <option value="analista">analista</option>
                          <option value="admin">admin</option>
                        </select>
                        {pendingRole !== u.role ? (
                          <button className="btn small primary" onClick={() => confirmRole(u)}>
                            Confirmar
                          </button>
                        ) : (
                          <button className="btn small" onClick={() => setEditingId(null)}>
                            Cancelar
                          </button>
                        )}
                      </>
                    ) : (
                      <button className="btn small" onClick={() => startEdit(u)}>
                        Cambiar rol
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2>Sesiones activas</h2>
        <p className="subtitle">
          Sesiones vigentes en Redis (una por login, expiran junto con su token) — se actualiza
          cada {SESSIONS_POLL_MS / 1000} s. Revocar una sesión invalida su token al instante.
          {sessions?.persistencia === "memoria" &&
            " Redis no está disponible: las sesiones son sin estado (solo JWT) y no se listan aquí."}
        </p>
        {sessionsError && <p className="error-msg">{sessionsError}</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Usuario</th>
                <th>Rol</th>
                <th>Iniciada</th>
                <th>Expira en</th>
                <th>Identificador (jti)</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {!sessions || sessions.sesiones.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    {sessions ? "No hay sesiones activas." : "Cargando sesiones…"}
                  </td>
                </tr>
              ) : (
                sessions.sesiones.map((s) => (
                  <tr key={s.jti}>
                    <td>
                      {s.username}
                      {s.jti === ownJti && (
                        <span className="badge debug" style={{ marginLeft: 8 }}>esta sesión</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge ${s.role === "admin" ? "debug" : "neutral"}`}>
                        {s.role}
                      </span>
                    </td>
                    <td className="mono">{formatTs(s.creado_en)}</td>
                    <td className="mono">{formatTtl(s.expira_en_segundos)}</td>
                    <td className="mono" title={s.jti}>{s.jti.slice(0, 12)}…</td>
                    <td className="actions-cell">
                      {s.jti === ownJti ? (
                        "—"
                      ) : (
                        <button className="btn small" onClick={() => revoke(s)}>
                          Revocar
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
    </div>
  );
}
