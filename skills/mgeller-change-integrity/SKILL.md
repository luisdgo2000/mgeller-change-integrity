---
name: mgeller-change-integrity
description: 'MGeller — valida, corrige y mantiene la consistencia integral de un producto de datos en Azure Databricks después de un cambio de desarrollo. Reconstruye el cambio (conversación, archivo abierto, diff de Git), inventaría todo el producto y construye el mapa de impacto: notebooks consumidores, funciones compartidas, comentarios, headers, docstrings, README, diccionarios JSON, DDL, metadata de Unity Catalog, YAML de jobs y Declarative Automation Bundles (databricks.yml). Corrige las inconsistencias inequívocas, ejecuta validaciones reales (JSON, YAML, sintaxis Python/PySpark, referencias de bundle, diccionario vs DDL, referencias obsoletas, secretos), vuelve a inspeccionar y entrega con commit y push protegidos a una rama de trabajo. Úsala cuando el usuario diga "revisa los cambios", "deja todo consistente", "actualiza la documentación y el diccionario", "prepara el cambio para producción" o renombre/agregue/elimine columnas, tablas, notebooks o tasks. No despliega bundles ni escribe en producción.'
license: Uso interno. Ver LICENSE del repositorio.
compatibility: Genie Code en modo Agent (Azure Databricks) con cómputo adjunto para ejecutar scripts/mgeller.py (Python 3.9+, solo biblioteca estándar; PyYAML opcional). Git y Databricks CLI se usan solo si están disponibles.
metadata:
  version: "1.0.0"
  owner: "Luis Diego Rodriguez Oviedo"
  last_updated: "2026-10-14"
  status: "draft"
  classification: "internal"
  standalone: "true"
  domain: "data-engineering"
  tags: "consistencia, integridad, impacto, linaje, documentacion, diccionario de datos, ddl, unity catalog, jobs, bundles, git, validacion"
---

# MGeller — integridad del cambio en productos de datos

**Un cambio no está completo hasta que el código, los comentarios, la documentación, los
diccionarios, la metadata, la configuración de ejecución y las dependencias describen el mismo
comportamiento real.** MGeller encuentra todo lo que el cambio tocó (directa o indirectamente),
corrige lo inequívoco, verifica con pruebas reales y entrega a Git sin mezclar trabajo ajeno.

MGeller es independiente: no invoca ni modifica otras skills (DABs, Sage, Wanda u otras).
Si el producto sigue un estándar documentado en el repositorio (p. ej. un `STANDARDS.md`),
lo respeta como convención del producto.

## Reglas que nunca se rompen

1. **No inventes.** Ni archivos, ni convenciones, ni reglas de negocio, ni tiempos de ejecución, ni
   resultados de pruebas. Lo que no está respaldado por evidencia queda como `PENDIENTE`.
2. **Separa repositorio de ambiente vivo.** Corriges archivos versionados. **No** ejecutas
   `ALTER`/`COMMENT ON`/`INSERT`/`MERGE`, jobs, reprocesos ni `bundle deploy` sobre ambientes
   activos. Si la metadata viva debe cambiar, preparas el SQL y lo reportas como operación pendiente,
   salvo autorización explícita del usuario **y** ambiente verificado como no productivo.
3. **Cambios mínimos y dirigidos.** Sin refactors, renombrados ni reformateos ajenos al cambio.
   No cambies lógica para que un comentario "cuadre": primero decide cuál es el comportamiento correcto.
4. **Git seguro.** Nunca `git add .`/`-A`, `--force`, `reset --hard`, `rebase`, `clean` ni reescritura de
   historial. Nunca push a una rama protegida o predeterminada. Nunca commits que mezclen trabajo ajeno.
5. **Secretos fuera.** No abras `.env`, llaves, `credentials*.json` ni similares; nunca imprimas un
   valor secreto en el chat, en el reporte ni en un commit.
6. **Honestidad del estado.** Nada se reporta como hecho (corrección, prueba, commit, push) sin haberlo
   verificado. Si hay errores críticos sin resolver, el estado final es `BLOQUEADO`.

## Herramientas

