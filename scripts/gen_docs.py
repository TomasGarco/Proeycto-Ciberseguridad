"""
Genera automáticamente las tablas de referencia técnica (endpoints, modelos
Pydantic, columnas ORM, variables de configuración) a partir del código real
de auth-service/app.py y log-service/app.py, usando el módulo `ast` (parseo
estático, sin importar los archivos — evitan así los efectos secundarios de
conexión a Postgres/MongoDB que ocurren al importar esos módulos).

Uso:
    python scripts/gen_docs.py            # regenera docs/AUTH_SERVICE_ARCHITECTURE.md
    python scripts/gen_docs.py --check    # no escribe, sale con código 1 si hay drift
"""
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
MARKER_START = "<!-- AUTO-GENERATED:START:{id} -->"
MARKER_END = "<!-- AUTO-GENERATED:END:{id} -->"


def parse_module(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return ast.unparse(node)


def extract_endpoints(tree: ast.Module) -> list[dict]:
    endpoints = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
                    and func.value.id == "app" and func.attr in HTTP_METHODS):
                continue
            if not dec.args:
                continue
            path_arg = dec.args[0]
            path_str = path_arg.value if isinstance(path_arg, ast.Constant) else ast.unparse(path_arg)
            kwargs = {kw.arg: _literal(kw.value) for kw in dec.keywords if kw.arg}
            if kwargs.get("include_in_schema") is False:
                continue
            summary = kwargs.get("summary")
            if not summary:
                doc = ast.get_docstring(node)
                summary = doc.strip().splitlines()[0] if doc else ""
            endpoints.append({
                "method": dec.func.attr.upper(),
                "path": path_str,
                "tags": kwargs.get("tags", []),
                "summary": summary,
                "function": node.name,
            })
    return endpoints


def extract_pydantic_models(tree: ast.Module) -> list[dict]:
    models = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        if "BaseModel" not in bases:
            continue
        fields = []
        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            field_name = stmt.target.id
            type_str = ast.unparse(stmt.annotation)
            constraints = {}
            default = None
            if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "Field":
                for kw in stmt.value.keywords:
                    if kw.arg:
                        constraints[kw.arg] = _literal(kw.value)
                if stmt.value.args and not (isinstance(stmt.value.args[0], ast.Constant) and stmt.value.args[0].value is Ellipsis):
                    default = _literal(stmt.value.args[0])
            elif stmt.value is not None:
                default = _literal(stmt.value)
            fields.append({"name": field_name, "type": type_str, "constraints": constraints, "default": default})
        models.append({"name": node.name, "fields": fields})
    return models


def extract_orm_models(tree: ast.Module) -> list[dict]:
    models = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
        if not any(b.endswith("Base") for b in bases):
            continue
        tablename = None
        columns = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                name = stmt.targets[0].id
                if name == "__tablename__" and isinstance(stmt.value, ast.Constant):
                    tablename = stmt.value.value
                    continue
                if isinstance(stmt.value, ast.Call) and isinstance(stmt.value.func, ast.Name) and stmt.value.func.id == "Column":
                    col_type = ast.unparse(stmt.value.args[0]) if stmt.value.args else "?"
                    constraints = {kw.arg: _literal(kw.value) for kw in stmt.value.keywords if kw.arg}
                    columns.append({"name": name, "type": col_type, "constraints": constraints})
        if columns:
            models.append({"name": node.name, "tablename": tablename, "columns": columns})
    return models


# Nombres de variables que sí son configuración de infraestructura (secreto,
# conexión, timeouts). Todo lo demás en mayúsculas a nivel de módulo (CSS,
# SVG, favicons embebidos como strings) se ignora explícitamente: son
# constantes de presentación, no configuración.
CONFIG_VAR_ALLOWLIST_SUFFIXES = ("_HOST", "_PORT", "_USER", "_PASSWORD", "_URL", "_KEY",
                                  "_DATABASE", "_USERNAME", "ALGORITHM", "_MINUTES", "_SECONDS")


def extract_config_vars(tree: ast.Module) -> list[dict]:
    configs = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        name = node.targets[0].id
        if not name.isupper() or not any(name.endswith(s) or name == s for s in CONFIG_VAR_ALLOWLIST_SUFFIXES):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "getenv":
            env_args = [_literal(a) for a in value.args]
            env_name = env_args[0] if env_args else name
            default = env_args[1] if len(env_args) > 1 else None
            configs.append({"name": name, "source": "env", "env_var": env_name, "default": default})
        elif isinstance(value, ast.Constant) and (value.value is None or isinstance(value.value, (str, int, float, bool))):
            configs.append({"name": name, "source": "hardcoded", "default": value.value})
    return configs


