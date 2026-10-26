#!/usr/bin/env python3
"""
mgeller.py — motor determinista de la skill MGeller (mgeller-change-integrity).

Hace lo que conviene que NO dependa del criterio del agente: inventariar el producto de
datos, encontrar cada referencia a un término, reconstruir el cambio desde Git, validar la
sintaxis y las referencias cruzadas, y entregar a Git con salvaguardas. Las decisiones
(qué corregir, qué fuente manda) las toma el agente siguiendo SKILL.md.

Solo usa la biblioteca estándar. PyYAML es opcional: si no está, los YAML se reportan como
NO_VERIFICADO en lugar de darse por válidos.

Subcomandos (todos aceptan --json para salida legible por máquina):
    inventario      artefactos del producto y grafo tabla/notebook/job
    cambios         cambio reconstruido desde Git o contra una copia de referencia
    impacto         todas las apariciones de uno o más términos, con su contexto
    validar         JSON, YAML, Python/notebooks, bundle, diccionario vs DDL, obsoletos
    uc-sql          SQL de solo lectura para leer la metadata de Unity Catalog
    contrastar-uc   compara la metadata exportada de UC con diccionarios y DDL
    secretos        busca secretos en archivos (nunca imprime el valor)
    git-estado      rama, remoto, cambios y línea base de cambios preexistentes
    git-entregar    commit (y push opcional) solo de los archivos del alcance

Códigos de salida: 0 = sin errores, 1 = hallazgos de severidad error o entrega rechazada,
2 = uso incorrecto o entorno no apto.
"""
from __future__ import annotations

import argparse
import ast
import base64
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    import yaml  # type: ignore

    HAY_YAML = True
except Exception:  # pragma: no cover - depende del entorno
    yaml = None
    HAY_YAML = False

VERSION = "1.0.0"

# --------------------------------------------------------------------------------------
# Clasificación de archivos
# --------------------------------------------------------------------------------------

DIRS_EXCLUIDOS = {
    ".git", "__pycache__", ".venv", "venv", "env", "node_modules", ".databricks",
    ".ipynb_checkpoints", ".pytest_cache", ".mypy_cache", ".ruff_cache", "build", "dist",
    ".idea", ".vscode",
}
# Archivos cuyo contenido no se lee ni se versiona desde MGeller.
PATRONES_SENSIBLES = [
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "*.jks", "id_rsa*", "id_ed25519*",
    "credentials*.json", "token*.json", "secret*.json", "secret*.yml", "secret*.yaml",
    "secrets*", ".databrickscfg", ".netrc", "*.keystore",
]
PERMITIDOS_AUNQUE_PAREZCAN = {".env.example"}

EXT_TEXTO = {
    ".py", ".sql", ".scala", ".r", ".ipynb", ".json", ".yml", ".yaml", ".md", ".txt",
    ".toml", ".cfg", ".ini", ".csv", ".sh", ".ps1", ".html", ".rst", ".conf",
}
NOMBRES_DEPENDENCIAS = {"requirements.txt", "pyproject.toml", "setup.py", "setup.cfg",
                        "environment.yml", "poetry.lock", "uv.lock"}

CABECERAS_NOTEBOOK = {
    "# Databricks notebook source": "python",
    "-- Databricks notebook source": "sql",
    "// Databricks notebook source": "scala",
}
SEPARADOR_CELDA = re.compile(r"^\s*(#|--|//) COMMAND -{5,}\s*$")
PREFIJO_MAGIC = re.compile(r"^\s*(#|--|//) MAGIC ?")


def es_sensible(ruta: Path) -> bool:
    nombre = ruta.name
    if nombre in PERMITIDOS_AUNQUE_PAREZCAN:
        return False
    return any(fnmatch.fnmatch(nombre.lower(), p) for p in PATRONES_SENSIBLES)


def leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8", errors="replace")


def tipo_notebook(ruta: Path) -> str | None:
    if ruta.suffix.lower() == ".ipynb":
        return "ipynb"
    if ruta.suffix.lower() not in {".py", ".sql", ".scala", ".r"}:
        return None
    try:
        with ruta.open(encoding="utf-8", errors="replace") as f:
            primera = f.readline().strip()
    except OSError:
        return None
    return CABECERAS_NOTEBOOK.get(primera)


def clasificar(ruta: Path, raiz: Path) -> str:
    rel = ruta.relative_to(raiz).as_posix().lower()
    nombre = ruta.name.lower()
    ext = ruta.suffix.lower()
    if es_sensible(ruta):
        return "sensible"
    if tipo_notebook(ruta):
        return "notebook"
    if nombre in {"databricks.yml", "databricks.yaml"}:
        return "bundle"
    if nombre in NOMBRES_DEPENDENCIAS:
        return "dependencias"
    if rel.startswith(".github/workflows") or nombre in {"azure-pipelines.yml", "azure-pipelines.yaml",
                                                          ".gitlab-ci.yml", "jenkinsfile"}:
        return "ci"
    partes = rel.split("/")
    if any(p in {"tests", "test"} for p in partes[:-1]) or nombre.startswith("test_") or nombre.endswith("_test.py"):
        return "test"
    if ext in {".yml", ".yaml"}:
        return "yaml"
    if ext == ".json":
        return "json"
    if ext == ".sql":
        return "sql"
    if ext == ".py":
        return "python"
    if ext in {".scala", ".r"}:
        return "codigo-otro"
    if ext in {".md", ".rst", ".txt", ".html"}:
        return "documentacion"
    if ext in {".toml", ".cfg", ".ini", ".conf"}:
        return "configuracion"
    return "otro"


def recorrer(raiz: Path):
    for actual, dirs, archivos in os.walk(raiz):
        dirs[:] = sorted(d for d in dirs if d not in DIRS_EXCLUIDOS)
        for a in sorted(archivos):
            if a == ".DS_Store":
                continue
            yield Path(actual) / a


# --------------------------------------------------------------------------------------
# Notebooks: celdas y contexto de cada línea
# --------------------------------------------------------------------------------------

@dataclass
class Celda:
    lenguaje: str          # python | sql | scala | md | run | pip | sh | otro
    linea_inicio: int      # 1-based, en el archivo
    lineas: list           # texto ya sin el prefijo MAGIC


def celdas_notebook(ruta: Path) -> list[Celda]:
    """Divide un notebook en formato fuente de Databricks (o .ipynb) en celdas."""
    tipo = tipo_notebook(ruta)
    if tipo == "ipynb":
        try:
            nb = json.loads(leer(ruta))
        except json.JSONDecodeError:
            return []
        celdas = []
        for c in nb.get("cells", []):
            fuente = c.get("source", [])
            texto = "".join(fuente) if isinstance(fuente, list) else str(fuente)
            lenguaje = "md" if c.get("cell_type") == "markdown" else "python"
            primeras = texto.lstrip()
            if lenguaje == "python" and primeras.startswith("%"):
                lenguaje = _lenguaje_magic(primeras.split()[0])
            celdas.append(Celda(lenguaje, 0, texto.splitlines()))
        return celdas
    base = tipo or "python"
    lineas = leer(ruta).splitlines()
    celdas: list[Celda] = []
    actual: list[str] = []
    inicio = 1
    for i, linea in enumerate(lineas, start=1):
        if i == 1 and linea.strip() in CABECERAS_NOTEBOOK:
            inicio = 2
            continue
        if SEPARADOR_CELDA.match(linea):
            celdas.append(_cerrar_celda(actual, inicio, base))
            actual, inicio = [], i + 1
            continue
        actual.append(linea)
    celdas.append(_cerrar_celda(actual, inicio, base))
    return [c for c in celdas if any(l.strip() for l in c.lineas)]


def _lenguaje_magic(cmd: str) -> str:
    return {"%md": "md", "%md-sandbox": "md", "%sql": "sql", "%python": "python", "%run": "run",
            "%pip": "pip", "%sh": "sh", "%scala": "scala", "%r": "otro", "%fs": "otro"}.get(cmd.lower(), "otro")


def _cerrar_celda(lineas: list[str], inicio: int, base: str) -> Celda:
    no_vacias = [l for l in lineas if l.strip()]
    if no_vacias and all(PREFIJO_MAGIC.match(l) for l in no_vacias):
        limpias = [PREFIJO_MAGIC.sub("", l, count=1) if PREFIJO_MAGIC.match(l) else l for l in lineas]
        primera = next(l for l in limpias if l.strip()).strip()
        lenguaje = _lenguaje_magic(primera.split()[0])
        if lenguaje in {"md", "sql", "python", "scala", "sh", "pip", "otro"}:
            # quita la línea del comando mágico pero conserva la numeración con una línea vacía
            idx = next(i for i, l in enumerate(limpias) if l.strip())
            resto = limpias[idx].strip()[len(primera.split()[0]):]
            limpias[idx] = resto
        return Celda(lenguaje, inicio, limpias)
    return Celda(base, inicio, list(lineas))


FSTRING_START = getattr(tokenize, "FSTRING_START", None)   # Python 3.12+ parte los f-strings
FSTRING_END = getattr(tokenize, "FSTRING_END", None)


def _tokens_cadena(codigo: str):
    """Tokens de comentario y de cadena, con los f-strings de Python 3.12+ reagrupados en un
    solo token (en 3.12 llegan como FSTRING_START … FSTRING_END)."""
    tokens = list(tokenize.generate_tokens(io.StringIO(codigo).readline))
    resultado = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if FSTRING_START is not None and tok.type == FSTRING_START:
            nivel, j = 0, i
            while j < len(tokens):
                if tokens[j].type == FSTRING_START:
                    nivel += 1
                elif tokens[j].type == FSTRING_END:
                    nivel -= 1
                    if nivel == 0:
                        break
                j += 1
            fin = tokens[min(j, len(tokens) - 1)]
            lineas = codigo.splitlines(keepends=True)
            texto = "".join(lineas[tok.start[0] - 1:fin.end[0]])
            corte_ini = tok.start[1]
            corte_fin = len(texto) - (len(lineas[fin.end[0] - 1]) - fin.end[1])
            resultado.append(tokenize.TokenInfo(tokenize.STRING, texto[corte_ini:corte_fin], tok.start, fin.end, tok.line))
            i = j + 1
            continue
        resultado.append(tok)
        i += 1
    return resultado


