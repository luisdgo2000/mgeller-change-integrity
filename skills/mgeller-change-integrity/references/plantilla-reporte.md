# Plantilla del reporte de MGeller

Breve, en tablas o viñetas, y solo con hechos verificados. No repitas el contenido de los archivos:
cita `archivo:línea`. Nunca incluyas valores secretos.

```markdown
## MGeller · <producto> · <ESTADO: VALIDADO | VALIDADO CON PENDIENTES | BLOQUEADO>

### Cambio identificado
- Solicitado: … (DECISION)
- Implementado: … (FACT: <archivo>)
- Objetivo / consecuencias esperadas: …

### Alcance analizado
- Raíz: `<ruta>` · N archivos (X notebooks, Y JSON, Z YAML, …) · tablas: … · jobs: …
- Excluidos por sensibles (no leídos): …

### Inconsistencias encontradas
| # | Severidad | Regla | Dónde | Problema |
|---|---|---|---|---|
| 1 | alta | R2 | `notebooks/dwh/Nb_Dim_Cliente.py:25` | Consume `FechaNacimiento`, ya no existe en `sat_cliente` |

### Correcciones aplicadas
| Archivo | Qué se cambió | Fuente de verdad |
|---|---|---|

### Validaciones
| Prueba | Estado | Detalle |
|---|---|---|
| Sintaxis JSON | ok | 3 archivos |
| databricks bundle validate | no-ejecutada | CLI no disponible |

### Pendientes
- Conflictos que requieren decisión: …
- Operaciones sobre ambientes vivos preparadas y no ejecutadas: …
- Permisos faltantes / validaciones no realizadas: …

### Git
- Modo: git-local | git-folder-databricks | sin-git
- Rama: `…` (creada desde `…` por ser protegida: sí/no)
- Archivos en el commit: …
- Commit: `<hash>` — `<mensaje>`
- Push: completado y verificado | fallido (<motivo>) | pendiente (<motivo>)
- Cambios preexistentes que quedaron fuera: …
```

Reglas del estado:

- `VALIDADO` exige: 0 errores, todas las pruebas obligatorias en `ok` y push verificado.
- Cualquier `no-ejecutada`, conflicto abierto u operación pendiente → `VALIDADO CON PENDIENTES`.
- Cualquier error crítico abierto, prueba obligatoria fallida o entrega rechazada que requiera una
  decisión → `BLOQUEADO`.
