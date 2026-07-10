import { Fragment, useEffect, useState } from "react";
import { createItem, deleteItem, fetchItems, updateItem } from "../api";
import { useToast } from "../toast";

const EMPTY_FORM = { name: "", description: "", price: "", is_offer: false };
const PROJECT_DOC_URL = "https://claude.ai/code/artifact/978ab0bf-f683-47fc-aaf5-bfd769d8f162";

function formatPrice(price) {
  return price.toLocaleString("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
}

// Mensajes de error específicos según la respuesta del Auth Service, en vez
// de un genérico "no se pudo". El detail del backend tiene prioridad cuando
// existe; los códigos comunes tienen traducción propia.
function apiErrorMessage(err, fallback) {
  const status = err.response?.status;
  const detail = err.response?.data?.detail;
  if (status === 401) return "Tu sesión expiró o fue revocada — cierra sesión y vuelve a entrar.";
  if (status === 403) return "Acción denegada: solo los administradores pueden editar o eliminar artículos.";
  if (status === 404) return "El artículo ya no existe en el inventario (puede que otro administrador lo haya eliminado).";
  if (status === 429) return "Demasiadas peticiones seguidas — espera unos segundos e intenta de nuevo.";
  if (typeof detail === "string") return detail;
  return fallback;
}

export default function ItemsPage({ user }) {
  const [items, setItems] = useState([]);
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState(null);
  const [editForm, setEditForm] = useState(EMPTY_FORM);
  const [expandedId, setExpandedId] = useState(null);
  const [confirmItem, setConfirmItem] = useState(null);
  const [deleting, setDeleting] = useState(false);
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

  // Cerrar el modal de confirmación con Escape
  useEffect(() => {
    if (!confirmItem) return;
    function onKey(e) {
      if (e.key === "Escape") setConfirmItem(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirmItem]);

  async function handleCreate(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const created = await createItem({
        name: form.name.trim(),
        description: form.description.trim() || null,
        price: parseFloat(form.price),
        is_offer: form.is_offer,
      });
      toast(`Artículo '${created.name}' creado con ID ${created.id} — ${formatPrice(created.price)}.`, "success");
      setForm(EMPTY_FORM);
      setShowForm(false);
      await load();
    } catch (err) {
      toast(apiErrorMessage(err, "No se pudo crear el artículo."), "error");
    } finally {
      setBusy(false);
    }
  }

  function startEdit(item) {
    setEditingId(item.id);
    setExpandedId(null);
    setEditForm({
      name: item.name,
      description: item.description || "",
      price: String(item.price),
      is_offer: item.is_offer,
    });
  }

  async function saveEdit(item) {
    try {
      const updated = await updateItem(item.id, {
        name: editForm.name.trim(),
        description: editForm.description.trim() || null,
        price: parseFloat(editForm.price),
        is_offer: editForm.is_offer,
      });
      // Detalle en el toast: qué campos cambiaron realmente
      const cambios = [];
      if (updated.name !== item.name) cambios.push(`nombre → '${updated.name}'`);
      if ((updated.description || "") !== (item.description || "")) cambios.push("descripción");
      if (updated.price !== item.price) cambios.push(`precio → ${formatPrice(updated.price)}`);
      if (updated.is_offer !== item.is_offer) cambios.push(updated.is_offer ? "marcado en oferta" : "quitado de oferta");
      toast(
        cambios.length
          ? `Artículo ID ${item.id} actualizado: ${cambios.join(", ")}.`
          : `Artículo ID ${item.id} guardado sin cambios.`,
        "success"
      );
      setEditingId(null);
      await load();
    } catch (err) {
      toast(apiErrorMessage(err, "No se pudo actualizar el artículo."), "error");
    }
  }

  async function confirmDelete() {
    const item = confirmItem;
    setDeleting(true);
    try {
      await deleteItem(item.id);
      toast(`Artículo '${item.name}' (ID ${item.id}, ${formatPrice(item.price)}) eliminado definitivamente del inventario.`, "success");
      setConfirmItem(null);
      setExpandedId(null);
      await load();
    } catch (err) {
      toast(apiErrorMessage(err, `No se pudo eliminar '${item.name}'.`), "error");
      setConfirmItem(null);
    } finally {
      setDeleting(false);
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
        <span className="muted" style={{ fontSize: "0.78rem" }}>
          Haz clic en una fila para ver el detalle del artículo
        </span>
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
                      <button className="btn small primary" onClick={() => saveEdit(item)}>
                        Guardar
                      </button>
                      <button className="btn small" onClick={() => setEditingId(null)}>
                        Cancelar
                      </button>
                    </td>
                  </tr>
                ) : (
                  <Fragment key={item.id}>
                    <tr
                      onClick={() => setExpandedId((id) => (id === item.id ? null : item.id))}
                      style={{ cursor: "pointer" }}
                    >
                      <td className="mono">{item.id}</td>
                      <td>{item.name}</td>
                      <td>{item.description || "—"}</td>
                      <td className="mono">{formatPrice(item.price)}</td>
                      <td>
                        {item.is_offer && <span className="badge warning">OFERTA</span>}
                      </td>
                      {isAdmin && (
                        <td className="actions-cell" onClick={(e) => e.stopPropagation()}>
                          <button className="btn small" onClick={() => startEdit(item)}>
                            Editar
                          </button>
                          <button className="btn small" onClick={() => setConfirmItem(item)}>
                            Eliminar
                          </button>
                        </td>
                      )}
                    </tr>
                    {expandedId === item.id && (
                      <tr className="detail-row">
                        <td colSpan={isAdmin ? 6 : 5}>
                          <div className="item-detail">
                            <div>
                              <span className="detail-label">ID</span>
                              <span className="mono">{item.id}</span>
                            </div>
                            <div>
                              <span className="detail-label">Nombre</span>
                              <span>{item.name}</span>
                            </div>
                            <div>
                              <span className="detail-label">Precio</span>
                              <span className="mono">{formatPrice(item.price)}</span>
                            </div>
                            <div>
                              <span className="detail-label">Estado</span>
                              <span>
                                {item.is_offer ? <span className="badge warning">OFERTA</span> : "Precio normal"}
                              </span>
                            </div>
                            <div>
                              <span className="detail-label">Creado por</span>
                              <span className="mono">usuario #{item.owner_id}</span>
                            </div>
                            <div className="full">
                              <span className="detail-label">Descripción completa</span>
                              <span>{item.description || "Sin descripción."}</span>
                            </div>
                            <div className="full detail-actions">
                              {isAdmin ? (
                                <>
                                  <button className="btn small" onClick={() => startEdit(item)}>
                                    Editar artículo
                                  </button>
                                  <button className="btn small" onClick={() => setConfirmItem(item)}>
                                    Eliminar artículo
                                  </button>
                                </>
                              ) : (
                                <span className="muted" style={{ fontSize: "0.78rem" }}>
                                  Solo los administradores pueden editar o eliminar artículos — tu cuenta tiene rol '{user.role}'.
                                </span>
                              )}
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              )
            )}
          </tbody>
        </table>
      </div>

      {confirmItem && (
        <div className="modal-overlay" onClick={() => setConfirmItem(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>¿Eliminar este artículo?</h3>
            <div className="item-summary">
              <div>
                <strong>{confirmItem.name}</strong>{" "}
                <span className="mono muted">· ID {confirmItem.id}</span>
              </div>
              <div className="muted">{confirmItem.description || "Sin descripción."}</div>
              <div>
                <span className="mono">{formatPrice(confirmItem.price)}</span>{" "}
                {confirmItem.is_offer && <span className="badge warning">OFERTA</span>}
              </div>
            </div>
            <p className="modal-warning">
              Se eliminará permanentemente del inventario (items_db) y quedará registrado en los
              logs de auditoría. Esta acción no se puede deshacer.
            </p>
            <div className="modal-actions">
              <button className="btn" onClick={() => setConfirmItem(null)} disabled={deleting}>
                Cancelar
              </button>
              <button className="btn danger" onClick={confirmDelete} disabled={deleting}>
                {deleting ? "Eliminando…" : "Sí, eliminar definitivamente"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
