# Reglas de consistencia de MGeller

Cada regla dice qué revisar, cómo lo detecta el motor (`scripts/mgeller.py`) y qué queda a tu
criterio. **Severidad**: `crítica` (el producto falla o produce datos incorrectos), `alta` (un
consumidor o un job se rompe, o la metadata contradice los datos), `media` (documentación o
comentarios engañosos), `baja` (redacción o formato).

## R1 — Código ↔ comentarios, headers, docstrings y documentación (6.1)

Busca, con `impacto` sobre el nombre anterior **y** el nuevo:

- Comentarios que describen la lógica anterior: filtros, joins, columnas eliminadas o renombradas,
  metodologías que ya no se usan, "se elimina X" cuando ahora se conserva.
- Headers (`# MAGIC %md` de la primera celda, front matter YAML) cuyo propósito, destino, grano,
  clave, estrategia de carga, dependencias o consumidores ya no coinciden.
- Docstrings de funciones o módulos que no corresponden a su comportamiento.
- Explicaciones de reglas de negocio que no coinciden con la transformación implementada.
- Referencias a tablas, notebooks o rutas que ya no existen.
- README, documentación técnica y glosarios.

El contexto que reporta el motor guía la corrección: `comentario`, `docstring` y `markdown` son
texto; `cadena` y `codigo` son lógica (no los cambies solo para alinear un texto). No te quedes con
el comentario más evidente: corrige todas las apariciones relevantes. Severidad habitual: media; alta
si el header documenta un contrato (destino, clave, grano) incorrecto.

## R2 — Notebook ↔ notebook (6.2)

Con el grafo del `inventario`:

- Para cada tabla cuya salida cambió, revisa a **todos** sus consumidores: columnas usadas, tipos,
  nulabilidad, supuestos (unicidad, grano, filtros previos) y uso de `select *`.
- Parámetros compartidos (widgets, `base_parameters`, `dbo.Parametros` u otra convención) y su
  nombre en cada notebook.
- Funciones auxiliares compartidas: firma, nombre y comportamiento (`validar` reporta
  `IMPORT-LOCAL` si un nombre importado dejó de existir).
- `%run` y `dbutils.notebook.run` (`NB-REFERENCIA`).
- Orden de ejecución: que la task productora preceda a la consumidora en el job.

Un cambio local que parece correcto aislado no es seguro hasta revisar a sus consumidores.
Severidad: crítica si un consumidor falla o calcula mal; alta si lee una columna que cambió de
semántica.

## R3 — Diccionarios de datos JSON (6.3)

`validar` reconoce diccionarios con forma `{tabla|table|nombre, columnas|columns|campos: [...]}` (o
mapas columna → atributos) y los compara con los DDL del producto por nombre de tabla:

- `DICC-COLUMNA-FALTANTE` / `DICC-COLUMNA-SOBRANTE`: columnas solo en el DDL o solo en el diccionario.
- `DICC-TIPO`: tipo distinto (con alias normalizados: `INTEGER`=`INT`, `LONG`=`BIGINT`…).
- `DICC-DESCRIPCION` (advertencia): descripción ≠ `COMMENT` del DDL.

Además revisa tú: nulabilidad y obligatoriedad, estructuras anidadas, referencias al objeto correcto
y coherencia con la **salida real** del notebook (el `select` final). Si el motor no reconoce el
formato, compáralo manualmente y dilo. **Respeta el formato**: mismo orden de campos, mismas claves,
misma indentación, mismos campos obligatorios; no reordenes ni "normalices" el archivo.

## R4 — Metadata de Unity Catalog (6.4)

Fuentes a contrastar: definición física de la tabla, comentarios de columnas y tabla en UC,
diccionarios, DDL, comentarios del notebook, documentación.

- Lee UC solo con `SELECT` sobre `information_schema.columns` y `information_schema.tables`
  (`mgeller.py uc-sql`). `contrastar-uc` marca columnas solo en UC o solo en el repo, tipos y
  descripciones distintas o ausentes.
- Una columna "solo en el repo" puede ser simplemente un cambio no desplegado: no es un error del repo.
- Si existe una fuente oficial de descripciones (diccionario, contrato), alinea las copias a ella.
- Si no se sabe qué versión es correcta, **no elijas**: repórtalo.
- La actualización de metadata viva se entrega como SQL versionado o como operación pendiente,
  por ejemplo:

```sql
-- PENDIENTE (no ejecutado por MGeller): aplicar en <ambiente> tras el despliegue
ALTER TABLE <catalogo>.<esquema>.<tabla> ALTER COLUMN <columna> COMMENT '<descripción oficial>';
COMMENT ON TABLE <catalogo>.<esquema>.<tabla> IS '<descripción oficial>';
```

## R5 — YAML, jobs y Declarative Automation Bundles (6.5)

`validar` carga `databricks.yml` y sus `include`, y comprueba:

- `JOB-RUTA` / `PIPELINE-RUTA`: `notebook_path`, `python_file`, `sql_task.file.path` y librerías de
  pipeline que no existen (rutas relativas al YAML que las declara; las absolutas o con variables se
  marcan `no-verificado`).
- `JOB-DEPENDENCIA`, `JOB-TASK-DUPLICADA`, `JOB-CICLO`.
- `BUNDLE-VARIABLE`: `${var.x}` usada y no declarada.
- `BUNDLE-CLI`: `databricks bundle validate -t <target no productivo>` si el CLI existe.

Revisa además: parámetros de cada task frente a los widgets del notebook, `schedule`/`trigger`,
cómputo y `environments`, variables por target, referencias a tablas o rutas en el YAML, y la
documentación operativa (frecuencia, horario, orden de tasks, responsables). Ajusta el YAML con las
convenciones existentes del archivo. Nunca `bundle deploy` ni `bundle run` para validar.

## R6 — Tiempos y metodología de procesamiento (6.6)

Si el cambio altera la estrategia (full → incremental, merge → append, nueva partición o clustering,
optimización), revisa todas las descripciones de metodología en comentarios, headers y documentación.

- **No inventes duraciones.** Si la documentación cita un tiempo, actualízalo solo con evidencia: el
  historial de ejecuciones (p. ej. la tabla de sistema `system.lakeflow.job_run_timeline` o la API de
  Jobs) cuando tengas acceso autorizado de lectura, o métricas comparables.
- Sin evidencia, separa lo comprobado ("la carga pasó a ser incremental por `FechaRegistro`") de lo que
  falta medir ("duración: pendiente de medir tras la primera ejecución").

## Clasificación de un hallazgo

| Situación | Acción |
|---|---|
| Inconsistencia inequívoca, fuente de verdad clara | Corregir y listar en *Correcciones aplicadas* |
| Corrección requiere cambiar lógica de negocio con evidencia | Corregir el código, citar la evidencia |
| Dos comportamientos posibles sin evidencia que decida | No modificar; *Pendientes* como conflicto |
| Requiere escribir en un ambiente vivo | Preparar SQL/cambio; *Pendientes* como operación |
| Validación imposible en el entorno | Marcar `no-ejecutada` con el motivo |
