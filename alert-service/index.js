const express = require("express");
const os = require("os");
const amqp = require("amqplib");
const jwt = require("jsonwebtoken");
const { Client, Pool } = require("pg");

const PORT = process.env.PORT || 8003;
const START_TIME = Date.now();

// Logging operacional del propio proceso — un objeto JSON por línea en
// stdout, mismo formato que los 3 servicios Python del proyecto.
function logEvent(level, category, message) {
  console.log(JSON.stringify({
    timestamp: new Date().toISOString(),
    service: "alert-service",
    level,
    category,
    message,
  }));
}

// Misma clave y algoritmo que auth-service (create_access_token en app.py) —
// alert-service no emite tokens, solo verifica los que auth-service firmó.
const JWT_SECRET_KEY = process.env.JWT_SECRET_KEY || "changeme-super-secret-key-for-jwt-in-production";
const JWT_ALGORITHM = "HS256";

const POSTGRES_HOST = process.env.POSTGRES_HOST || "localhost";
const POSTGRES_PORT = parseInt(process.env.POSTGRES_PORT || "5432", 10);
const POSTGRES_USER = process.env.POSTGRES_USER || "postgres";
const POSTGRES_PASSWORD = process.env.POSTGRES_PASSWORD || "postgres";
const ALERTS_DB = "alerts_db";

const RABBITMQ_HOST = process.env.RABBITMQ_HOST || "localhost";
const RABBITMQ_PORT = parseInt(process.env.RABBITMQ_PORT || "5672", 10);
const RABBITMQ_USER = process.env.RABBITMQ_USER || "guest";
const RABBITMQ_PASSWORD = process.env.RABBITMQ_PASSWORD || "guest";

const ALERTS_EXCHANGE = "alerts_events";
const ALERTS_QUEUE = "alerts_queue";
const BINDING_KEY = "alerts.#";

// Ciclo de vida de un incidente: nueva → reconocida → cerrada.
const VALID_STATUSES = ["nueva", "reconocida", "cerrada"];

// Pool hacia alerts_db; es null hasta que el aprovisionamiento termina — los
// endpoints de alertas responden 503 mientras tanto (/api/health no depende).
let pool = null;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// --- Aprovisionamiento de PostgreSQL ---

// Espejo de _wait_for_postgres() del auth-service: reintenta la conexión a la
// base de mantenimiento 'postgres' hasta que el servidor acepte conexiones.
async function waitForPostgres(retries = 15, delayMs = 2000) {
  for (let attempt = 1; attempt <= retries; attempt++) {
    const client = new Client({
      host: POSTGRES_HOST,
      port: POSTGRES_PORT,
      user: POSTGRES_USER,
      password: POSTGRES_PASSWORD,
      database: "postgres",
    });
    try {
      await client.connect();
      logEvent("INFO", "DB", `Conectado a PostgreSQL en ${POSTGRES_HOST}:${POSTGRES_PORT}`);
      return client;
    } catch (err) {
      await client.end().catch(() => {});
      if (attempt === retries) throw err;
      logEvent("INFO", "DB", `Esperando a PostgreSQL... (intento ${attempt}/${retries})`);
      await sleep(delayMs);
    }
  }
}

// Crea alerts_db si no existe. Necesario porque el script de postgres-init/
// solo corre en el PRIMER arranque del volumen postgres_data — en instalaciones
// existentes la base no está y el servicio debe autoaprovisionarse.
async function ensureDatabase(client) {
  const { rows } = await client.query("SELECT 1 FROM pg_database WHERE datname = $1", [ALERTS_DB]);
  if (rows.length === 0) {
    await client.query(`CREATE DATABASE ${ALERTS_DB}`);
    logEvent("INFO", "DB", `Base de datos '${ALERTS_DB}' creada.`);
  }
  await client.end();
}

async function ensureSchema() {
  const alertsPool = new Pool({
    host: POSTGRES_HOST,
    port: POSTGRES_PORT,
    user: POSTGRES_USER,
    password: POSTGRES_PASSWORD,
    database: ALERTS_DB,
  });
  await alertsPool.query(`
    CREATE TABLE IF NOT EXISTS alerts (
      id SERIAL PRIMARY KEY,
      rule_id TEXT NOT NULL,
      rule_name TEXT NOT NULL,
      rule_type TEXT NOT NULL,
      severity TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'nueva',
      service TEXT,
      message TEXT NOT NULL,
      triggering_event JSONB,
      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
  `);
  logEvent("INFO", "DB", `Tabla 'alerts' lista en '${ALERTS_DB}'.`);
  return alertsPool;
}