def contexto_lineas_python(codigo: str) -> dict[int, list[tuple[int, int, str]]]:
    """Para cada línea (1-based relativa al bloque), lista de rangos (col_ini, col_fin, tipo)
    con tipo en {comentario, docstring, cadena}. Lo que no cae en un rango es código."""
    rangos: dict[int, list[tuple[int, int, str]]] = {}
    try:
        tokens = _tokens_cadena(codigo)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return {}
    previo_significativo = None
    for i, tok in enumerate(tokens):
        if tok.type == tokenize.COMMENT:
            rangos.setdefault(tok.start[0], []).append((tok.start[1], 10**9, "comentario"))
        elif tok.type == tokenize.STRING:
            siguiente = next((t for t in tokens[i + 1:] if t.type not in (tokenize.NL, tokenize.COMMENT)), None)
            suelto = (previo_significativo is None or previo_significativo.type in (
                tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)) and (
                siguiente is None or siguiente.type in (tokenize.NEWLINE, tokenize.ENDMARKER))
            tipo = "docstring" if suelto and tok.string.lstrip("rRbBuUfF")[:3] in ('"""', "'''") else "cadena"
            for ln in range(tok.start[0], tok.end[0] + 1):
                ini = tok.start[1] if ln == tok.start[0] else 0
                fin = tok.end[1] if ln == tok.end[0] else 10**9
                rangos.setdefault(ln, []).append((ini, fin, tipo))
        if tok.type not in (tokenize.NL, tokenize.COMMENT, tokenize.ENCODING):
            previo_significativo = tok
    return rangos


def _contexto_en(rangos, linea_rel: int, col: int, default: str) -> str:
    for ini, fin, tipo in rangos.get(linea_rel, []):
        if ini <= col < fin:
            return tipo
    return default


# --------------------------------------------------------------------------------------
# Raíz del producto
# --------------------------------------------------------------------------------------

def detectar_raiz(inicio: Path) -> Path:
    """Sube desde `inicio` hasta encontrar databricks.yml; si no hay, la raíz del repo Git;
    si tampoco, el propio directorio."""
    p = inicio.resolve()
    if p.is_file():
        p = p.parent
    for candidato in [p, *p.parents]:
        if (candidato / "databricks.yml").exists() or (candidato / "databricks.yaml").exists():
            return candidato
        if (candidato / ".git").exists():
            return candidato
    return p


# --------------------------------------------------------------------------------------
# Grafo de dependencias (tablas, notebooks, jobs)
# --------------------------------------------------------------------------------------

NOMBRE_TABLA = r"[`\w.{}$\-]+"
RE_ASIGNACION = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*[fF]?[rR]?([\"'])([^\"'\n]+)\2\s*(#.*)?$")
LECTURAS = [
    re.compile(r"spark\.(?:read\.)?table\(\s*(?P<arg>[fF]?[\"'][^\"']+[\"']|[A-Za-z_]\w*)"),
    re.compile(r"DeltaTable\.forName\(\s*\w+\s*,\s*(?P<arg>[fF]?[\"'][^\"']+[\"']|[A-Za-z_]\w*)"),
    re.compile(r"\b(?:FROM|JOIN)\s+(?P<sql>" + NOMBRE_TABLA + ")", re.IGNORECASE),
]
ESCRITURAS = [
    re.compile(r"\.(?:saveAsTable|insertInto|toTable)\(\s*(?P<arg>[fF]?[\"'][^\"']+[\"']|[A-Za-z_]\w*)"),
    re.compile(r"\bINSERT\s+(?:INTO|OVERWRITE)\s+(?:TABLE\s+)?(?P<sql>" + NOMBRE_TABLA + ")", re.IGNORECASE),
    re.compile(r"\bMERGE\s+INTO\s+(?P<sql>" + NOMBRE_TABLA + ")", re.IGNORECASE),
    re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(?:TABLE|VIEW|MATERIALIZED\s+VIEW|STREAMING\s+TABLE)\s+"
               r"(?:IF\s+NOT\s+EXISTS\s+)?(?P<sql>" + NOMBRE_TABLA + ")", re.IGNORECASE),
]
PALABRAS_NO_TABLA = {"select", "(", "values", "lateral", "unnest", "json", "parquet", "delta", "csv"}
RE_RUN = re.compile(r"^\s*%run\s+(\S+)")
RE_NB_RUN = re.compile(r"dbutils\.notebook\.run\(\s*[fF]?[\"']([^\"']+)[\"']")


def _limpiar_tabla(t: str) -> str:
    t = t.strip().strip("`").strip(";").strip(",").strip(")")
    return t


def clave_tabla(nombre: str) -> str:
    """Último segmento en minúsculas: permite unir `{catalogo}.dv.sat_x` con `dv_dev.dv.sat_x`."""
    return nombre.replace("`", "").split(".")[-1].lower()


def _resolver(arg: str, asignaciones: dict[str, str]) -> str | None:
    if arg is None:
        return None
    arg = arg.strip()
    if arg[:1] in "fFrR" and arg[1:2] in "\"'":
        arg = arg[1:]
    if arg[:1] in "\"'":
        return arg[1:-1]
    return asignaciones.get(arg)


def _cadenas_python(codigo: str) -> str:
    """Contenido de los literales de cadena de un bloque Python (donde vive el SQL embebido)."""
    partes = []
    try:
        for tok in _tokens_cadena(codigo):
            if tok.type == tokenize.STRING:
                partes.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return codigo
    return "\n".join(partes)


def tablas_en_texto(texto: str, python: str = "", sql: str | None = None) -> tuple[set[str], set[str]]:
    """Tablas leídas y escritas. `python` es código Python (se le aplican los patrones de la API
    de Spark, y los de SQL solo a sus literales de cadena); `sql` es SQL puro. Si solo se pasa
    `texto`, se trata como SQL."""
    if sql is None and not python:
        sql = texto
    sql = sql or ""
    sql_total = sql + "\n" + _cadenas_python(python) if python else sql
    asignaciones = {}
    for linea in python.splitlines():
        m = RE_ASIGNACION.match(linea)
        if m:
            asignaciones[m.group(1)] = m.group(3)
    lee, escribe = set(), set()
    for patrones, destino in ((LECTURAS, lee), (ESCRITURAS, escribe)):
        for patron in patrones:
            fuente = sql_total if "(?P<sql>" in patron.pattern else python
            for m in patron.finditer(fuente):
                crudo = m.groupdict().get("sql")
                if crudo is not None:
                    nombre = _limpiar_tabla(crudo)
                    if crudo.startswith("{") and crudo.endswith("}") and crudo[1:-1] in asignaciones:
                        nombre = asignaciones[crudo[1:-1]]
                else:
                    nombre = _resolver(m.group("arg"), asignaciones)
                if not nombre or nombre.lower() in PALABRAS_NO_TABLA or nombre.startswith("("):
                    continue
                if "." not in nombre and not re.match(r"^[A-Za-z_][\w{}]*$", nombre):
                    continue
                destino.add(nombre)
    # Una tabla que se crea y luego se lee en el mismo notebook sigue siendo salida.
    return lee, escribe


@dataclass
class Bundle:
    archivo: str
    archivos_yaml: list = field(default_factory=list)
    variables: dict = field(default_factory=dict)
    targets: dict = field(default_factory=dict)
    jobs: dict = field(default_factory=dict)        # clave -> {"archivo", "def"}
    pipelines: dict = field(default_factory=dict)
    errores_carga: list = field(default_factory=list)


def cargar_bundle(raiz: Path) -> Bundle | None:
    principal = next((raiz / n for n in ("databricks.yml", "databricks.yaml") if (raiz / n).exists()), None)
    if principal is None or not HAY_YAML:
        return None
    b = Bundle(archivo=principal.relative_to(raiz).as_posix())
    pendientes = [principal]
    vistos = set()
    while pendientes:
        archivo = pendientes.pop(0)
        if archivo in vistos:
            continue
        vistos.add(archivo)
        try:
            doc = yaml.safe_load(leer(archivo)) or {}
        except Exception as e:  # noqa: BLE001 - se reporta, no se oculta
            b.errores_carga.append(f"{archivo.relative_to(raiz).as_posix()}: {e}")
            continue
        b.archivos_yaml.append(archivo.relative_to(raiz).as_posix())
        if archivo == principal:
            for patron in doc.get("include", []) or []:
                for encontrado in sorted(raiz.glob(patron)):
                    pendientes.append(encontrado)
            b.targets = doc.get("targets", {}) or {}
        b.variables.update(doc.get("variables", {}) or {})
        recursos = doc.get("resources", {}) or {}
        for clave, definicion in (recursos.get("jobs", {}) or {}).items():
            b.jobs[clave] = {"archivo": archivo, "def": definicion or {}}
        for clave, definicion in (recursos.get("pipelines", {}) or {}).items():
            b.pipelines[clave] = {"archivo": archivo, "def": definicion or {}}
        for _, t in (doc.get("targets", {}) or {}).items():
            for clave, definicion in ((t or {}).get("resources", {}) or {}).get("jobs", {}).items():
                b.jobs.setdefault(clave, {"archivo": archivo, "def": definicion or {}})
    return b


def resolver_ruta_recurso(ruta: str, archivo_yaml: Path) -> tuple[Path | None, str]:
    """Devuelve (ruta_local, estado) con estado en {existe, no-existe, no-verificable}."""
    if "${" in ruta or ruta.startswith("/"):
        return None, "no-verificable"
    base = (archivo_yaml.parent / ruta).resolve()
    for ext in ("", ".py", ".sql", ".ipynb", ".scala", ".r", ".R"):
        candidato = Path(str(base) + ext)
        if candidato.exists():
            return candidato, "existe"
    return base, "no-existe"


def tareas_de_job(definicion: dict) -> list[dict]:
    tareas = list(definicion.get("tasks", []) or [])
    for t in list(tareas):
        for_each = (t or {}).get("for_each_task", {}) or {}
        if for_each.get("task"):
            tareas.append(for_each["task"])
    return [t for t in tareas if isinstance(t, dict)]