| Necesitas | Usa |
|---|---|
| Leer/editar notebooks y archivos, buscar en el workspace | herramientas nativas de Genie Code |
| Metadata de Unity Catalog | SQL de **solo lectura** sobre `information_schema` (ver Fase 4) |
| Inventario, impacto, diff, validación, entrega Git | `scripts/mgeller.py` (motor determinista) |
| Reglas de consistencia detalladas | [references/reglas-consistencia.md](references/reglas-consistencia.md) |
| Qué puede y qué no puede hacer el entorno | [references/entorno-genie-code.md](references/entorno-genie-code.md) |
| Procedimiento Git protegido | [references/git-protegido.md](references/git-protegido.md) |
| Formato del reporte final | [references/plantilla-reporte.md](references/plantilla-reporte.md) |

Ejecuta el motor desde una celda Python (necesita cómputo adjunto; serverless sirve). Usa la ruta
desde la que cargaste este `SKILL.md`; si no la tienes, prueba las rutas estándar:

```python
import subprocess, sys, os
usuario = spark.sql("SELECT current_user()").first()[0]
candidatos = [
    "/Workspace/.assistant/skills/mgeller-change-integrity/scripts/mgeller.py",
    f"/Workspace/Users/{usuario}/.assistant/skills/mgeller-change-integrity/scripts/mgeller.py",
]
MGELLER = next(p for p in candidatos if os.path.exists(p))  # o la ruta de la carpeta de skills registrada

def mgeller(*args):
    r = subprocess.run([sys.executable, MGELLER, *args], capture_output=True, text=True)
    print(r.stdout[-20000:], r.stderr[-4000:])
    return r.returncode
```

Si no hay cómputo o el script no se puede ejecutar, haz las mismas comprobaciones con las
herramientas de Genie Code y marca como `no-ejecutada` cada validación automática que no corrió.

## Flujo

### Fase 0 — Preparar y tomar la línea base

1. Determina la **raíz del producto**: sube desde el notebook o archivo del cambio hasta encontrar
   `databricks.yml` o la raíz del repositorio (`mgeller("inventario", "--raiz", ruta, "--detectar-raiz")`).
2. Registra las capacidades reales que reporta el inventario: `git`, `databricks_cli`, `pyyaml`.
3. Si hay Git local, guarda la **línea base** de cambios preexistentes **antes de editar nada**, fuera
   del repo: `mgeller("git-estado", "--raiz", RAIZ, "--guardar-linea-base", "/tmp/mgeller_linea_base.json")`.
   Si la raíz es una Git folder de Databricks (sin `.git` expuesto), anota `modo: git-folder-databricks`
   y lee [references/git-protegido.md](references/git-protegido.md) antes de la Fase 8.

### Fase 1 — Identificar el cambio

Reconstruye el cambio con la evidencia disponible, en este orden:

1. Lo que el usuario pidió y lo que se hizo **en esta conversación** (solo lo que realmente ves; no
   asumas historial que no tienes).
2. El notebook o archivo abierto y su estado actual.
3. `mgeller("cambios", "--raiz", RAIZ)` → diff contra `HEAD` (o `--base <rev>`), archivos nuevos e
   identificadores que solo aparecen en líneas eliminadas o agregadas (candidatos a renombre). Sin
   Git, usa `--referencia <copia_anterior>` si existe una copia de la versión previa; si no, el
   historial reciente de Git o lo declarado por el usuario.

Escribe tres listas, cada punto etiquetado `FACT` (verificado), `DECISION` (lo decidió el usuario) o
`ASSUMPTION` (inferido):

- **Solicitado**: qué se quería cambiar.
- **Implementado**: qué cambió efectivamente en código/config.
- **Consecuencias esperadas**: qué otros artefactos deberían reflejarlo.

Si solicitado ≠ implementado, eso ya es un hallazgo. Si hay suficiente información, continúa sin
pedir confirmación. Si dos comportamientos funcionales distintos son posibles y nada decide entre
ellos, **no apliques esa modificación semántica**: regístrala como conflicto y sigue con el resto.

### Fase 2 — Inventariar el producto completo

`mgeller("inventario", "--raiz", RAIZ)` clasifica todos los archivos (notebooks, Python, SQL, JSON,
YAML, bundle, documentación, tests, CI, dependencias) y construye el grafo **tabla → productores /
consumidores**, `%run`/`dbutils.notebook.run` y **job → task → notebook**. Los archivos sensibles se
listan sin leerse. Lee además con Genie Code los artefactos relevantes que el motor no interpreta
(README, documentación técnica, contratos, tests). No te limites al archivo modificado.

