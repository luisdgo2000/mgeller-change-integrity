# Capacidades del entorno

Qué da por hecho MGeller, qué comprueba en cada ejecución y qué no puede hacer. Verificado contra la
documentación de Azure Databricks del 2026-10-13 (Genie Code, Agent Skills y Git folders). **Lo que
dice la documentación no garantiza que esté disponible en tu sesión:** compruébalo cada vez.

## Comprueba al iniciar

| Capacidad | Cómo se comprueba | Si falta |
|---|---|---|
| Modo Agent de Genie Code | Las skills solo funcionan en modo Agent | No hay ejecución autónoma: entrega instrucciones |
| Cómputo adjunto | Ejecutar una celda Python | Validaciones del motor → `no-ejecutada`; revisión manual con las herramientas de Genie Code |
| Lectura de archivos del workspace desde el cómputo | `os.path.exists("/Workspace/...")` | Lee con Genie Code y valida a mano |
| `git` | `capacidades.git` en `inventario` | Ruta B o entrega pendiente |
| Databricks CLI | `capacidades.databricks_cli` | `bundle validate` → `no-ejecutada`; queda la validación estática |
| PyYAML | `capacidades.pyyaml` | YAML → `no-verificado` (nunca "válido") |
| Lectura de UC | `SELECT` sobre `information_schema` | R4 → `no-ejecutada (permiso)` |
| Historial de jobs | Lectura de `system.lakeflow.*` o API de Jobs | R6 sin tiempos: "pendiente de medir" |

## Lo que Genie Code sí hace (documentado)

- Lee y edita notebooks y archivos, ejecuta código en el cómputo adjunto y usa la salida.
- Usa metadata de Unity Catalog (tablas, columnas, descripciones, linaje) con **tus** permisos.
- Carga skills desde `Workspace/.assistant/skills/` (workspace), `/Users/{usuario}/.assistant/skills/`
  (usuario) o carpetas registradas en *Settings*. Se invocan con `@mgeller-change-integrity` o se
  cargan solas por su descripción. Las ediciones de una skill aplican en un **chat nuevo**.
- Por defecto un clasificador aprueba las acciones; el usuario puede exigir aprobación manual.

## Lo que no hay que asumir

- **Commit/push desde una Git folder**: no hay API pública; la Git folder no expone `.git` al
  cómputo. Ver [git-protegido.md](git-protegido.md), Ruta B.
- **Historial completo de la conversación**: usa solo el contexto que realmente ves.
- **Diff del notebook** dentro de una Git folder: no hay `git diff` desde el cómputo; reconstruye el
  cambio con la conversación, el archivo y una copia de referencia si existe.
- **Databricks CLI en el cómputo**: no viene garantizado; no instales dependencias nuevas para validar.
- **Permisos de escritura en UC**: aun teniéndolos, MGeller no escribe metadata viva sin autorización
  explícita y ambiente verificado como no productivo.

## Fuera de Databricks

El motor es Python estándar: funciona igual en una copia local del repositorio (VS Code, terminal,
CI). Ahí la Ruta A de Git es la normal y `databricks bundle validate` corre si el CLI está instalado
y autenticado.