def construir_grafo(raiz: Path, archivos: list[Path]) -> dict:
    productores: dict[str, set] = {}
    consumidores: dict[str, set] = {}
    nombres_tabla: dict[str, set] = {}
    llamadas: dict[str, list] = {}
    for ruta in archivos:
        cat = clasificar(ruta, raiz)
        if cat not in {"notebook", "python", "sql"}:
            continue
        rel = ruta.relative_to(raiz).as_posix()
        if cat == "notebook":
            celdas = celdas_notebook(ruta)
            python = "\n".join("\n".join(c.lineas) for c in celdas if c.lenguaje in {"python", "scala"})
            sql = "\n".join("\n".join(c.lineas) for c in celdas if c.lenguaje == "sql")
            for linea in leer(ruta).splitlines():
                limpia = PREFIJO_MAGIC.sub("", linea, count=1)
                m = RE_RUN.match(limpia)
                if m:
                    llamadas.setdefault(rel, []).append({"tipo": "%run", "destino": m.group(1)})
        elif cat == "python":
            python, sql = leer(ruta), ""
        else:
            python, sql = "", leer(ruta)
        for m in RE_NB_RUN.finditer(python):
            llamadas.setdefault(rel, []).append({"tipo": "dbutils.notebook.run", "destino": m.group(1)})
        lee, escribe = tablas_en_texto("", python=python, sql=sql)
        for t in escribe:
            productores.setdefault(clave_tabla(t), set()).add(rel)
            nombres_tabla.setdefault(clave_tabla(t), set()).add(t)
        for t in lee:
            if t in escribe:
                continue
            consumidores.setdefault(clave_tabla(t), set()).add(rel)
            nombres_tabla.setdefault(clave_tabla(t), set()).add(t)
    jobs = []
    bundle = cargar_bundle(raiz)
    if bundle:
        for clave, info in bundle.jobs.items():
            definicion, archivo = info["def"], info["archivo"]
            for t in tareas_de_job(definicion):
                ruta_nb = (t.get("notebook_task") or {}).get("notebook_path") or (
                    t.get("spark_python_task") or {}).get("python_file")
                destino, estado = (None, "sin-ruta")
                if ruta_nb:
                    destino, estado = resolver_ruta_recurso(ruta_nb, archivo)
                jobs.append({
                    "job": clave, "task_key": t.get("task_key"), "archivo": archivo.relative_to(raiz).as_posix(),
                    "ruta_declarada": ruta_nb, "estado_ruta": estado,
                    "artefacto": destino.relative_to(raiz).as_posix() if destino and estado == "existe" and _dentro(destino, raiz) else None,
                    "depends_on": [d.get("task_key") for d in (t.get("depends_on") or []) if isinstance(d, dict)],
                })
    tablas = {}
    for clave in sorted(set(productores) | set(consumidores)):
        tablas[clave] = {
            "nombres": sorted(nombres_tabla.get(clave, [])),
            "productores": sorted(productores.get(clave, [])),
            "consumidores": sorted(consumidores.get(clave, [])),
        }
    return {"tablas": tablas, "llamadas_notebook": llamadas, "tareas_job": jobs}


def _dentro(ruta: Path, raiz: Path) -> bool:
    try:
        ruta.resolve().relative_to(raiz.resolve())
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------------------
# inventario
# --------------------------------------------------------------------------------------

def cmd_inventario(args) -> int:
    raiz = detectar_raiz(Path(args.raiz)) if args.detectar_raiz else Path(args.raiz).resolve()
    archivos = list(recorrer(raiz))
    por_tipo: dict[str, list] = {}
    for a in archivos:
        por_tipo.setdefault(clasificar(a, raiz), []).append(a.relative_to(raiz).as_posix())
    sensibles = por_tipo.pop("sensible", [])
    grafo = construir_grafo(raiz, [a for a in archivos if not es_sensible(a)])
    salida = {
        "raiz": str(raiz),
        "capacidades": capacidades(),
        "total_archivos": len(archivos),
        "por_tipo": por_tipo,
        "excluidos_sensibles": sensibles,
        "grafo": grafo,
    }
    if args.json:
        print(json.dumps(salida, ensure_ascii=False, indent=2))
    else:
        print(f"Raíz del producto: {raiz}")
        for tipo, lista in sorted(por_tipo.items()):
            print(f"\n[{tipo}] {len(lista)}")
            for r in lista:
                print(f"  - {r}")
        if sensibles:
            print(f"\n[excluidos por sensibles — contenido no leído] {len(sensibles)}")
            for r in sensibles:
                print(f"  - {r}")
        print("\nTablas (clave → productores / consumidores):")
        for clave, info in grafo["tablas"].items():
            print(f"  {clave}: produce {info['productores'] or '—'} · consume {info['consumidores'] or '—'}")
        if grafo["tareas_job"]:
            print("\nTareas de jobs:")
            for t in grafo["tareas_job"]:
                print(f"  {t['job']}.{t['task_key']} → {t['ruta_declarada']} [{t['estado_ruta']}] depende de {t['depends_on'] or '—'}")
    return 0


def capacidades() -> dict:
    return {
        "python": sys.version.split()[0],
        "pyyaml": HAY_YAML,
        "git": shutil.which("git") is not None,
        "databricks_cli": shutil.which("databricks") is not None,
    }


# --------------------------------------------------------------------------------------
# impacto
# --------------------------------------------------------------------------------------

@dataclass
class Aparicion:
    archivo: str
    linea: int
    tipo_artefacto: str
    contexto: str
    texto: str


def buscar_termino(raiz: Path, termino: str, es_regex: bool, sensible_mayus: bool) -> list[Aparicion]:
    flags = 0 if sensible_mayus else re.IGNORECASE
    if es_regex:
        patron = re.compile(termino, flags)
    else:
        patron = re.compile(r"(?<![\w])" + re.escape(termino) + r"(?![\w])", flags)
    resultados: list[Aparicion] = []
    for ruta in recorrer(raiz):
        if es_sensible(ruta) or ruta.suffix.lower() not in EXT_TEXTO | {""}:
            continue
        rel = ruta.relative_to(raiz).as_posix()
        cat = clasificar(ruta, raiz)
        try:
            texto = leer(ruta)
        except OSError:
            continue
        if not patron.search(texto):
            continue
        if cat == "notebook" and ruta.suffix.lower() != ".ipynb":
            for celda in celdas_notebook(ruta):
                rangos = contexto_lineas_python("\n".join(celda.lineas)) if celda.lenguaje == "python" else {}
                for j, linea in enumerate(celda.lineas, start=1):
                    for m in patron.finditer(linea):
                        if celda.lenguaje == "md":
                            ctx = "markdown"
                        elif celda.lenguaje == "python":
                            ctx = _contexto_en(rangos, j, m.start(), "codigo")
                            if not rangos and linea.strip().startswith("#"):
                                ctx = "comentario"
                        elif celda.lenguaje == "sql":
                            ctx = "comentario" if linea.strip().startswith("--") else "sql"
                        else:
                            ctx = celda.lenguaje
                        resultados.append(Aparicion(rel, celda.linea_inicio + j - 1, cat, ctx, linea.strip()[:200]))
                        break
            continue
        rangos = contexto_lineas_python(texto) if ruta.suffix.lower() == ".py" else {}
        for n, linea in enumerate(texto.splitlines(), start=1):
            m = patron.search(linea)
            if not m:
                continue
            if ruta.suffix.lower() == ".py":
                ctx = _contexto_en(rangos, n, m.start(), "codigo")
            elif ruta.suffix.lower() == ".sql":
                ctx = "comentario" if linea.strip().startswith("--") else "sql"
            elif ruta.suffix.lower() == ".json":
                ctx = "json-clave" if re.search(r"[\"'][^\"']*" + patron.pattern + r"[^\"']*[\"']\s*:", linea, flags) else "json-valor"
            elif ruta.suffix.lower() in {".yml", ".yaml"}:
                ctx = "yaml-comentario" if linea.strip().startswith("#") else "yaml"
            elif ruta.suffix.lower() in {".md", ".rst", ".txt", ".html"}:
                ctx = "documentacion"
            else:
                ctx = "texto"
            resultados.append(Aparicion(rel, n, cat, ctx, linea.strip()[:200]))
    return resultados


def cmd_impacto(args) -> int:
    raiz = Path(args.raiz).resolve()
    grafo = construir_grafo(raiz, [a for a in recorrer(raiz) if not es_sensible(a)])
    salida = {"raiz": str(raiz), "terminos": {}}
    for termino in args.termino:
        apariciones = buscar_termino(raiz, termino, args.regex, args.mayusculas)
        relacionados = {}
        clave = termino.split(".")[-1].lower()
        if clave in grafo["tablas"]:
            relacionados["tabla"] = grafo["tablas"][clave]
        nb = [t for t in grafo["tareas_job"] if t["ruta_declarada"] and Path(t["ruta_declarada"]).stem.lower() == Path(termino).stem.lower()]
        if nb:
            relacionados["tareas_job"] = nb
        llamadores = [origen for origen, ls in grafo["llamadas_notebook"].items()
                      if any(Path(l["destino"]).stem.lower() == Path(termino).stem.lower() for l in ls)]
        if llamadores:
            relacionados["notebooks_que_lo_llaman"] = llamadores
        archivos = sorted({a.archivo for a in apariciones})
        salida["terminos"][termino] = {
            "apariciones": [asdict(a) for a in apariciones],
            "archivos": archivos,
            "por_contexto": _contar(apariciones, "contexto"),
            "por_tipo_artefacto": _contar(apariciones, "tipo_artefacto"),
            "dependencias_estructurales": relacionados,
        }
    if args.json:
        print(json.dumps(salida, ensure_ascii=False, indent=2))
    else:
        for termino, info in salida["terminos"].items():
            print(f"== {termino}: {len(info['apariciones'])} apariciones en {len(info['archivos'])} archivos")
            for a in info["apariciones"]:
                print(f"  {a['archivo']}:{a['linea']} [{a['tipo_artefacto']}/{a['contexto']}] {a['texto']}")
            if info["dependencias_estructurales"]:
                print("  dependencias estructurales:", json.dumps(info["dependencias_estructurales"], ensure_ascii=False))
    return 0


def _contar(items, atributo) -> dict:
    conteo: dict[str, int] = {}
    for i in items:
        conteo[getattr(i, atributo)] = conteo.get(getattr(i, atributo), 0) + 1
    return conteo


# --------------------------------------------------------------------------------------
# cambios
# --------------------------------------------------------------------------------------

RE_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
PALABRAS_COMUNES = set("""
and the for not with from import def class return true false none null select where join left right inner
outer group order having case when then else end into table create replace insert update delete merge
using spark col lit self print display string int bigint date timestamp boolean decimal double float as
df dbutils widgets get comment column columns alter add set values exists over partition by on is in
""".split())


def _git(raiz: Path, *args, check=True, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(raiz), *args], capture_output=True, text=True, check=check,
                          env=env)


def es_repo_git(raiz: Path) -> bool:
    if shutil.which("git") is None:
        return False
    r = _git(raiz, "rev-parse", "--show-toplevel", check=False)
    return r.returncode == 0


def senales_identificadores(eliminadas: list[str], agregadas: list[str]) -> dict:
    def conteo(lineas):
        c: dict[str, int] = {}
        for l in lineas:
            for t in RE_IDENT.findall(l):
                if t.lower() not in PALABRAS_COMUNES:
                    c[t] = c.get(t, 0) + 1
        return c
    e, a = conteo(eliminadas), conteo(agregadas)
    solo_eliminados = sorted(t for t in e if t not in a)
    solo_agregados = sorted(t for t in a if t not in e)
    return {"solo_en_eliminadas": solo_eliminados, "solo_en_agregadas": solo_agregados}