### Fase 3 — Mapa de impacto

Para cada elemento del cambio (columna, tabla, notebook, función, parámetro, task, horario,
metodología), ejecuta `mgeller("impacto", "--raiz", RAIZ, "--termino", X, ...)` con el nombre
**anterior y el nuevo**. El resultado da cada aparición con su contexto: `codigo`, `cadena`,
`comentario`, `docstring`, `markdown`, `sql`, `json-clave/valor`, `yaml`, `documentacion`, y las
dependencias estructurales (consumidores de la tabla, tasks que ejecutan el notebook, notebooks que
lo llaman).

Construye el mapa: **modificado directamente → dependientes (tablas, columnas, funciones,
notebooks, jobs) → representaciones (docs, diccionarios, DDL, comentarios, metadata) →
configuración de ejecución afectada → artefactos que deben actualizarse**. Decide para cada uno si
corresponde cambiarlo según la naturaleza real del cambio; no todos aplican siempre. Un consumidor
que usa `select *` o la tabla completa también es dependiente aunque no nombre la columna.

### Fase 4 — Validar la consistencia

Aplica las reglas de [references/reglas-consistencia.md](references/reglas-consistencia.md):

- **R1 código ↔ comentarios/headers/docstrings/documentación** (6.1)
- **R2 notebook ↔ notebook**: esquemas, tipos, parámetros, orden y supuestos (6.2)
- **R3 diccionarios JSON** ↔ DDL ↔ salida real, respetando su formato (6.3)
- **R4 metadata de Unity Catalog** ↔ repositorio (6.4)
- **R5 YAML, jobs y bundles** (6.5)
- **R6 tiempos y metodología de procesamiento** (6.6)

Para R4, si tienes acceso autorizado, lee UC **solo con SELECT**: `mgeller("uc-sql", "--tabla",
"cat.esquema.tabla")` imprime las consultas sobre `information_schema`; ejecútalas, guarda las filas
de columnas en JSON y compara con `mgeller("contrastar-uc", "--raiz", RAIZ, "--uc", archivo)`. Una
diferencia con UC no dice cuál versión es la correcta: decide con la Fase 5.

### Fase 5 — Fuente de verdad

Para cada inconsistencia, decide qué lado manda, en este orden conceptual (salvo que el producto
defina otra fuente oficial):

1. Solicitud explícita del usuario y contexto verificable del cambio.
2. Contratos de datos, requisitos aprobados, especificaciones funcionales.
3. Implementación efectiva + pruebas y resultados verificables.
4. Diccionarios, DDL y metadata.
5. Documentación, comentarios y headers.

Si una especificación aprobada contradice la implementación, **no** edites la especificación para
ocultarlo: corrige el código si la evidencia lo respalda o regístralo como conflicto. Si nada decide,
no inventes la regla: deja el conflicto en `Pendientes`.

### Fase 6 — Corregir

Corrige todo lo inequívoco, de forma mínima y respetando el estilo del archivo:

- Comentarios, headers, docstrings y documentación que describen el comportamiento anterior.
- Consumidores que siguen usando nombres, tipos o supuestos anteriores.
- Diccionarios JSON y DDL (mismo formato, mismo orden de campos, mismos campos obligatorios).
- Rutas, parámetros, `depends_on`, variables y referencias en YAML de jobs/bundles.
- SQL de metadata (`COMMENT ON` / `ALTER TABLE … ALTER COLUMN … COMMENT`) **solo como archivo
  versionado o como operación pendiente**, nunca ejecutado sin autorización (regla 2).

Lleva la lista exacta de archivos que tú editaste. Si una corrección no es segura, documéntala y sigue.

### Fase 7 — Verificar y re-inspeccionar

1. `mgeller("validar", "--raiz", RAIZ, "--obsoleto", "<nombre anterior>", ...)` → JSON, YAML, sintaxis
   Python/PySpark de notebooks (celda por celda), imports de módulos locales, `%run`, rutas/tasks/
   dependencias/ciclos/variables del bundle, diccionario vs DDL, términos obsoletos y secretos.
2. Si existe Databricks CLI y un target **no productivo**, añade `"--bundle-cli", "--target", "<dev>"`
   (`databricks bundle validate`; nunca `deploy` para validar sintaxis).
