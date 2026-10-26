#!/usr/bin/env python3
"""
lint_skill.py — valida una carpeta de skill contra la especificación de Agent Skills
(https://agentskills.io/specification), que es la que sigue Genie Code.

Errores (salida 1):
  - SKILL.md ausente o sin frontmatter YAML válido.
  - `name`: 1–64 caracteres, [a-z0-9-], sin guion inicial/final ni `--`, igual al nombre de la carpeta.
  - `description`: 1–1024 caracteres.
  - `compatibility`: ≤ 500 caracteres si existe; `metadata`: mapa de texto a texto.
  - Enlaces markdown relativos que no resuelven a un archivo de la skill.
  - El script `scripts/mgeller.py` no compila.
  - Menciones a un nombre anterior de la skill (la skill se llama MGeller).
Advertencias:
  - Cuerpo de SKILL.md con más de 500 líneas (recomendación de la especificación).

Uso:  python3 herramientas/lint_skill.py skills/mgeller-change-integrity
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

NOMBRES_PROHIBIDOS = re.compile(r"\bariadna\b", re.IGNORECASE)
ENLACE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def lint(carpeta: Path) -> tuple[list[str], list[str]]:
    errores, avisos = [], []
    skill = carpeta / "SKILL.md"
    if not skill.exists():
        return [f"{skill}: no existe"], avisos
    texto = skill.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", texto, re.DOTALL)
    if not m:
        return [f"{skill}: falta el frontmatter YAML"], avisos
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        return [f"{skill}: frontmatter inválido: {e}"], avisos
    cuerpo = m.group(2)

    nombre = fm.get("name")
    if not isinstance(nombre, str) or not (1 <= len(nombre) <= 64):
        errores.append("name: obligatorio, 1–64 caracteres")
    elif not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", nombre):
        errores.append(f"name '{nombre}': solo minúsculas, dígitos y guiones simples, sin guion al inicio o al final")
    elif nombre != carpeta.name:
        errores.append(f"name '{nombre}' no coincide con la carpeta '{carpeta.name}'")
    desc = fm.get("description")
    if not isinstance(desc, str) or not (1 <= len(desc) <= 1024):
        errores.append(f"description: obligatoria, 1–1024 caracteres (tiene {len(desc) if isinstance(desc, str) else 0})")
    if "compatibility" in fm and (not isinstance(fm["compatibility"], str) or len(fm["compatibility"]) > 500):
        errores.append("compatibility: texto de hasta 500 caracteres")
    if "metadata" in fm and not (isinstance(fm["metadata"], dict) and
                                 all(isinstance(k, str) and isinstance(v, str) for k, v in fm["metadata"].items())):
        errores.append("metadata: debe ser un mapa de texto a texto (pon las versiones entre comillas)")
    lineas = cuerpo.count("\n")
    if lineas > 500:
        avisos.append(f"SKILL.md tiene {lineas} líneas de cuerpo (> 500 recomendadas)")

    for md in sorted(carpeta.rglob("*.md")):
        contenido = md.read_text(encoding="utf-8")
        for destino in ENLACE.findall(contenido):
            if re.match(r"^[a-z]+://|^#|^mailto:", destino):
                continue
            ruta = (md.parent / destino.split("#")[0]).resolve()
            if not ruta.exists():
                errores.append(f"{md.relative_to(carpeta)}: enlace roto '{destino}'")
            elif carpeta.resolve() not in ruta.parents and ruta != carpeta.resolve():
                errores.append(f"{md.relative_to(carpeta)}: '{destino}' apunta fuera de la skill")
    for archivo in sorted(p for p in carpeta.rglob("*") if p.is_file()):
        try:
            if NOMBRES_PROHIBIDOS.search(archivo.read_text(encoding="utf-8")):
                errores.append(f"{archivo.relative_to(carpeta)}: menciona un nombre anterior de la skill")
        except UnicodeDecodeError:
            continue
    for script in sorted((carpeta / "scripts").glob("*.py")):
        try:
            compile(script.read_text(encoding="utf-8"), str(script), "exec")
        except SyntaxError as e:
            errores.append(f"{script.relative_to(carpeta)}: no compila: {e.msg} (línea {e.lineno})")
    return errores, avisos


def main() -> int:
    carpeta = Path(sys.argv[1] if len(sys.argv) > 1 else "skills/mgeller-change-integrity").resolve()
    errores, avisos = lint(carpeta)
    for a in avisos:
        print(f"AVISO  {a}")
    for e in errores:
        print(f"ERROR  {e}")
    print(f"{carpeta.name}: {'OK' if not errores else f'{len(errores)} errores'}")
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