def _diff_unificado(diff: str) -> dict[str, dict]:
    archivos: dict[str, dict] = {}
    actual = None
    for linea in diff.splitlines():
        if linea.startswith("diff --git"):
            actual = linea.split(" b/", 1)[-1]
            archivos[actual] = {"eliminadas": [], "agregadas": []}
        elif actual and linea.startswith("+") and not linea.startswith("+++"):
            archivos[actual]["agregadas"].append(linea[1:])
        elif actual and linea.startswith("-") and not linea.startswith("---"):
            archivos[actual]["eliminadas"].append(linea[1:])
    return archivos


def cmd_cambios(args) -> int:
    raiz = Path(args.raiz).resolve()
    salida: dict = {"raiz": str(raiz), "fuente": None, "archivos": {}, "notas": []}
    if args.referencia:
        ref = Path(args.referencia).resolve()
        salida["fuente"] = f"comparación contra copia de referencia {ref}"
        import difflib
        rel_actuales = {p.relative_to(raiz).as_posix() for p in recorrer(raiz) if not es_sensible(p)}
        rel_ref = {p.relative_to(ref).as_posix() for p in recorrer(ref) if not es_sensible(p)}
        for rel in sorted(rel_actuales | rel_ref):
            a = leer(ref / rel).splitlines() if rel in rel_ref else []
            b = leer(raiz / rel).splitlines() if rel in rel_actuales else []
            if a == b:
                continue
            el, ag = [], []
            for l in difflib.unified_diff(a, b, lineterm="", n=0):
                if l.startswith("+") and not l.startswith("+++"):
                    ag.append(l[1:])
                elif l.startswith("-") and not l.startswith("---"):
                    el.append(l[1:])
            estado = "nuevo" if rel not in rel_ref else "eliminado" if rel not in rel_actuales else "modificado"
            salida["archivos"][rel] = {"estado": estado, "eliminadas": el, "agregadas": ag}
    elif es_repo_git(raiz):
        top = Path(_git(raiz, "rev-parse", "--show-toplevel").stdout.strip())
        base = args.base or "HEAD"
        salida["fuente"] = f"git diff contra {base} (incluye cambios no confirmados y archivos nuevos)"
        rel_raiz = raiz.relative_to(top).as_posix() if raiz != top else "."
        diff = _git(top, "diff", "--no-color", "-U0", base, "--", rel_raiz, check=False).stdout
        por_archivo = _diff_unificado(diff)
        estados = _git(top, "status", "--porcelain=v1", "--untracked-files=all", "--", rel_raiz).stdout.splitlines()
        nuevos = set()
        for linea in estados:
            codigo, ruta = linea[:2], linea[3:]
            if " -> " in ruta:
                ruta = ruta.split(" -> ", 1)[1]
            if codigo == "??":
                p = top / ruta
                if es_sensible(p):
                    salida["notas"].append(f"{ruta}: archivo sensible sin seguimiento; contenido no leído")
                    continue
                nuevos.add(ruta)
                por_archivo[ruta] = {"eliminadas": [], "agregadas": leer(p).splitlines() if p.is_file() else []}
        for ruta, info in por_archivo.items():
            if es_sensible(Path(ruta)):
                info = {"eliminadas": [], "agregadas": []}
                salida["notas"].append(f"{ruta}: archivo sensible; diff omitido")
            info["estado"] = "nuevo" if ruta in nuevos else ("eliminado" if not (top / ruta).exists() else "modificado")
            salida["archivos"][ruta] = info
        if not por_archivo:
            log = _git(top, "log", "-5", "--name-status", "--format=%h %ad %s", "--date=short", "--", rel_raiz, check=False).stdout
            salida["notas"].append("Sin cambios pendientes contra la base. Historial reciente para reconstruir el cambio:")
            salida["historial_reciente"] = log
    else:
        salida["fuente"] = None
        salida["notas"].append(
            "No hay repositorio Git accesible ni copia de referencia: el cambio debe reconstruirse con el "
            "contexto de la conversación, el archivo abierto y lo declarado por el usuario.")
    todas_el = [l for i in salida["archivos"].values() for l in i["eliminadas"]]
    todas_ag = [l for i in salida["archivos"].values() for l in i["agregadas"]]
    salida["senales"] = senales_identificadores(todas_el, todas_ag)
    if args.json:
        print(json.dumps(salida, ensure_ascii=False, indent=2))
    else:
        print(f"Fuente: {salida['fuente']}")
        for n in salida["notas"]:
            print(f"Nota: {n}")
        for ruta, info in salida["archivos"].items():
            print(f"\n{ruta} [{info['estado']}] -{len(info['eliminadas'])} +{len(info['agregadas'])}")
            for l in info["eliminadas"][: args.max_lineas]:
                print(f"  - {l}")
            for l in info["agregadas"][: args.max_lineas]:
                print(f"  + {l}")
        print("\nIdentificadores solo en líneas eliminadas (candidatos a renombre/eliminación):",
              ", ".join(salida["senales"]["solo_en_eliminadas"]) or "—")
        print("Identificadores solo en líneas agregadas:", ", ".join(salida["senales"]["solo_en_agregadas"]) or "—")
        if salida.get("historial_reciente"):
            print(salida["historial_reciente"])
    return 0


# --------------------------------------------------------------------------------------
# DDL y diccionarios
# --------------------------------------------------------------------------------------

RE_CREATE = re.compile(r"\bCREATE\s+(?:OR\s+REPLACE\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(" + NOMBRE_TABLA + r")\s*\(",
                       re.IGNORECASE)
RE_COMMENT = re.compile(r"\bCOMMENT\s+(['\"])((?:\\.|(?!\1).)*)\1", re.IGNORECASE | re.DOTALL)
PALABRAS_RESTRICCION = {"constraint", "primary", "foreign", "unique", "check", "index", "period"}


def _bloque_parentesis(texto: str, inicio: int) -> str | None:
    nivel, i, comilla = 0, inicio, None
    while i < len(texto):
        ch = texto[i]
        if comilla:
            if ch == "\\":
                i += 2
                continue
            if ch == comilla:
                comilla = None
        elif ch in "'\"":
            comilla = ch
        elif ch == "(":
            nivel += 1
        elif ch == ")":
            nivel -= 1
            if nivel == 0:
                return texto[inicio + 1:i]
        i += 1
    return None


def _partir_nivel_superior(texto: str) -> list[str]:
    partes, nivel, actual, comilla = [], 0, [], None
    for ch in texto:
        if comilla:
            actual.append(ch)
            if ch == comilla:
                comilla = None
            continue
        if ch in "'\"":
            comilla = ch
        elif ch in "(<":
            nivel += 1
        elif ch in ")>":
            nivel -= 1
        if ch == "," and nivel == 0:
            partes.append("".join(actual))
            actual = []
            continue
        actual.append(ch)
    if "".join(actual).strip():
        partes.append("".join(actual))
    return partes


def extraer_ddl(texto: str) -> list[dict]:
    tablas = []
    for m in RE_CREATE.finditer(texto):
        cuerpo = _bloque_parentesis(texto, m.end() - 1)
        if cuerpo is None:
            continue
        columnas = []
        for parte in _partir_nivel_superior(cuerpo):
            parte = re.sub(r"--[^\n]*", "", parte).strip()
            if not parte:
                continue
            tokens = parte.split()
            if tokens[0].lower() in PALABRAS_RESTRICCION or len(tokens) < 2:
                continue
            nombre = tokens[0].strip("`\"")
            if not re.match(r"^[A-Za-z_]\w*$", nombre):
                continue
            resto = parte[len(tokens[0]):].strip()
            tipo = re.split(r"\s+(?:NOT\s+NULL|NULL|COMMENT|DEFAULT|GENERATED|MASK|CONSTRAINT)\b", resto, maxsplit=1,
                            flags=re.IGNORECASE)[0].strip()
            cm = RE_COMMENT.search(parte)
            columnas.append({
                "nombre": nombre, "tipo": tipo,
                "nullable": not re.search(r"\bNOT\s+NULL\b", parte, re.IGNORECASE),
                "comentario": cm.group(2) if cm else None,
            })
        if columnas:
            tablas.append({"tabla": _limpiar_tabla(m.group(1)), "columnas": columnas})
    return tablas


CLAVES_TABLA = ("tabla", "table", "nombre_tabla", "table_name", "nombretabla", "entidad")
CLAVES_COLUMNAS = ("columnas", "columns", "campos", "fields", "atributos", "schema")
CLAVES_NOMBRE = ("nombre", "name", "columna", "column", "column_name", "nombre_columna", "campo", "field")
CLAVES_TIPO = ("tipo", "type", "data_type", "tipo_dato", "tipodato", "datatype")
CLAVES_DESC = ("descripcion", "descripción", "description", "comentario", "comment", "desc")


def _primera(d: dict, claves) -> object:
    bajas = {k.lower(): v for k, v in d.items()} if isinstance(d, dict) else {}
    for c in claves:
        if c in bajas:
            return bajas[c]
    return None


def extraer_diccionarios(doc, archivo: str) -> list[dict]:
    """Reconoce diccionarios de datos en formas comunes; lo que no reconoce lo ignora (no inventa)."""
    tablas = []

    def visitar(nodo, tabla_padre=None):
        if isinstance(nodo, dict):
            cols = _primera(nodo, CLAVES_COLUMNAS)
            nombre_tabla = _primera(nodo, CLAVES_TABLA)
            if nombre_tabla is None and cols is not None:
                nombre_tabla = _primera(nodo, ("nombre", "name"))
            if isinstance(cols, (list, dict)) and isinstance(nombre_tabla, str):
                columnas = []
                items = cols.items() if isinstance(cols, dict) else [(None, c) for c in cols]
                for clave, c in items:
                    if isinstance(c, dict):
                        nombre = clave or _primera(c, CLAVES_NOMBRE)
                        if not isinstance(nombre, str):
                            continue
                        tipo = _primera(c, CLAVES_TIPO)
                        columnas.append({"nombre": nombre, "tipo": tipo if isinstance(tipo, str) else None,
                                         "descripcion": _primera(c, CLAVES_DESC)})
                    elif isinstance(c, str):
                        columnas.append({"nombre": c, "tipo": None, "descripcion": None})
                if columnas:
                    tablas.append({"tabla": nombre_tabla, "archivo": archivo, "columnas": columnas,
                                   "descripcion_tabla": _primera(nodo, CLAVES_DESC)})
                    return
            for v in nodo.values():
                visitar(v)
        elif isinstance(nodo, list):
            for v in nodo:
                visitar(v)

    visitar(doc)
    return tablas


ALIAS_TIPO = {"integer": "int", "long": "bigint", "short": "smallint", "byte": "tinyint", "real": "float",
              "bool": "boolean", "varchar": "string", "text": "string", "char": "string", "numeric": "decimal",
              "dec": "decimal"}


