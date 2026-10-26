# Changelog

Cambios notables de mgeller-change-integrity. Formato basado en
[Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y versionado
[SemVer](https://semver.org/lang/es/).

## [1.0.0] — 2026-10-14

### Añadido
- Skill `mgeller-change-integrity` (MGeller) para Genie Code: flujo de 9 fases que identifica un
  cambio, inventaría el producto de datos, mapea su impacto, corrige inconsistencias inequívocas,
  valida y entrega a Git con salvaguardas.
- Motor `scripts/mgeller.py` (solo biblioteca estándar): `inventario`, `cambios`, `impacto`,
  `validar`, `uc-sql`, `contrastar-uc`, `secretos`, `git-estado`, `git-entregar`.
- Referencias: reglas de consistencia R1–R6, capacidades del entorno, Git protegido y plantilla del
  reporte.
- Escenarios de validación (27 pruebas) sobre un producto de ejemplo: columna renombrada con
  consumidor y diccionario JSON, cambio de job con YAML y documentación operativa, salvaguardas Git,
  operación sin PyYAML, compatibilidad con Python 3.9 y 3.12.
- `herramientas/lint_skill.py`: valida el frontmatter y los enlaces contra la especificación.

### Pendiente
- Validación en un workspace real de Azure Databricks con Genie Code (ver README, «Pruebas en
  Databricks»).

[1.0.0]: https://github.com/luisdgo2000/mgeller-change-integrity/releases/tag/v1.0.0
