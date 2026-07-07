export default function AlertsPage() {
  return (
    <div className="card">
      <h2>Alertas activas</h2>
      <p className="subtitle">Ciclo de vida de incidentes por severidad</p>
      <p className="muted">
        El Alert Service aún no existe — se implementará junto con el motor de
        reglas del Analysis Service (Semana 8 en adelante). Cuando esté
        disponible, esta vista mostrará las alertas activas con su severidad y
        permitirá gestionarlas.
      </p>
      <div className="severity-row">
        <span className="badge info">BAJA</span>
        <span className="badge warning">MEDIA</span>
        <span className="badge error">ALTA</span>
        <span className="badge error">CRÍTICA</span>
      </div>
    </div>
  );
}