def normalizar_tipo(t: str | None) -> str | None:
    if not t:
        return None
    t = re.sub(r"\s+", "", str(t).lower())
    base = re.match(r"^([a-z]+)", t)
    if base and base.group(1) in ALIAS_TIPO:
        t = ALIAS_TIPO[base.group(1)] + t[len(base.group(1)):]
    if t.startswith("string(") or t.startswith("varchar("):
        t = "string"
    return t


def _norm_texto(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().rstrip(".").lower()


# --------------------------------------------------------------------------------------
# validar
# --------------------------------------------------------------------------------------

@dataclass
class Hallazgo:
    severidad: str   # error | advertencia | info | no-verificado
    regla: str
    archivo: str
    linea: int | None
    mensaje: str


def validar_producto(raiz: Path, terminos_obsoletos: list[str], usar_cli: bool, target: str | None,
                     solo: set[str] | None = None) -> tuple[list[Hallazgo], list[dict]]:
    hallazgos: list[Hallazgo] = []
    pruebas: list[dict] = []
    archivos = [a for a in recorrer(raiz) if not es_sensible(a)]
    if solo:
        objetivo = [a for a in archivos if a.relative_to(raiz).as_posix() in solo]
    else:
        objetivo = archivos

    def prueba(nombre, estado, detalle=""):
        pruebas.append({"prueba": nombre, "estado": estado, "detalle": detalle})

    # 1. JSON
    n_json, err_json = 0, 0
    for a in objetivo:
        if a.suffix.lower() in {".json", ".ipynb"}:
            n_json += 1
            try:
                json.loads(leer(a))
            except json.JSONDecodeError as e:
                err_json += 1
                hallazgos.append(Hallazgo("error", "JSON-SINTAXIS", _rel(a, raiz), e.lineno, e.msg))
    prueba("Sintaxis JSON", "ok" if err_json == 0 else "fallo", f"{n_json} archivos, {err_json} con error")

    # 2. YAML
    ymls = [a for a in objetivo if a.suffix.lower() in {".yml", ".yaml"}]
    if not HAY_YAML:
        for a in ymls:
            hallazgos.append(Hallazgo("no-verificado", "YAML-SINTAXIS", _rel(a, raiz), None, "PyYAML no disponible"))
        prueba("Sintaxis YAML", "no-ejecutada", "PyYAML no disponible en el entorno")
    else:
        err = 0
        for a in ymls:
            try:
                list(yaml.safe_load_all(leer(a)))
            except Exception as e:  # noqa: BLE001
                err += 1
                linea = getattr(getattr(e, "problem_mark", None), "line", None)
                hallazgos.append(Hallazgo("error", "YAML-SINTAXIS", _rel(a, raiz), (linea + 1) if linea is not None else None,
                                          str(e).splitlines()[0]))
        prueba("Sintaxis YAML", "ok" if err == 0 else "fallo", f"{len(ymls)} archivos, {err} con error")

    # 3. Python y notebooks
    n_py, err_py = 0, 0
    for a in objetivo:
        cat = clasificar(a, raiz)
        if cat == "notebook" and a.suffix.lower() == ".py" or (a.suffix.lower() == ".ipynb"):
            for celda in celdas_notebook(a):
                if celda.lenguaje != "python":
                    continue
                n_py += 1
                codigo = "\n".join(celda.lineas)
                try:
                    ast.parse(codigo)
                except SyntaxError as e:
                    err_py += 1
                    hallazgos.append(Hallazgo("error", "PY-SINTAXIS", _rel(a, raiz),
                                              (celda.linea_inicio + (e.lineno or 1) - 1) if celda.linea_inicio else None,
                                              f"{e.msg}"))
        elif a.suffix.lower() == ".py":
            n_py += 1
            try:
                ast.parse(leer(a))
            except SyntaxError as e:
                err_py += 1
                hallazgos.append(Hallazgo("error", "PY-SINTAXIS", _rel(a, raiz), e.lineno, e.msg))
    prueba("Sintaxis Python/PySpark (ast)", "ok" if err_py == 0 else "fallo", f"{n_py} bloques, {err_py} con error")

    # 4. Imports locales
    hallazgos += validar_imports_locales(raiz, archivos, objetivo)

    # 5. Notebooks llamados con %run / dbutils.notebook.run
    grafo = construir_grafo(raiz, archivos)
    for origen, llamadas in grafo["llamadas_notebook"].items():
        for ll in llamadas:
            destino = ll["destino"]
            if destino.startswith("/") or "{" in destino or "$" in destino:
                continue
            ruta, estado = resolver_ruta_recurso(destino, raiz / origen)
            if estado == "no-existe":
                hallazgos.append(Hallazgo("error", "NB-REFERENCIA", origen, None,
                                          f"{ll['tipo']} apunta a '{destino}', que no existe en el producto"))

    # 6. Bundle / jobs
    hallazgos += validar_bundle(raiz, prueba)
    if usar_cli:
        hallazgos += validar_bundle_cli(raiz, target, prueba)

    # 7. Diccionarios vs DDL
    hallazgos += validar_diccionarios_vs_ddl(raiz, archivos, prueba)

    # 8. Términos obsoletos
    for termino in terminos_obsoletos:
        apariciones = buscar_termino(raiz, termino, False, True)
        for ap in apariciones:
            if Path(ap.archivo).name.upper().startswith("CHANGELOG"):
                hallazgos.append(Hallazgo("info", "OBSOLETO-HISTORICO", ap.archivo, ap.linea,
                                          f"'{termino}' en historial de cambios (se conserva)"))
                continue
            hallazgos.append(Hallazgo("error", "OBSOLETO", ap.archivo, ap.linea,
                                      f"referencia obsoleta a '{termino}' [{ap.contexto}]: {ap.texto}"))
        prueba(f"Referencias obsoletas a '{termino}'",
               "ok" if not any(h.regla == "OBSOLETO" and termino in h.mensaje for h in hallazgos) else "fallo",
               f"{len(apariciones)} apariciones")

    # 9. Secretos en los archivos validados
    for a in objetivo:
        for linea, tipo in buscar_secretos(a):
            hallazgos.append(Hallazgo("error", "SECRETO", _rel(a, raiz), linea, f"posible secreto ({tipo}); valor no mostrado"))
    return hallazgos, pruebas


def _rel(a: Path, raiz: Path) -> str:
    try:
        return a.relative_to(raiz).as_posix()
    except ValueError:
        return str(a)


def validar_imports_locales(raiz: Path, archivos: list[Path], objetivo: list[Path]) -> list[Hallazgo]:
    """Si un archivo importa un módulo que existe dentro del producto, comprueba que los nombres
    importados sigan definidos en él (detecta funciones renombradas o eliminadas)."""
    hallazgos = []
    modulos: dict[str, Path] = {}
    for a in archivos:
        if a.suffix == ".py" and not tipo_notebook(a):
            rel = a.relative_to(raiz).with_suffix("")
            partes = list(rel.parts)
            if partes[-1] == "__init__":
                partes = partes[:-1]
            for i in range(len(partes)):
                modulos.setdefault(".".join(partes[i:]), a)
    if not modulos:
        return hallazgos
    definidos_cache: dict[Path, set] = {}

    def definidos(p: Path) -> set:
        if p not in definidos_cache:
            nombres = set()
            try:
                arbol = ast.parse(leer(p))
            except SyntaxError:
                definidos_cache[p] = None  # type: ignore
                return None  # type: ignore
            for nodo in ast.walk(arbol):
                if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    nombres.add(nodo.name)
                elif isinstance(nodo, ast.Assign):
                    for t in nodo.targets:
                        if isinstance(t, ast.Name):
                            nombres.add(t.id)
                elif isinstance(nodo, (ast.Import, ast.ImportFrom)):
                    for n in nodo.names:
                        nombres.add((n.asname or n.name).split(".")[0])
            definidos_cache[p] = nombres
        return definidos_cache[p]

    for a in objetivo:
        if a.suffix.lower() != ".py":
            continue
        if tipo_notebook(a):
            codigo = "\n".join("\n".join(c.lineas) for c in celdas_notebook(a) if c.lenguaje == "python")
        else:
            codigo = leer(a)
        try:
            arbol = ast.parse(codigo)
        except SyntaxError:
            continue
        for nodo in ast.walk(arbol):
            if isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.module in modulos and modulos[nodo.module] != a:
                disponibles = definidos(modulos[nodo.module])
                if disponibles is None:
                    continue
                for n in nodo.names:
                    if n.name != "*" and n.name not in disponibles:
                        hallazgos.append(Hallazgo("error", "IMPORT-LOCAL", _rel(a, raiz), getattr(nodo, "lineno", None),
                                                  f"'{n.name}' no está definido en {modulos[nodo.module].relative_to(raiz).as_posix()}"))
    return hallazgos


RE_VAR = re.compile(r"\$\{var\.([A-Za-z_][\w-]*)")


def validar_bundle(raiz: Path, prueba) -> list[Hallazgo]:
    hallazgos: list[Hallazgo] = []
    principal = next((raiz / n for n in ("databricks.yml", "databricks.yaml") if (raiz / n).exists()), None)
    if principal is None:
        prueba("Referencias del bundle (estático)", "no-aplica", "sin databricks.yml en la raíz")
        return hallazgos
    if not HAY_YAML:
        # Respaldo parcial: sin PyYAML aún se puede comprobar que existan las rutas declaradas.
        hallazgos.append(Hallazgo("no-verificado", "BUNDLE", principal.name, None,
                                  "PyYAML no disponible: tasks, dependencias y variables sin verificar"))
        patron = re.compile(r"^\s*-?\s*(notebook_path|python_file|path)\s*:\s*[\"']?([^\"'#\s]+)")
        for archivo in [a for a in recorrer(raiz) if a.suffix.lower() in {".yml", ".yaml"}]:
            for n, linea in enumerate(leer(archivo).splitlines(), start=1):
                m = patron.match(linea)
                if m:
                    _, estado = resolver_ruta_recurso(m.group(2), archivo)
                    if estado == "no-existe":
                        hallazgos.append(Hallazgo("error", "JOB-RUTA", _rel(archivo, raiz), n,
                                                  f"{m.group(1)} '{m.group(2)}' no existe"))
        prueba("Referencias del bundle (estático)", "parcial",
               "PyYAML no disponible: solo se verificó la existencia de rutas")
        return hallazgos
    b = cargar_bundle(raiz)
    for e in b.errores_carga:
        hallazgos.append(Hallazgo("error", "BUNDLE-CARGA", e.split(":")[0], None, e))
    revisadas = 0
    for clave, info in b.jobs.items():
        archivo, definicion = info["archivo"], info["def"]
        rel_archivo = _rel(archivo, raiz)
        tareas = tareas_de_job(definicion)
        claves = [t.get("task_key") for t in tareas]
        for k in {k for k in claves if claves.count(k) > 1}:
            hallazgos.append(Hallazgo("error", "JOB-TASK-DUPLICADA", rel_archivo, None, f"job '{clave}': task_key '{k}' repetida"))
        for t in tareas:
            revisadas += 1
            for d in t.get("depends_on") or []:
                if isinstance(d, dict) and d.get("task_key") not in claves:
                    hallazgos.append(Hallazgo("error", "JOB-DEPENDENCIA", rel_archivo, None,
                                              f"job '{clave}', task '{t.get('task_key')}' depende de '{d.get('task_key')}', que no existe"))
            rutas = []
            if t.get("notebook_task"):
                rutas.append(("notebook_path", t["notebook_task"].get("notebook_path")))
            if t.get("spark_python_task"):
                rutas.append(("python_file", t["spark_python_task"].get("python_file")))
            if t.get("sql_task", {}).get("file"):
                rutas.append(("sql_task.file", t["sql_task"]["file"].get("path")))
            for etiqueta, ruta in rutas:
                if not ruta:
                    hallazgos.append(Hallazgo("error", "JOB-RUTA", rel_archivo, None, f"job '{clave}', task '{t.get('task_key')}': {etiqueta} vacío"))
                    continue
                _, estado = resolver_ruta_recurso(ruta, archivo)
                if estado == "no-existe":
                    hallazgos.append(Hallazgo("error", "JOB-RUTA", rel_archivo, None,
                                              f"job '{clave}', task '{t.get('task_key')}': {etiqueta} '{ruta}' no existe"))
                elif estado == "no-verificable":
                    hallazgos.append(Hallazgo("no-verificado", "JOB-RUTA", rel_archivo, None,
                                              f"job '{clave}', task '{t.get('task_key')}': {etiqueta} '{ruta}' es absoluta o usa variables"))
        if _hay_ciclo(tareas):
            hallazgos.append(Hallazgo("error", "JOB-CICLO", rel_archivo, None, f"job '{clave}': dependencias cíclicas entre tasks"))
    for clave, info in b.pipelines.items():
        for lib in info["def"].get("libraries", []) or []:
            for tipo in ("notebook", "file"):
                ruta = (lib.get(tipo) or {}).get("path") if isinstance(lib, dict) else None
                if ruta:
                    _, estado = resolver_ruta_recurso(ruta, info["archivo"])
                    if estado == "no-existe":
                        hallazgos.append(Hallazgo("error", "PIPELINE-RUTA", _rel(info["archivo"], raiz), None,
                                                  f"pipeline '{clave}': {tipo} '{ruta}' no existe"))
    # variables usadas vs declaradas
    declaradas = set(b.variables)
    for rel in b.archivos_yaml:
        for n, linea in enumerate(leer(raiz / rel).splitlines(), start=1):
            for v in RE_VAR.findall(linea):
                if v not in declaradas:
                    hallazgos.append(Hallazgo("error", "BUNDLE-VARIABLE", rel, n, f"variable '${{var.{v}}}' no declarada"))
    prueba("Referencias del bundle (estático)", "ok" if not any(h.severidad == "error" for h in hallazgos) else "fallo",
           f"{len(b.jobs)} jobs, {revisadas} tasks, {len(b.pipelines)} pipelines, targets: {', '.join(b.targets) or '—'}")
    return hallazgos


def _hay_ciclo(tareas: list[dict]) -> bool:
    grafo = {t.get("task_key"): [d.get("task_key") for d in (t.get("depends_on") or []) if isinstance(d, dict)] for t in tareas}
    estado: dict = {}

    def dfs(n) -> bool:
        estado[n] = 1
        for m in grafo.get(n, []):
            if estado.get(m) == 1 or (estado.get(m) is None and m in grafo and dfs(m)):
                return True
        estado[n] = 2
        return False

    return any(estado.get(n) is None and dfs(n) for n in grafo)


def validar_bundle_cli(raiz: Path, target: str | None, prueba) -> list[Hallazgo]:
    if shutil.which("databricks") is None:
        prueba("databricks bundle validate", "no-ejecutada", "Databricks CLI no disponible en el entorno")
        return [Hallazgo("no-verificado", "BUNDLE-CLI", "databricks.yml", None, "Databricks CLI no disponible")]
    if target and re.search(r"prod|prd|production", target, re.IGNORECASE):
        prueba("databricks bundle validate", "no-ejecutada", f"target '{target}' parece productivo; usa uno de desarrollo")
        return [Hallazgo("no-verificado", "BUNDLE-CLI", "databricks.yml", None, "validación contra target productivo omitida")]
    cmd = ["databricks", "bundle", "validate", "--output", "json"] + (["-t", target] if target else [])
    try:
        r = subprocess.run(cmd, cwd=raiz, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        prueba("databricks bundle validate", "fallo", "tiempo agotado (300 s)")
        return [Hallazgo("error", "BUNDLE-CLI", "databricks.yml", None, "bundle validate excedió 300 s")]
    if r.returncode == 0:
        prueba("databricks bundle validate", "ok", f"target {target or 'por defecto'}")
        return []
    detalle = (r.stderr or r.stdout).strip().splitlines()
    prueba("databricks bundle validate", "fallo", detalle[-1] if detalle else f"código {r.returncode}")
    return [Hallazgo("error", "BUNDLE-CLI", "databricks.yml", None, l) for l in detalle[-10:]]


def ddl_del_producto(raiz: Path, archivos: list[Path]) -> list[dict]:
    resultado = []
    for a in archivos:
        cat = clasificar(a, raiz)
        if cat in {"sql", "notebook", "python"} and a.suffix.lower() in {".sql", ".py"}:
            # En notebooks se ignoran las celdas markdown: un DDL citado en la documentación no es el DDL.
            texto = ("\n".join("\n".join(c.lineas) for c in celdas_notebook(a) if c.lenguaje != "md")
                     if cat == "notebook" else leer(a))
            for t in extraer_ddl(texto):
                t["archivo"] = a.relative_to(raiz).as_posix()
                resultado.append(t)
    return resultado


def diccionarios_del_producto(raiz: Path, archivos: list[Path]) -> list[dict]:
    resultado = []
    for a in archivos:
        if a.suffix.lower() == ".json":
            try:
                doc = json.loads(leer(a))
            except json.JSONDecodeError:
                continue
            resultado += extraer_diccionarios(doc, a.relative_to(raiz).as_posix())
    return resultado


def validar_diccionarios_vs_ddl(raiz: Path, archivos: list[Path], prueba) -> list[Hallazgo]:
    hallazgos = []
    ddls = ddl_del_producto(raiz, archivos)
    dics = diccionarios_del_producto(raiz, archivos)
    if not dics or not ddls:
        prueba("Diccionario de datos vs DDL", "no-aplica",
               f"{len(dics)} diccionarios reconocidos, {len(ddls)} DDL encontrados")
        return hallazgos
    por_tabla: dict[str, list] = {}
    for d in ddls:
        por_tabla.setdefault(clave_tabla(d["tabla"]), []).append(d)
    comparadas = 0
    for dic in dics:
        candidatos = por_tabla.get(clave_tabla(dic["tabla"]), [])
        for ddl in candidatos:
            comparadas += 1
            cols_ddl = {c["nombre"].lower(): c for c in ddl["columnas"]}
            cols_dic = {c["nombre"].lower(): c for c in dic["columnas"]}
            ref = f"{dic['archivo']} ↔ {ddl['archivo']}"
            for n in sorted(set(cols_ddl) - set(cols_dic)):
                hallazgos.append(Hallazgo("error", "DICC-COLUMNA-FALTANTE", dic["archivo"], None,
                                          f"{dic['tabla']}: columna '{cols_ddl[n]['nombre']}' está en el DDL ({ddl['archivo']}) y no en el diccionario"))
            for n in sorted(set(cols_dic) - set(cols_ddl)):
                hallazgos.append(Hallazgo("error", "DICC-COLUMNA-SOBRANTE", dic["archivo"], None,
                                          f"{dic['tabla']}: columna '{cols_dic[n]['nombre']}' está en el diccionario y no en el DDL ({ddl['archivo']})"))
            for n in sorted(set(cols_dic) & set(cols_ddl)):
                td, tl = normalizar_tipo(cols_dic[n]["tipo"]), normalizar_tipo(cols_ddl[n]["tipo"])
                if td and tl and td != tl:
                    hallazgos.append(Hallazgo("error", "DICC-TIPO", dic["archivo"], None,
                                              f"{dic['tabla']}.{cols_dic[n]['nombre']}: tipo '{cols_dic[n]['tipo']}' ≠ DDL '{cols_ddl[n]['tipo']}' ({ref})"))
                dd, dl = cols_dic[n].get("descripcion"), cols_ddl[n].get("comentario")
                if dd and dl and _norm_texto(dd) != _norm_texto(dl):
                    hallazgos.append(Hallazgo("advertencia", "DICC-DESCRIPCION", dic["archivo"], None,
                                              f"{dic['tabla']}.{cols_dic[n]['nombre']}: la descripción difiere del COMMENT del DDL ({ref})"))
    prueba("Diccionario de datos vs DDL",
           "ok" if not any(h.severidad == "error" for h in hallazgos) else "fallo",
           f"{len(dics)} diccionarios, {len(ddls)} DDL, {comparadas} pares comparados")
    return hallazgos


def cmd_validar(args) -> int:
    raiz = Path(args.raiz).resolve()
    solo = set(args.archivos) if args.archivos else None
    hallazgos, pruebas = validar_producto(raiz, args.obsoleto or [], args.bundle_cli, args.target, solo)
    resumen = {s: sum(1 for h in hallazgos if h.severidad == s) for s in ("error", "advertencia", "info", "no-verificado")}
    salida = {"raiz": str(raiz), "capacidades": capacidades(), "pruebas": pruebas, "resumen": resumen,
              "hallazgos": [asdict(h) for h in hallazgos]}
    if args.json:
        print(json.dumps(salida, ensure_ascii=False, indent=2))
    else:
        print(f"Validación de {raiz}")
        for p in pruebas:
            print(f"  [{p['estado']:^13}] {p['prueba']} — {p['detalle']}")
        for h in hallazgos:
            ubic = f"{h.archivo}:{h.linea}" if h.linea else h.archivo
            print(f"  {h.severidad.upper():<13} {h.regla:<24} {ubic} — {h.mensaje}")
        print(f"Resumen: {resumen}")
    return 1 if resumen["error"] else 0


# --------------------------------------------------------------------------------------
# Unity Catalog (solo lectura)
# --------------------------------------------------------------------------------------

def cmd_uc_sql(args) -> int:
    consultas = []
    for fqn in args.tabla:
        partes = fqn.replace("`", "").split(".")
        if len(partes) != 3:
            print(f"'{fqn}' debe ser catalogo.esquema.tabla", file=sys.stderr)
            return 2
        cat, esq, tab = partes
        consultas.append(
            f"-- {fqn}: columnas (solo lectura)\n"
            f"SELECT table_catalog, table_schema, table_name, column_name, data_type, is_nullable, comment, ordinal_position\n"
            f"FROM `{cat}`.information_schema.columns\n"
            f"WHERE table_schema = '{esq}' AND table_name = '{tab}'\nORDER BY ordinal_position;\n\n"
            f"-- {fqn}: comentario de la tabla (solo lectura)\n"
            f"SELECT table_catalog, table_schema, table_name, comment\nFROM `{cat}`.information_schema.tables\n"
            f"WHERE table_schema = '{esq}' AND table_name = '{tab}';")
    print("\n\n".join(consultas))
    print("\n-- Exporta el resultado de las consultas de columnas a JSON (lista de filas) y pásalo a "
          "`mgeller.py contrastar-uc --uc <archivo>`.")
    return 0


def cmd_contrastar_uc(args) -> int:
    raiz = Path(args.raiz).resolve()
    filas = json.loads(Path(args.uc).read_text(encoding="utf-8"))
    if isinstance(filas, dict):
        filas = filas.get("filas") or filas.get("rows") or []
    uc: dict[str, dict] = {}
    for f in filas:
        f = {k.lower(): v for k, v in f.items()}
        uc.setdefault(f["table_name"].lower(), {})[f["column_name"].lower()] = f
    archivos = [a for a in recorrer(raiz) if not es_sensible(a)]
    hallazgos = []
    for fuente, tablas in (("diccionario", diccionarios_del_producto(raiz, archivos)), ("ddl", ddl_del_producto(raiz, archivos))):
        for t in tablas:
            cols_uc = uc.get(clave_tabla(t["tabla"]))
            if not cols_uc:
                continue
            cols_src = {c["nombre"].lower(): c for c in t["columnas"]}
            for n in sorted(set(cols_uc) - set(cols_src)):
                hallazgos.append(Hallazgo("advertencia", "UC-COLUMNA-SOLO-EN-UC", t["archivo"], None,
                                          f"{t['tabla']}.{cols_uc[n]['column_name']} existe en UC y no en el {fuente}"))
            for n in sorted(set(cols_src) - set(cols_uc)):
                hallazgos.append(Hallazgo("advertencia", "UC-COLUMNA-SOLO-EN-REPO", t["archivo"], None,
                                          f"{t['tabla']}.{cols_src[n]['nombre']} está en el {fuente} y no en UC (¿cambio aún no desplegado?)"))
            for n in sorted(set(cols_uc) & set(cols_src)):
                desc_src = cols_src[n].get("descripcion") if fuente == "diccionario" else cols_src[n].get("comentario")
                desc_uc = cols_uc[n].get("comment")
                if desc_src and desc_uc and _norm_texto(desc_src) != _norm_texto(desc_uc):
                    hallazgos.append(Hallazgo("advertencia", "UC-DESCRIPCION", t["archivo"], None,
                                              f"{t['tabla']}.{cols_src[n]['nombre']}: descripción del {fuente} ≠ comment en UC"))
                elif desc_src and not desc_uc:
                    hallazgos.append(Hallazgo("advertencia", "UC-SIN-COMMENT", t["archivo"], None,
                                              f"{t['tabla']}.{cols_src[n]['nombre']}: sin comment en UC"))
                ts, tu = normalizar_tipo(cols_src[n].get("tipo")), normalizar_tipo(cols_uc[n].get("data_type"))
                if ts and tu and ts != tu:
                    hallazgos.append(Hallazgo("error", "UC-TIPO", t["archivo"], None,
                                              f"{t['tabla']}.{cols_src[n]['nombre']}: {fuente} '{cols_src[n].get('tipo')}' ≠ UC '{cols_uc[n].get('data_type')}'"))
    salida = {"hallazgos": [asdict(h) for h in hallazgos],
              "nota": "Las diferencias con UC no indican por sí solas qué versión es la correcta."}
    print(json.dumps(salida, ensure_ascii=False, indent=2) if args.json else
          "\n".join(f"{h.severidad.upper():<12} {h.regla:<24} {h.archivo} — {h.mensaje}" for h in hallazgos) or "Sin diferencias.")
    return 1 if any(h.severidad == "error" for h in hallazgos) else 0


# --------------------------------------------------------------------------------------
# Secretos
# --------------------------------------------------------------------------------------

PATRONES_SECRETO = [
    ("token-databricks", re.compile(r"\bdapi[0-9a-f]{32}(?:-\d+)?\b")),
    ("clave-privada", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("clave-storage-azure", re.compile(r"AccountKey=[A-Za-z0-9+/=]{40,}")),
    ("firma-sas", re.compile(r"[?&]sig=[A-Za-z0-9%+/=]{20,}")),
    ("clave-aws", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("token-github", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("jdbc-con-password", re.compile(r"jdbc:[^\s\"']*password=[^;&\s\"']{4,}", re.IGNORECASE)),
    ("asignacion-credencial", re.compile(
        r"\b(?:password|passwd|pwd|client_secret|secret_key|api_key|access_token|token)[\"']?\s*[:=]\s*[\"'](?![<{$])[^\"'\s]{8,}[\"']",
        re.IGNORECASE)),
]


def buscar_secretos(ruta: Path) -> list[tuple[int, str]]:
    if es_sensible(ruta) or ruta.suffix.lower() not in EXT_TEXTO | {""}:
        return []
    try:
        lineas = leer(ruta).splitlines()
    except OSError:
        return []
    hallados = []
    for n, linea in enumerate(lineas, start=1):
        if "dbutils.secrets" in linea or "{{secrets/" in linea:
            continue
        for tipo, patron in PATRONES_SECRETO:
            if patron.search(linea):
                hallados.append((n, tipo))
                break
    return hallados


def cmd_secretos(args) -> int:
    total = []
    for a in args.archivos:
        p = Path(a)
        if es_sensible(p):
            total.append({"archivo": a, "linea": None, "tipo": "archivo-sensible"})
            continue
        for linea, tipo in buscar_secretos(p):
            total.append({"archivo": a, "linea": linea, "tipo": tipo})
    print(json.dumps(total, ensure_ascii=False, indent=2) if args.json else
          "\n".join(f"{t['archivo']}:{t['linea']} — {t['tipo']} (valor no mostrado)" for t in total) or "Sin secretos detectados.")
    return 1 if total else 0


# --------------------------------------------------------------------------------------
# Git protegido
# --------------------------------------------------------------------------------------

RAMAS_PROTEGIDAS_DEFECTO = ["main", "master", "develop", "development", "release", "release/*", "releases/*",
                            "prod", "prd", "production", "produccion", "hotfix/*"]


def _sha_archivo(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def estado_git(raiz: Path, protegidas: list[str]) -> dict:
    if shutil.which("git") is None:
        return {"modo": "sin-git", "motivo": "binario git no disponible"}
    if not es_repo_git(raiz):
        en_workspace = str(raiz).startswith("/Workspace/")
        return {"modo": "git-folder-databricks" if en_workspace else "sin-git",
                "motivo": ("Carpeta del workspace sin .git expuesto: si es una Git folder de Databricks, commit y "
                           "push se hacen desde su diálogo Git (no hay API pública para ello)") if en_workspace
                else "el directorio no pertenece a un repositorio Git"}
    top = Path(_git(raiz, "rev-parse", "--show-toplevel").stdout.strip())
    rama = _git(top, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    remotos = _git(top, "remote").stdout.split()
    remoto = "origin" if "origin" in remotos else (remotos[0] if remotos else None)
    url = _git(top, "remote", "get-url", remoto, check=False).stdout.strip() if remoto else ""
    url = re.sub(r"//[^@/]+@", "//***@", url)  # nunca mostrar credenciales embebidas
    pred = None
    if remoto:
        r = _git(top, "symbolic-ref", "--short", f"refs/remotes/{remoto}/HEAD", check=False)
        if r.returncode == 0:
            pred = r.stdout.strip().split("/", 1)[-1]
    porcelana = _git(top, "status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines()
    cambios = []
    for l in porcelana:
        ruta = l[3:].split(" -> ", 1)[-1]
        cambios.append({"estado": l[:2], "ruta": ruta, "sensible": es_sensible(Path(ruta))})
    gitdir = Path(_git(top, "rev-parse", "--git-dir").stdout.strip())
    gitdir = gitdir if gitdir.is_absolute() else top / gitdir
    en_curso = [n for n in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD")
                if (gitdir / n).exists()]
    upstream = _git(top, "rev-parse", "--abbrev-ref", "@{u}", check=False)
    return {
        "modo": "git-local", "raiz_repo": str(top), "rama": rama, "detached": rama == "HEAD",
        "rama_protegida": es_protegida(rama, protegidas, pred), "rama_predeterminada": pred,
        "remoto": remoto, "url_remoto": url, "upstream": upstream.stdout.strip() if upstream.returncode == 0 else None,
        "operacion_en_curso": en_curso, "cambios": cambios,
        "staged": [c["ruta"] for c in cambios if c["estado"][0] not in (" ", "?")],
    }


def es_protegida(rama: str, protegidas: list[str], predeterminada: str | None) -> bool:
    if predeterminada and rama == predeterminada:
        return True
    return any(fnmatch.fnmatch(rama.lower(), p.lower()) for p in protegidas)


def _protegidas(args) -> list[str]:
    extra = os.environ.get("MGELLER_RAMAS_PROTEGIDAS", "")
    return (args.protegidas or RAMAS_PROTEGIDAS_DEFECTO) + [p for p in extra.split(",") if p.strip()]


def cmd_git_estado(args) -> int:
    raiz = Path(args.raiz).resolve()
    est = estado_git(raiz, _protegidas(args))
    if args.guardar_linea_base and est.get("modo") == "git-local":
        top = Path(est["raiz_repo"])
        linea_base = {"head": _git(top, "rev-parse", "HEAD", check=False).stdout.strip(),
                      "rama": est["rama"],
                      "archivos": {c["ruta"]: (None if c["sensible"] else _sha_archivo(top / c["ruta"]))
                                   for c in est["cambios"]}}
        Path(args.guardar_linea_base).write_text(json.dumps(linea_base, indent=2), encoding="utf-8")
        est["linea_base_guardada"] = args.guardar_linea_base
    print(json.dumps(est, ensure_ascii=False, indent=2))
    return 0 if est.get("modo") == "git-local" else 2


def _env_auth(token_env: str | None) -> dict | None:
    if not token_env:
        return None
    token = os.environ.get(token_env)
    if not token:
        raise SystemExit(f"La variable de entorno {token_env} no está definida")
    usuario = os.environ.get("MGELLER_GIT_USUARIO", "mgeller")
    cabecera = "Authorization: Basic " + base64.b64encode(f"{usuario}:{token}".encode()).decode()
    env = dict(os.environ)
    n = int(env.get("GIT_CONFIG_COUNT", "0"))
    env.update({"GIT_CONFIG_COUNT": str(n + 1), f"GIT_CONFIG_KEY_{n}": "http.extraHeader", f"GIT_CONFIG_VALUE_{n}": cabecera,
                "GIT_TERMINAL_PROMPT": "0"})
    return env


def cmd_git_entregar(args) -> int:
    raiz = Path(args.raiz).resolve()
    rechazos: list[str] = []
    acciones: list[str] = []
    protegidas = _protegidas(args)
    est = estado_git(raiz, protegidas)

    def fin(codigo: int, extra: dict | None = None) -> int:
        salida = {"resultado": "rechazado" if rechazos else "completado", "rechazos": rechazos, "acciones": acciones}
        salida.update(extra or {})
        print(json.dumps(salida, ensure_ascii=False, indent=2))
        return codigo

    if est.get("modo") != "git-local":
        rechazos.append(f"modo {est.get('modo')}: {est.get('motivo')}")
        return fin(2)
    top = Path(est["raiz_repo"])
    if est["detached"]:
        rechazos.append("HEAD desacoplado: no hay rama de trabajo")
    if est["operacion_en_curso"]:
        rechazos.append(f"operación Git en curso: {', '.join(est['operacion_en_curso'])}")
    if not args.mensaje.strip():
        rechazos.append("mensaje de commit vacío")

    def relativa_al_repo(a: str) -> str | None:
        """Acepta rutas absolutas, relativas al directorio actual o relativas al repo."""
        if Path(a).is_absolute():
            p = Path(a).resolve()
        else:
            p = (Path.cwd() / a).resolve()
            if not (_dentro(p, top) and p.exists()):
                p = (top / a).resolve()
        return p.relative_to(top.resolve()).as_posix() if _dentro(p, top) else None

    archivos = []
    for a in args.archivos:
        rel = relativa_al_repo(a)
        if rel is None:
            rechazos.append(f"{a}: fuera del repositorio")
            continue
        archivos.append(rel)
    archivos = sorted(set(archivos))
    if not archivos:
        rechazos.append("lista de archivos vacía: MGeller nunca usa `git add .`")
    cambiados = {c["ruta"]: c for c in est["cambios"]}
    for a in archivos:
        if es_sensible(Path(a)):
            rechazos.append(f"{a}: archivo sensible; no se versiona desde MGeller")
        elif a not in cambiados:
            rechazos.append(f"{a}: no tiene cambios pendientes (o está ignorado por .gitignore)")
        else:
            for linea, tipo in buscar_secretos(top / a):
                rechazos.append(f"{a}:{linea}: posible secreto ({tipo}); valor no mostrado")

    # Cambios preexistentes
    if args.linea_base:
        base = json.loads(Path(args.linea_base).read_text(encoding="utf-8"))
        preexistentes = set(base.get("archivos", {}))
        declarados = {relativa_al_repo(a) for a in (args.cambio_original or [])}
        for a in archivos:
            if a in preexistentes and a not in declarados and not args.autorizar_mezcla:
                rechazos.append(f"{a}: ya tenía cambios antes de MGeller y no fue declarado como parte del cambio "
                                f"validado (--cambio-original); no se mezcla trabajo ajeno")
        ajenos = sorted(preexistentes - set(archivos))
        if ajenos:
            acciones.append(f"cambios preexistentes que quedan fuera del commit: {', '.join(ajenos)}")
    elif not args.sin_linea_base:
        rechazos.append("falta --linea-base (o --sin-linea-base con motivo en el reporte): no se puede distinguir "
                        "trabajo previo del usuario")

    if rechazos:
        return fin(1)

    # Rama de trabajo
    rama = est["rama"]
    if est["rama_protegida"]:
        nueva = args.rama_trabajo
        if not nueva:
            rechazos.append(f"la rama '{rama}' está protegida y no se indicó --rama-trabajo")
            return fin(1)
        if es_protegida(nueva, protegidas, est["rama_predeterminada"]):
            rechazos.append(f"la rama de trabajo '{nueva}' también está protegida")
            return fin(1)
        existe = _git(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{nueva}", check=False).returncode == 0
        if existe:
            rechazos.append(f"la rama '{nueva}' ya existe localmente; elige otra para no mezclar trabajo")
            return fin(1)
        r = _git(top, "switch", "-c", nueva, check=False)  # conserva el árbol de trabajo
        if r.returncode != 0:
            rechazos.append(f"no se pudo crear la rama '{nueva}': {r.stderr.strip()}")
            return fin(1)
        acciones.append(f"rama protegida '{rama}' → se creó la rama de trabajo '{nueva}' (cambios sin confirmar preservados)")
        rama = nueva

    # Commit solo de los archivos del alcance
    r = _git(top, "add", "--", *archivos, check=False)
    if r.returncode != 0:
        rechazos.append(f"git add falló: {r.stderr.strip()}")
        return fin(1)
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
        f.write(args.mensaje.strip() + "\n")
        archivo_msg = f.name
    try:
        r = _git(top, "commit", "--only", "-F", archivo_msg, "--", *archivos, check=False)
    finally:
        os.unlink(archivo_msg)
    if r.returncode != 0:
        rechazos.append(f"git commit falló: {(r.stderr or r.stdout).strip()}")
        return fin(1)
    sha = _git(top, "rev-parse", "HEAD").stdout.strip()
    incluidos = sorted(_git(top, "show", "--name-only", "--format=", "HEAD").stdout.split())
    if incluidos != archivos:
        rechazos.append(f"el commit {sha[:10]} contiene {incluidos}, distinto de lo solicitado {archivos}; revísalo "
                        f"antes de publicar (no se hace push)")
        return fin(1, {"commit": sha, "rama": rama, "archivos_commit": incluidos})
    acciones.append(f"commit {sha[:10]} en '{rama}' con {len(incluidos)} archivos")
    extra = {"commit": sha, "rama": rama, "archivos_commit": incluidos, "mensaje": args.mensaje.strip(), "push": "no solicitado"}

    if args.push:
        if es_protegida(rama, protegidas, est["rama_predeterminada"]):
            rechazos.append(f"push a rama protegida '{rama}' bloqueado")
            return fin(1, extra)
        if not est["remoto"]:
            extra["push"] = "pendiente: no hay remoto configurado"
            return fin(0, extra)
        env = _env_auth(args.token_env)
        r = _git(top, "push", "--set-upstream", est["remoto"], f"HEAD:refs/heads/{rama}", check=False, env=env)
        if r.returncode != 0:
            extra["push"] = "fallido"
            extra["detalle_push"] = re.sub(r"//[^@/]+@", "//***@", (r.stderr or r.stdout).strip())
            return fin(1, extra)
        remoto_sha = _git(top, "ls-remote", est["remoto"], f"refs/heads/{rama}", check=False, env=env).stdout.split()
        verificado = bool(remoto_sha) and remoto_sha[0] == sha
        extra["push"] = "completado y verificado" if verificado else "ejecutado pero no verificado en el remoto"
        acciones.append(f"push de '{rama}' a {est['remoto']}: {extra['push']}")
        if not verificado:
            return fin(1, extra)
    return fin(0, extra)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mgeller", description="Motor de validación de consistencia de MGeller")
    p.add_argument("--version", action="version", version=f"mgeller {VERSION}")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("inventario", help="artefactos del producto y grafo de dependencias")
    s.add_argument("--raiz", required=True)
    s.add_argument("--detectar-raiz", action="store_true", help="subir hasta databricks.yml o la raíz Git")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_inventario)

    s = sub.add_parser("cambios", help="reconstruye el cambio desde Git o una copia de referencia")
    s.add_argument("--raiz", required=True)
    s.add_argument("--base", help="revisión Git base (por defecto HEAD)")
    s.add_argument("--referencia", help="directorio con la versión anterior (si no hay Git)")
    s.add_argument("--max-lineas", type=int, default=40)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_cambios)

    s = sub.add_parser("impacto", help="todas las apariciones de uno o más términos")
    s.add_argument("--raiz", required=True)
    s.add_argument("--termino", action="append", required=True)
    s.add_argument("--regex", action="store_true")
    s.add_argument("--mayusculas", action="store_true", help="distinguir mayúsculas")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_impacto)

    s = sub.add_parser("validar", help="validaciones estáticas del producto")
    s.add_argument("--raiz", required=True)
    s.add_argument("--archivos", nargs="*", help="limitar validación de sintaxis a estos archivos (relativos a la raíz)")
    s.add_argument("--obsoleto", action="append", help="término que ya no debe aparecer (repetible)")
    s.add_argument("--bundle-cli", action="store_true", help="ejecutar `databricks bundle validate` si existe el CLI")
    s.add_argument("--target", help="target del bundle para la validación con CLI (nunca productivo)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_validar)

    s = sub.add_parser("uc-sql", help="SQL de solo lectura para leer metadata de UC")
    s.add_argument("--tabla", action="append", required=True)
    s.set_defaults(func=cmd_uc_sql)

    s = sub.add_parser("contrastar-uc", help="compara metadata exportada de UC con diccionarios y DDL")
    s.add_argument("--raiz", required=True)
    s.add_argument("--uc", required=True, help="JSON con filas de information_schema.columns")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_contrastar_uc)

    s = sub.add_parser("secretos", help="busca secretos en archivos")
    s.add_argument("archivos", nargs="+")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_secretos)

    s = sub.add_parser("git-estado", help="estado Git y línea base de cambios preexistentes")
    s.add_argument("--raiz", required=True)
    s.add_argument("--protegidas", nargs="*")
    s.add_argument("--guardar-linea-base", help="ruta (fuera del repo) donde guardar la línea base")
    s.set_defaults(func=cmd_git_estado)

    s = sub.add_parser("git-entregar", help="commit/push protegido de los archivos del alcance")
    s.add_argument("--raiz", required=True)
    s.add_argument("--archivos", nargs="+", required=True)
    s.add_argument("--mensaje", required=True)
    s.add_argument("--linea-base")
    s.add_argument("--sin-linea-base", action="store_true")
    s.add_argument("--cambio-original", nargs="*", help="archivos preexistentes que SÍ son el cambio validado")
    s.add_argument("--autorizar-mezcla", action="store_true", help="solo con autorización explícita del usuario")
    s.add_argument("--rama-trabajo")
    s.add_argument("--protegidas", nargs="*")
    s.add_argument("--push", action="store_true")
    s.add_argument("--token-env", help="variable de entorno con un token Git (nunca se imprime)")
    s.set_defaults(func=cmd_git_entregar)
    return p


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