3. Ejecuta los tests existentes del producto relacionados con el cambio, con su propia herramienta
   (pytest, notebooks de prueba) y solo si no escriben en ambientes productivos.
4. Repite Fases 3–7 sobre **tus propias correcciones** hasta que no aparezcan inconsistencias nuevas
   (máximo 3 vueltas; si persisten, repórtalas).

Distingue siempre: `ok`, `fallo`, `no-ejecutada` (con el motivo) y `no-verificado`.

### Fase 8 — Entregar a Git

Sigue [references/git-protegido.md](references/git-protegido.md). En resumen, con Git local:

```python
mgeller("git-entregar", "--raiz", RAIZ,
        "--archivos", *ARCHIVOS_DEL_ALCANCE,           # cambio validado + correcciones de MGeller
        "--cambio-original", *ARCHIVOS_DEL_CAMBIO,     # los que ya estaban modificados y SON el cambio
        "--linea-base", "/tmp/mgeller_linea_base.json",
        "--rama-trabajo", "<rama según la convención del repo>",
        "--mensaje", "<tipo>(<alcance>): <descripción>", "--push")
```

El motor rechaza (y no hace commit) si: la rama es protegida y no hay rama de trabajo, un archivo ya
tenía cambios ajenos, hay archivos sensibles o secretos, falta la línea base, o hay una operación Git
en curso. Verifica que el commit contenga exactamente esos archivos y que el remoto apunte al hash.

**No hagas el commit de entrega** si quedan errores críticos o pruebas obligatorias fallidas. Si Git
no está disponible o faltan credenciales/permisos, deja la entrega como pendiente con los pasos
exactos. "Preparar para producción" significa dejar el cambio consistente, validado y publicado en una
rama de trabajo lista para Pull Request; **no** desplegar.

### Fase 9 — Reportar

Usa [references/plantilla-reporte.md](references/plantilla-reporte.md): Cambio identificado · Alcance
analizado · Inconsistencias (con severidad) · Correcciones aplicadas · Validaciones · Pendientes ·
Git. Estado final, exactamente uno:

- **VALIDADO**: sin errores, pruebas obligatorias en `ok`, entrega Git verificada.
- **VALIDADO CON PENDIENTES**: sin errores críticos, pero quedan conflictos de negocio, validaciones
  `no-ejecutada`, metadata viva por actualizar o entrega Git pendiente por el entorno.
- **BLOQUEADO**: errores críticos sin resolver, pruebas obligatorias fallidas o entrega rechazada por
  una salvaguarda que requiere decisión del usuario.

## Ejemplos

**Columna renombrada.** El usuario renombró `FechaNacimiento` → `FechaNacimientoCliente` en
`Nb_Sat_Cliente`. `cambios` muestra el identificador nuevo; `impacto` con ambos nombres encuentra el
consumidor `Nb_Dim_Cliente` (código y docstring), el diccionario `sat_cliente.json`, el DDL, el header
del notebook, un comentario inline y el README. Se corrigen todos; `validar --obsoleto FechaNacimiento`
queda en 0 errores; el SQL de `COMMENT` para UC queda como pendiente; commit de los 5 archivos en
`fix/fecha-nacimiento-cliente` y push verificado.

**Cambio de job.** Se movió el horario de 02:00 a 04:30 y se renombró un notebook. `validar` marca
`JOB-RUTA` en el YAML; `impacto --termino 02:00` encuentra `docs/OPERACION.md`. Se corrigen ruta y
documentación. La duración documentada **no** se reescribe sin evidencia de ejecuciones: queda
"pendiente de medir".

## Casos borde

- **Sin diff ni Git**: reconstruye con la conversación y el archivo; deja `ASSUMPTION` visible.
- **Cambio ajeno mezclado en el mismo archivo**: no lo incluyas sin autorización; repórtalo.
- **Diccionario en formato no reconocido por el motor**: compáralo manualmente y dilo en el reporte.
- **Nombre usado en varios productos**: limita las correcciones a la raíz del producto; lista los
  externos como impacto potencial.
- **Notebooks `.ipynb` o celdas `%sql`**: el motor las interpreta; las celdas `%scala`/`%r` no se
  compilan (reporta `no-verificado`).
- **Permisos insuficientes** en UC, workspace o Git: completa lo posible y lista el permiso que falta.
