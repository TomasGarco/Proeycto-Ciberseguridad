import axios from "axios";

// Todas las rutas pasan por /api/* — nginx (producción) o el proxy de Vite
// (desarrollo) las redirigen al microservicio correspondiente.
const api = axios.create();

export function getToken() {
  return localStorage.getItem("token");
}

export function setToken(token) {
  if (token) {
    localStorage.setItem("token", token);
  } else {
    localStorage.removeItem("token");
  }
}

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Payload del JWT guardado (sub, role, jti...), decodificado en el cliente.
// Solo lectura de datos no sensibles — la validez del token la decide el
// backend contra su firma y la sesión en Redis.
export function getTokenPayload() {
  const token = getToken();
  if (!token) return null;
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

// --- Auth Service ---

export async function login(username, password) {
  // /auth/login usa OAuth2PasswordRequestForm: espera form-urlencoded
  const body = new URLSearchParams({ username, password });
  const { data } = await api.post("/api/auth/login", body);
  setToken(data.access_token);
  return data;
}

export async function register(username, email, password) {
  const { data } = await api.post("/api/auth/register", { username, email, password });
  return data;
}

export async function fetchMe() {
  const { data } = await api.get("/api/auth/me");
  return data;
}

export async function logout() {
  // Revoca la sesión en el servidor (Redis) antes de descartar el token local;
  // si el backend no responde, igual se cierra la sesión del lado del cliente.
  try {
    await api.post("/api/auth/logout");
  } catch {
    /* el token se descarta abajo de todas formas */
  }
  setToken(null);
}

export async function fetchUsers() {
  const { data } = await api.get("/api/auth/users");
  return data;
}

export async function updateUserRole(userId, role) {
  const { data } = await api.patch(`/api/auth/users/${userId}/role`, { role });
  return data;
}

export async function fetchSessions() {
  const { data } = await api.get("/api/auth/sessions");
  return data;
}

export async function revokeSession(jti) {
  const { data } = await api.delete(`/api/auth/sessions/${jti}`);
  return data;
}

// --- Items (Auth Service) ---

export async function fetchItems({ skip = 0, limit = 100 } = {}) {
  const { data } = await api.get("/api/items", { params: { skip, limit } });
  return data;
}

export async function createItem({ name, description, price, is_offer }) {
  const { data } = await api.post("/api/items", { name, description, price, is_offer });
  return data;
}

export async function updateItem(id, payload) {
  const { data } = await api.put(`/api/items/${id}`, payload);
  return data;
}

export async function deleteItem(id) {
  await api.delete(`/api/items/${id}`);
}

// --- Log Service ---

export async function fetchLogs({ limit = 100, level = "", service = "" } = {}) {
  const params = { limit };
  if (level) params.level = level;
  if (service) params.service = service;
  const { data } = await api.get("/api/logs", { params });
  return data;
}

// --- Analysis Service ---

export async function fetchStats() {
  const { data } = await api.get("/api/analysis/stats");
  return data;
}

export async function fetchRecentEvents(limit = 20) {
  const { data } = await api.get("/api/analysis/events/recent", { params: { limit } });
  return data;
}

export async function fetchRules() {
  const { data } = await api.get("/api/analysis/rules");
  return data;
}

export async function updateRule(id, enabled) {
  const { data } = await api.patch(`/api/analysis/rules/${id}`, { enabled });
  return data;
}

// --- Alert Service ---

export async function fetchAlerts({ limit = 100, severity = "", status = "" } = {}) {
  const params = { limit };
  if (severity) params.severity = severity;
  if (status) params.status = status;
  const { data } = await api.get("/api/alerts", { params });
  return data;
}

export async function fetchAlertStats() {
  const { data } = await api.get("/api/alerts/stats");
  return data;
}

export async function updateAlertStatus(id, status) {
  const { data } = await api.patch(`/api/alerts/${id}`, { status });
  return data;
}

export default api;
