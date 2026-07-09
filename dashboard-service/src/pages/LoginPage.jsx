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

const EYE_OPEN = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8Z" />
    <circle cx="12" cy="12" r="3" />
  </svg>
);

const EYE_CLOSED = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M17.94 17.94A10.94 10.94 0 0 1 12 20c-7 0-11-8-11-8a20.3 20.3 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a20.3 20.3 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </svg>
);

function PasswordField({ label, value, onChange, autoComplete, placeholder, error }) {
  const [visible, setVisible] = useState(false);
  return (
    <label>
      {label}
      <span className="pass-field">
        <input
          type={visible ? "text" : "password"}
          value={value}
          onChange={onChange}
          autoComplete={autoComplete}
          placeholder={placeholder}
          required
        />
        <button
          type="button"
          className="pass-toggle"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
        >
          {visible ? EYE_CLOSED : EYE_OPEN}
        </button>
      </span>
      {error && <span className="field-error">{error}</span>}
    </label>
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

// Errores 422 de FastAPI/Pydantic anclados a su campo: detail es una lista de
// {loc: ["body", "password"], msg: "..."} — se toma el último elemento de loc.
function fieldErrorsFromResponse(err) {
  const detail = err.response?.data?.detail;
  if (!Array.isArray(detail)) return {};
  const errors = {};
  for (const d of detail) {
    const campo = Array.isArray(d.loc) ? d.loc[d.loc.length - 1] : null;
    if (campo) errors[campo] = String(d.msg || "").replace(/^Value error,\s*/, "");
  }
  return errors;
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
  const [fieldErrors, setFieldErrors] = useState({});

  // Especificaciones que exige el Auth Service (UserCreate / _validar_password)
  const userOk = username.trim().length >= 3 && username.trim().length <= 50;
  const emailOk = /\S+@\S+\.\S+/.test(email);
  const lengthOk = password.length >= 8;
  const upperOk = /[A-Z]/.test(password);
  const lowerOk = /[a-z]/.test(password);
  const numberOk = /[0-9]/.test(password);
  const distinctOk = new Set(password).size >= 3; // bloquea repetitivas: 11111111, aaaaaaaa…
  const matchOk = confirm.length > 0 && password === confirm;
  const registerReady = userOk && emailOk && lengthOk && upperOk && lowerOk && numberOk && distinctOk && matchOk;

  function switchMode(next) {
    setMode(next);
    setPassword("");
    setConfirm("");
    setServerError("");
    setFieldErrors({});
  }

  // Al editar cualquier campo se limpia su error de servidor y el mensaje agregado
  function field(setter, campo) {
    return (e) => {
      setter(e.target.value);
      if (serverError) setServerError("");
      if (campo && fieldErrors[campo]) {
        setFieldErrors((prev) => {
          const next = { ...prev };
          delete next[campo];
          return next;
        });
      }
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
    setFieldErrors({});
    try {
      await register(username.trim(), email.trim(), password);
      toast("Cuenta creada correctamente. Ahora inicia sesión.", "success");
      switchMode("login");
    } catch (err) {
      const msg = errorDetail(err, "No se pudo crear la cuenta. Revisa los datos.");
      setServerError(msg);
      setFieldErrors(fieldErrorsFromResponse(err));
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
            <PasswordField
              label="Contraseña"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              placeholder="••••••••"
            />
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
                onChange={field(setUsername, "username")}
                autoComplete="username"
                placeholder="nombre_usuario"
                required
              />
              {fieldErrors.username && <span className="field-error">{fieldErrors.username}</span>}
            </label>
            <label>
              Email
              <input
                type="email"
                value={email}
                onChange={field(setEmail, "email")}
                autoComplete="email"
                placeholder="tu@correo.com"
                required
              />
              {fieldErrors.email && <span className="field-error">{fieldErrors.email}</span>}
            </label>
            <PasswordField
              label="Contraseña"
              value={password}
              onChange={field(setPassword, "password")}
              autoComplete="new-password"
              placeholder="mínimo 8 caracteres"
              error={fieldErrors.password}
            />
            <PasswordField
              label="Confirmar contraseña"
              value={confirm}
              onChange={field(setConfirm)}
              autoComplete="new-password"
              placeholder="repite la contraseña"
            />

            <ul className="reqs">
              <Requirement ok={userOk}>Usuario de 3 a 50 caracteres (no puede estar ya registrado)</Requirement>
              <Requirement ok={emailOk}>Email con formato válido (no puede estar ya registrado)</Requirement>
              <Requirement ok={lengthOk}>Contraseña de mínimo 8 caracteres</Requirement>
              <Requirement ok={upperOk}>Al menos una letra mayúscula</Requirement>
              <Requirement ok={lowerOk}>Al menos una letra minúscula</Requirement>
              <Requirement ok={numberOk}>Al menos un número</Requirement>
              <Requirement ok={distinctOk}>Sin caracteres repetitivos (ej: 11111111) — mínimo 3 distintos</Requirement>
              <Requirement ok={matchOk}>Las contraseñas coinciden</Requirement>
            </ul>

            {serverError && <p className="error-msg">{serverError}</p>}

            <button className="btn primary" type="submit" disabled={busy || !registerReady}>
              {busy ? "Creando cuenta…" : "Crear cuenta"}
            </button>
            <p className="hint">Las cuentas nuevas se crean con rol <code>analista</code>.</p>
          </form>
        )}
      </div>
    </div>
  );
}
