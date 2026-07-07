import { useState } from "react";
import { fetchMe, login, register, setToken } from "../api";
import { useToast } from "../toast";
import Logo from "../logo";

function Requirement({ ok, children }) {
  return (
    <li className={ok ? "ok" : ""}>
      <span className="req-mark">{ok ? "✓" : "○"}</span> {children}
    </li>
  );
}

// Extrae el mensaje de error del backend (string en 400, lista de pydantic en 422)
function errorDetail(err, fallback) {
  const detail = err.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => String(d.msg || "").replace(/^Value error,\s*/, "")).join(" ");
  }
  return fallback;
}

export default function LoginPage({ onLogin }) {
  const toast = useToast();
  const [mode, setMode] = useState("login"); // 'login' | 'register'
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [serverError, setServerError] = useState("");

  // Especificaciones que exige el Auth Service (UserCreate)
  const userOk = username.trim().length >= 3 && username.trim().length <= 50;
  const emailOk = /\S+@\S+\.\S+/.test(email);
  const passOk = password.length >= 6;
  const distinctOk = new Set(password).size >= 3; // bloquea repetitivas: 111111, aaaaaa…
  const matchOk = confirm.length > 0 && password === confirm;
  const registerReady = userOk && emailOk && passOk && distinctOk && matchOk;

  function switchMode(next) {
    setMode(next);
    setPassword("");
    setConfirm("");
    setServerError("");
  }

  // Al editar cualquier campo se limpia el error del servidor anterior
  function field(setter) {
    return (e) => {
      setter(e.target.value);
      if (serverError) setServerError("");
    };
  }

  async function handleLogin(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await login(username, password);
      const me = await fetchMe();
      toast(`Bienvenido, ${me.username}.`, "success");
      onLogin(me);
    } catch (err) {
      setToken(null);
      toast(errorDetail(err, "No se pudo iniciar sesión. Verifica usuario y contraseña."), "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleRegister(e) {
    e.preventDefault();
    if (!registerReady) {
      toast("Revisa los requisitos del formulario antes de continuar.", "warning");
      return;
    }
    setBusy(true);
    setServerError("");
    try {
      await register(username.trim(), email.trim(), password);
      toast("Cuenta creada correctamente. Ahora inicia sesión.", "success");
      switchMode("login");
    } catch (err) {
      const msg = errorDetail(err, "No se pudo crear la cuenta. Revisa los datos.");
      setServerError(msg);
      toast(msg, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="centered login-bg">
      <div className="card login-card">
        <div className="login-brand">
          <span className="login-logo"><Logo size={30} /></span>
          <h1>SOC Dashboard</h1>
          <p className="hint">Plataforma de monitoreo de eventos de seguridad</p>
        </div>

        <div className="auth-tabs">
          <button
            type="button"
            className={mode === "login" ? "active" : ""}
            onClick={() => switchMode("login")}
          >
            Iniciar sesión
          </button>
          <button
            type="button"
            className={mode === "register" ? "active" : ""}
            onClick={() => switchMode("register")}
          >
            Crear cuenta
          </button>
        </div>

        {mode === "login" ? (
          <form onSubmit={handleLogin} className="auth-form">
            <label>
              Usuario
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                placeholder="admin"
                required
              />
            </label>
            <label>
              Contraseña
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                placeholder="••••••••"
                required
              />
            </label>
            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? "Entrando…" : "Iniciar sesión"}
            </button>
            <p className="hint">
              Entorno de prácticas — usuario semilla: <code>admin</code> / <code>admin123</code>
            </p>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="auth-form">
            <label>
              Usuario
              <input
                value={username}
                onChange={field(setUsername)}
                autoComplete="username"
                placeholder="nombre_usuario"
                required
              />
            </label>
            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={field(setEmail)}
                autoComplete="email"
                placeholder="tu@correo.com"
                required
              />
            </label>
            <label>
              Contraseña
              <input
                type="password"
                value={password}
                onChange={field(setPassword)}
                autoComplete="new-password"
                placeholder="mínimo 6 caracteres"
                required
              />
            </label>
            <label>
              Confirmar contraseña
              <input
                type="password"
                value={confirm}
                onChange={field(setConfirm)}
                autoComplete="new-password"
                placeholder="repite la contraseña"
                required
              />
            </label>

            <ul className="reqs">
              <Requirement ok={userOk}>Usuario de 3 a 50 caracteres (no puede estar ya registrado)</Requirement>
              <Requirement ok={emailOk}>Email con formato válido (no puede estar ya registrado)</Requirement>
              <Requirement ok={passOk}>Contraseña de mínimo 6 caracteres</Requirement>
              <Requirement ok={distinctOk}>Sin caracteres repetitivos (ej: 111111) — mínimo 3 distintos</Requirement>
              <Requirement ok={matchOk}>Las contraseñas coinciden</Requirement>
            </ul>

            {serverError && <p className="error-msg">{serverError}</p>}

            <button className="btn primary" type="submit" disabled={busy || !registerReady}>
              {busy ? "Creando cuenta…" : "Crear cuenta"}
            </button>
            <p className="hint">Las cuentas nuevas se crean con rol <code>user</code>.</p>
          </form>
        )}
      </div>
    </div>
  );
}
