import { useEffect, useState } from "react";
import { createItem, deleteItem, fetchItems, updateItem } from "../api";
import { useToast } from "../toast";

const EMPTY_FORM = { name: "", description: "", price: "", is_offer: false };
const PROJECT_DOC_URL = "https://claude.ai/code/artifact/978ab0bf-f683-47fc-aaf5-bfd769d8f162";

function formatPrice(price) {
  return price.toLocaleString("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
}

export default function ItemsPage({ user }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState(EMPTY_FORM);
  const toast = useToast();
  const isAdmin = user.role === "admin";

  async function load() {
    try {
      const data = await fetchItems({ limit: 100 });
      setItems(data);
      setError("");
    } catch {
      setError("No se pudo conectar con el Auth Service.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleCreate(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await createItem({
        name: form.name.trim(),
        description: form.description.trim() || null,
        price: parseFloat(form.price),
        is_offer: form.is_offer,
      });
      toast(`Artículo '${form.name.trim()}' creado.`, "success");
      setForm(EMPTY_FORM);
      setShowForm(false);
      await load();
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg = typeof detail === "string" ? detail : "No se pudo crear el artículo.";
      toast(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  function startEdit(item) {
    setEditingId(item.id);
    setEditForm({
      name: item.name,
      description: item.description || "",
      price: String(item.price),
      is_offer: item.is_offer,
    });
  }

  async function saveEdit(id) {
    try {
      await updateItem(id, {
        name: editForm.name.trim(),
        description: editForm.description.trim() || null,
        price: parseFloat(editForm.price),
        is_offer: editForm.is_offer,
      });
      toast("Artículo actualizado.", "success");
      setEditingId(null);
      await load();
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg = typeof detail === "string" ? detail : "No se pudo actualizar el artículo.";
      toast(msg, "error");
    }
  }

  async function handleDelete(item) {
    if (!window.confirm(`¿Eliminar el artículo '${item.name}'? Esta acción no se puede deshacer.`)) return;
    try {
      await deleteItem(item.id);
      toast(`Artículo '${item.name}' eliminado.`, "success");
      await load();
    } catch {
      toast(`No se pudo eliminar '${item.name}'.`, "error");
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <h2>Artículos</h2>
          <p className="subtitle">Inventario de ejemplo (CRUD protegido por rol) — creación abierta a cualquier cuenta, edición y borrado solo para administradores</p>
        </div>
        <a className="doc-link" href={PROJECT_DOC_URL} target="_blank" rel="noopener noreferrer">
          Ver documentación del proyecto ↗
        </a>
      </div>

      <div className="controls">
        <button className="btn" type="button" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Cancelar" : "Nuevo artículo"}
        </button>
        {error && <span className="error-msg">{error}</span>}
      </div>

      {showForm && (
        <form onSubmit={handleCreate} className="auth-form" style={{ marginBottom: 16 }}>
          <label>
            Nombre
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Auriculares Gamer"
              minLength={2}
              maxLength={50}
              required
            />
          </label>
          <label>
            Descripción
            <input
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Sonido 7.1 (opcional)"
              maxLength={200}
            />
          </label>
          <label>
            Precio (COP)
            <input
              type="number"
              value={form.price}
              onChange={(e) => setForm({ ...form, price: e.target.value })}
              placeholder="120000"
              min="0.01"
              step="0.01"
              required
            />
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={form.is_offer}
              onChange={(e) => setForm({ ...form, is_offer: e.target.checked })}
            />
            En oferta
          </label>
          <button className="btn primary" type="submit" disabled={busy}>
            {busy ? "Creando…" : "Crear artículo"}
          </button>
        </form>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Nombre</th>
              <th>Descripción</th>
              <th>Precio</th>
              <th>Oferta</th>
              {isAdmin && <th>Acciones</th>}
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td colSpan={isAdmin ? 6 : 5} className="muted">
                  No hay artículos registrados.
                </td>
              </tr>
            ) : (
              items.map((item) =>
                editingId === item.id ? (
                  <tr key={item.id}>
                    <td className="mono">{item.id}</td>
                    <td>
                      <input
                        value={editForm.name}
                        onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        value={editForm.description}
                        onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        value={editForm.price}
                        onChange={(e) => setEditForm({ ...editForm, price: e.target.value })}
                        min="0.01"
                        step="0.01"
                      />
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        checked={editForm.is_offer}
                        onChange={(e) => setEditForm({ ...editForm, is_offer: e.target.checked })}
                      />
                    </td>
                    <td className="actions-cell">
                      <button className="btn small primary" onClick={() => saveEdit(item.id)}>
                        Guardar
                      </button>
                      <button className="btn small" onClick={() => setEditingId(null)}>
                        Cancelar
                      </button>
                    </td>
                  </tr>
                ) : (
                  <tr key={item.id}>
                    <td className="mono">{item.id}</td>
                    <td>{item.name}</td>
                    <td>{item.description || "—"}</td>
                    <td className="mono">{formatPrice(item.price)}</td>
                    <td>
                      {item.is_offer && <span className="badge warning">OFERTA</span>}
                    </td>
                    {isAdmin && (
                      <td className="actions-cell">
                        <button className="btn small" onClick={() => startEdit(item)}>
                          Editar
                        </button>
                        <button className="btn small" onClick={() => handleDelete(item)}>
                          Eliminar
                        </button>
                      </td>
                    )}
                  </tr>
                )
              )
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