// --- Consumidor de RabbitMQ ---

// Bucle del consumidor: conecta, declara exchange/cola y persiste cada alerta
// en Postgres. Si la conexión se cae, reintenta desde cero (mismo patrón que
// _consume_loop() del analysis-service).
async function consumeLoop() {
  for (;;) {
    try {
      const connection = await amqp.connect({
        protocol: "amqp",
        hostname: RABBITMQ_HOST,
        port: RABBITMQ_PORT,
        username: RABBITMQ_USER,
        password: RABBITMQ_PASSWORD,
        heartbeat: 60,
      });
      logEvent("INFO", "RABBITMQ", `Conectado a RabbitMQ en ${RABBITMQ_HOST}:${RABBITMQ_PORT}`);
      const channel = await connection.createChannel();
      await channel.assertExchange(ALERTS_EXCHANGE, "topic", { durable: true });
      await channel.assertQueue(ALERTS_QUEUE, { durable: true });
      await channel.bindQueue(ALERTS_QUEUE, ALERTS_EXCHANGE, BINDING_KEY);
      await channel.prefetch(10);
      logEvent("INFO", "RABBITMQ", `Consumiendo de la cola '${ALERTS_QUEUE}' (binding '${BINDING_KEY}')`);

      // La promesa solo se rechaza cuando la conexión muere — mantiene vivo
      // el bucle y dispara la reconexión del catch.
      await new Promise((_, reject) => {
        connection.on("error", (err) => reject(err));
        connection.on("close", () => reject(new Error("conexión cerrada")));
        channel.consume(ALERTS_QUEUE, async (msg) => {
          if (!msg) return;
          let alert;
          try {
            alert = JSON.parse(msg.content.toString());
          } catch {
            logEvent("WARNING", "ALERTAS", `Mensaje descartado (JSON inválido): ${msg.content.toString().slice(0, 200)}`);
            channel.ack(msg);
            return;
          }
          try {
            await pool.query(
              `INSERT INTO alerts (rule_id, rule_name, rule_type, severity, service, message, triggering_event)
               VALUES ($1, $2, $3, $4, $5, $6, $7)`,
              [
                alert.rule_id || "desconocida",
                alert.rule_name || "Regla desconocida",
                alert.rule_type || "desconocido",
                alert.severity || "baja",
                alert.service || null,
                alert.message || "",
                alert.triggering_event ? JSON.stringify(alert.triggering_event) : null,
              ]
            );
            logEvent("INFO", "ALERTAS", `Alerta persistida (${String(alert.severity).toUpperCase()}): ${alert.message}`);
            channel.ack(msg);
          } catch (err) {
            // Sin ack: el mensaje vuelve a la cola y se reintenta.
            logEvent("ERROR", "ALERTAS", `Error al insertar en Postgres: ${err.message}`);
            channel.nack(msg, false, true);
          }
        });
      });
    } catch (err) {
      logEvent("ERROR", "RABBITMQ", `Conexión perdida (${err.message}); reintentando en 3s...`);
      await sleep(3000);
    }
  }
}

// --- API REST ---

const app = express();
app.use(express.json());

// Responde 503 mientras el aprovisionamiento de Postgres no haya terminado.
function requireDb(req, res, next) {
  if (!pool) {
    return res.status(503).json({ detail: "El Alert Service aún está inicializando la base de datos." });
  }
  next();
}

// Verifica el JWT emitido por auth-service y exige rol admin — solo para el
// endpoint que modifica el ciclo de vida de una alerta (PATCH). Las lecturas
// (GET /alerts, /alerts/stats) siguen abiertas, mismo criterio que
// log-service/analysis-service: el dashboard ya oculta estos botones a
// usuarios no-admin, pero eso no impedía llamar el PATCH directo por HTTP.
function requireAdmin(req, res, next) {
  const authHeader = req.headers.authorization || "";
  const [scheme, token] = authHeader.split(" ");
  if (scheme !== "Bearer" || !token) {
    return res.status(401).json({ detail: "Token de autenticación requerido." });
  }
  try {
    const payload = jwt.verify(token, JWT_SECRET_KEY, { algorithms: [JWT_ALGORITHM] });
    if (payload.role !== "admin") {
      return res.status(403).json({ detail: "Esta acción requiere rol admin." });
    }
    req.user = payload;
    next();
  } catch (err) {
    return res.status(401).json({ detail: "Token inválido o expirado." });
  }
}