def render_endpoint_table(endpoints: list[dict]) -> str:
    lines = ["| Método | Ruta | Tags | Función | Resumen |", "|---|---|---|---|---|"]
    for e in endpoints:
        tags = ", ".join(e["tags"]) if e["tags"] else ""
        lines.append(f"| `{e['method']}` | `{e['path']}` | {tags} | `{e['function']}()` | {e['summary']} |")
    return "\n".join(lines)


def render_pydantic_tables(models: list[dict]) -> str:
    blocks = []
    for m in models:
        lines = [f"**`{m['name']}`**", "", "| Campo | Tipo | Restricciones | Default |", "|---|---|---|---|"]
        for f in m["fields"]:
            constraints = ", ".join(f"{k}={v}" for k, v in f["constraints"].items() if k not in ("example",)) or "-"
            default = f["default"] if f["default"] is not None else "-"
            lines.append(f"| {f['name']} | `{f['type']}` | {constraints} | {default} |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_orm_tables(models: list[dict]) -> str:
    blocks = []
    for m in models:
        lines = [f"**`{m['name']}`** (tabla `{m['tablename']}`)", "", "| Columna | Tipo | Restricciones |", "|---|---|---|"]
        for c in m["columns"]:
            constraints = ", ".join(f"{k}={v}" for k, v in c["constraints"].items()) or "-"
            lines.append(f"| {c['name']} | `{c['type']}` | {constraints} |")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_config_table(configs: list[dict]) -> str:
    lines = ["| Variable | Origen | Env var | Default |", "|---|---|---|---|"]
    for c in configs:
        if c["source"] == "env":
            lines.append(f"| `{c['name']}` | variable de entorno | `{c['env_var']}` | `{c['default']}` |")
        else:
            lines.append(f"| `{c['name']}` | **hardcoded en el código** | - | `{c['default']}` |")
    return "\n".join(lines)


def inject_into_doc(doc_path: Path, fragments: dict[str, str]) -> bool:
    text = doc_path.read_text(encoding="utf-8")
    changed = False
    for marker_id, fragment in fragments.items():
        start = MARKER_START.format(id=marker_id)
        end = MARKER_END.format(id=marker_id)
        start_idx = text.find(start)
        end_idx = text.find(end)
        if start_idx == -1 or end_idx == -1:
            print(f"[gen_docs] ADVERTENCIA: marcador '{marker_id}' no encontrado en {doc_path.name}, se omite.")
            continue
        before = text[:start_idx + len(start)]
        after = text[end_idx:]
        new_block = f"{before}\n{fragment}\n{after}"
        if new_block != text[:len(new_block)] or True:
            replaced = text[:start_idx + len(start)] + "\n" + fragment + "\n" + text[end_idx:]
            if replaced != text:
                changed = True
            text = replaced
    doc_path.write_text(text, encoding="utf-8")
    return changed


def build_fragments(auth_tree, log_tree) -> dict[str, str]:
    return {
        "auth-config": render_config_table(extract_config_vars(auth_tree)),
        "auth-orm": render_orm_tables(extract_orm_models(auth_tree)),
        "auth-pydantic": render_pydantic_tables(extract_pydantic_models(auth_tree)),
        "auth-endpoints": render_endpoint_table(extract_endpoints(auth_tree)),
        "log-endpoints": render_endpoint_table(extract_endpoints(log_tree)),
    }


def main():
    check_only = "--check" in sys.argv

    auth_tree = parse_module(REPO_ROOT / "auth-service" / "app.py")
    log_tree = parse_module(REPO_ROOT / "log-service" / "app.py")
    fragments = build_fragments(auth_tree, log_tree)

    doc_path = REPO_ROOT / "docs" / "AUTH_SERVICE_ARCHITECTURE.md"
    original = doc_path.read_text(encoding="utf-8")

    if check_only:
        candidate = original
        for marker_id, fragment in fragments.items():
            start = MARKER_START.format(id=marker_id)
            end = MARKER_END.format(id=marker_id)
            start_idx = candidate.find(start)
            end_idx = candidate.find(end)
            if start_idx == -1 or end_idx == -1:
                continue
            candidate = candidate[:start_idx + len(start)] + "\n" + fragment + "\n" + candidate[end_idx:]
        if candidate != original:
            print("[gen_docs] La documentación está desactualizada respecto al código. Corré: python scripts/gen_docs.py")
            sys.exit(1)
        print("[gen_docs] OK — la documentación coincide con el código.")
        return

    changed = inject_into_doc(doc_path, fragments)
    print(f"[gen_docs] {'Actualizado' if changed else 'Sin cambios'}: {doc_path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
