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

export async function fetchUsers() {
  const { data } = await api.get("/api/auth/users");
  return data;
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

export default api;
