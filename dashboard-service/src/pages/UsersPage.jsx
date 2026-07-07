import { useEffect, useState } from "react";
import { fetchUsers } from "../api";

function formatTs(ts) {
  return ts ? String(ts).replace("T", " ").substring(0, 19) : "—";
}

export default function UsersPage() {
  const [users, setUsers] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchUsers()
      .then(setUsers)
      .catch((err) => {
        const detail = err.response?.data?.detail;
        setError(detail || "No se pudo obtener la lista de usuarios.");
      });
  }, []);

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
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
