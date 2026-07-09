import { useEffect, useState } from "react";
import { fetchUsers, updateUserRole } from "../api";
import { useToast } from "../toast";

function formatTs(ts) {
  return ts ? String(ts).replace("T", " ").substring(0, 19) : "—";
}

export default function UsersPage({ user }) {
  const [users, setUsers] = useState([]);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [pendingRole, setPendingRole] = useState("");
  const toast = useToast();

  useEffect(() => {
    fetchUsers()
      .then(setUsers)
      .catch((err) => {
        const detail = err.response?.data?.detail;
        setError(detail || "No se pudo obtener la lista de usuarios.");
      });
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

  return (
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
  );
}