app.get("/api/health", (req, res) => {
  res.json({
    status: "healthy",
    uptime_seconds: Math.round((Date.now() - START_TIME) / 1000),
    platform: `${os.type()}-${os.release()}-${os.arch()}`,
    node_version: process.version,
  });
});

// Lista de alertas, más recientes primero. Filtros opcionales: severity, status.
app.get("/alerts", requireDb, async (req, res) => {
  try {
    const { severity, status } = req.query;
    const limit = Math.min(parseInt(req.query.limit, 10) || 100, 500);
    const conditions = [];
    const params = [];
    if (severity) {
      params.push(severity);
      conditions.push(`severity = $${params.length}`);
    }
    if (status) {
      params.push(status);
      conditions.push(`status = $${params.length}`);
    }
    const where = conditions.length > 0 ? `WHERE ${conditions.join(" AND ")}` : "";
    params.push(limit);
    const { rows } = await pool.query(
      `SELECT * FROM alerts ${where} ORDER BY created_at DESC, id DESC LIMIT $${params.length}`,
      params
    );
    res.json(rows);
  } catch (err) {
    logEvent("ERROR", "API", `Error consultando alertas: ${err.message}`);
    res.status(500).json({ detail: "Error interno consultando las alertas." });
  }
});

// Conteos agregados por severidad y por estado.
app.get("/alerts/stats", requireDb, async (req, res) => {
  try {
    const [total, bySeverity, byStatus] = await Promise.all([
      pool.query("SELECT COUNT(*)::int AS total FROM alerts"),
      pool.query("SELECT severity, COUNT(*)::int AS total FROM alerts GROUP BY severity"),
      pool.query("SELECT status, COUNT(*)::int AS total FROM alerts GROUP BY status"),
    ]);
    res.json({
      total_alertas: total.rows[0].total,
      por_severidad: Object.fromEntries(bySeverity.rows.map((r) => [r.severity, r.total])),
      por_estado: Object.fromEntries(byStatus.rows.map((r) => [r.status, r.total])),
    });
  } catch (err) {
    logEvent("ERROR", "API", `Error consultando estadísticas: ${err.message}`);
    res.status(500).json({ detail: "Error interno consultando las estadísticas." });
  }
});

// Cambia el estado de una alerta (ciclo de vida del incidente).
// Requiere JWT válido con rol admin (ver requireAdmin) — es el único endpoint
// de este servicio que modifica datos, por eso es el único que exige token;
// las lecturas (GET) siguen abiertas, igual que en log-service/analysis-service.
app.patch("/alerts/:id", requireDb, requireAdmin, async (req, res) => {
  const { status } = req.body || {};
  if (!VALID_STATUSES.includes(status)) {
    return res.status(400).json({ detail: `Estado inválido. Valores permitidos: ${VALID_STATUSES.join(", ")}.` });
  }
  const id = parseInt(req.params.id, 10);
  if (Number.isNaN(id)) {
    return res.status(400).json({ detail: "El id de la alerta debe ser numérico." });
  }
  try {
    const { rows } = await pool.query(
      "UPDATE alerts SET status = $1, updated_at = NOW() WHERE id = $2 RETURNING *",
      [status, id]
    );
    if (rows.length === 0) {
      return res.status(404).json({ detail: `No existe una alerta con id ${id}.` });
    }
    res.json(rows[0]);
  } catch (err) {
    logEvent("ERROR", "API", `Error actualizando la alerta ${id}: ${err.message}`);
    res.status(500).json({ detail: "Error interno actualizando la alerta." });
  }
});

// --- Arranque ---

// Express escucha de inmediato (así /api/health responde desde el primer
// segundo); el aprovisionamiento de Postgres y el consumidor corren detrás.
app.listen(PORT, () => {
  logEvent("INFO", "STARTUP", `alert-service escuchando en el puerto ${PORT}`);
});

(async () => {
  try {
    const maintenanceClient = await waitForPostgres();
    await ensureDatabase(maintenanceClient);
    pool = await ensureSchema();
    consumeLoop();
  } catch (err) {
    logEvent("ERROR", "STARTUP", `Error fatal en el arranque: ${err.message}`);
    process.exit(1);
  }
})();
