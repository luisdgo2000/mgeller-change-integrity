# MGeller — integridad del cambio en productos de datos

![Versión](https://img.shields.io/badge/versi%C3%B3n-1.0.0-blue)
![Estado](https://img.shields.io/badge/estado-draft-orange)
![Python](https://img.shields.io/badge/python-3.9%E2%80%933.12-blue)
![Pruebas](https://img.shields.io/badge/pruebas-28%20OK-brightgreen)
![Licencia](https://img.shields.io/badge/licencia-uso%20interno-lightgrey)

> **En una frase:** cuando alguien cambia algo en un producto de datos (renombra una columna,
> mueve el horario de un job, modifica un notebook), MGeller revisa **todo lo demás que ese cambio
> toca** —otros notebooks, comentarios, documentación, diccionarios de datos, DDL, tablas, jobs—,
> lo deja consistente, lo comprueba con pruebas reales y lo entrega a Git en una rama de trabajo
> lista para revisión.

**Cómo leer este documento.** Si solo quieres entender qué es y para qué sirve, lee las secciones 1
a 5. Si vas a instalarlo y usarlo, ve a la 7 y la 8. Si necesitas la referencia técnica completa
(comandos, reglas, códigos de hallazgo), están en la 9, la 10 y la 11. Las palabras técnicas se
explican en el [glosario](#16-glosario).

## Tabla de contenido

1. [¿Qué es MGeller?](#1-qué-es-mgeller)
2. [El problema que resuelve](#2-el-problema-que-resuelve)
3. [¿Para quién es?](#3-para-quién-es)
4. [Qué hace y qué no hace](#4-qué-hace-y-qué-no-hace)
5. [Cómo funciona](#5-cómo-funciona)
6. [Ejemplo de principio a fin](#6-ejemplo-de-principio-a-fin)
7. [Requisitos e instalación](#7-requisitos-e-instalación)
8. [Cómo usarlo en Genie Code](#8-cómo-usarlo-en-genie-code)
9. [Usar el motor por línea de comandos](#9-usar-el-motor-por-línea-de-comandos)
10. [Qué revisa: reglas y códigos de hallazgo](#10-qué-revisa-reglas-y-códigos-de-hallazgo)
11. [Git protegido: cómo se entrega sin riesgo](#11-git-protegido-cómo-se-entrega-sin-riesgo)
12. [Seguridad](#12-seguridad)
13. [Estructura del repositorio y pruebas](#13-estructura-del-repositorio-y-pruebas)
14. [Preguntas frecuentes](#14-preguntas-frecuentes)
15. [Solución de problemas](#15-solución-de-problemas)
16. [Glosario](#16-glosario)
17. [Estado, limitaciones y pendientes](#17-estado-limitaciones-y-pendientes)
18. [Versionado, autoría y licencia](#18-versionado-autoría-y-licencia)

---

## 1. ¿Qué es MGeller?

MGeller es una **skill** para **Databricks Genie Code**, el asistente de inteligencia artificial de
Databricks. Una *skill* es una carpeta con instrucciones que se le entrega al asistente para que
sepa hacer bien una tarea especializada. La tarea de MGeller es la **revisión de consistencia que
debe hacerse después de un cambio**: asegurarse de que el código, los comentarios, la
documentación, los diccionarios, la metadata y la configuración de ejecución cuenten todos la misma
historia.

MGeller se compone de **dos piezas** que trabajan juntas:

| Pieza | Qué es | Dónde está | ¿Usa IA? |
|---|---|---|---|
| **El criterio** (la skill) | Instrucciones escritas: qué pasos seguir, qué reglas nunca romper, cómo decidir qué lado manda cuando dos cosas se contradicen y cómo reportar | `skills/mgeller-change-integrity/SKILL.md` y la carpeta `references/` | Sí: es lo que lee el asistente |
| **El motor** | Un programa Python de apoyo que hace las comprobaciones mecánicas: inventariar archivos, buscar todas las apariciones de un nombre, validar JSON/YAML/Python, comparar el diccionario contra el DDL, preparar el commit | `skills/mgeller-change-integrity/scripts/mgeller.py` | No: con la misma entrada siempre da el mismo resultado |

La división del trabajo es deliberada: **la IA decide qué corregir y lo corrige; el motor mide y
verifica.** Una analogía: la IA es el editor de un libro y el motor es el corrector ortográfico y
el control de calidad. Al editor se le confía el criterio; al corrector no se le pide opinión,
solo que encuentre todos los errores, siempre.

> **Principio rector:** *un cambio no está completo hasta que el código, la documentación, los
> metadatos, los diccionarios, las configuraciones y las dependencias afectadas describen el
> comportamiento real.*

## 2. El problema que resuelve

Piensa en una calle que cambia de nombre. No basta con cambiar el letrero de la esquina: hay que
actualizar los mapas, las direcciones en las facturas, el GPS, los registros del correo. Si solo
cambias el letrero, el sistema sigue "funcionando", pero cada cosa que usa el nombre viejo falla en
silencio.

En un producto de datos pasa exactamente igual. Renombrar una columna en un notebook parece un
cambio pequeño, pero la columna vive también en:

- otros notebooks que la leen (los *consumidores*),
- el diccionario de datos en JSON,
- el DDL de la tabla,
- los comentarios y el encabezado del notebook,
- el README y la documentación operativa,
- la metadata de Unity Catalog,
- los jobs y los bundles que ejecutan todo eso.

| Sin MGeller | Con MGeller |
|---|---|
| Se cambia un notebook y se confía en recordar los demás lugares | El motor busca **todas** las apariciones, con su contexto (código, comentario, SQL, JSON…) |
| El diccionario dice una cosa y el DDL otra, y nadie lo nota hasta que alguien consulta | Compara diccionario y DDL tabla por tabla y marca cada diferencia |
| El notebook consumidor falla de madrugada porque lee una columna que ya no existe | Detecta al consumidor **antes** de que llegue a producción |
| La documentación miente (describe la lógica anterior) | Corrige comentarios, encabezados y documentación que describen el comportamiento viejo |
| El commit mezcla el cambio con trabajo ajeno, o se hace directo a `main` | Entrega solo los archivos del alcance, en una rama de trabajo, con push verificado |
| Nadie sabe qué se revisó | Un reporte con estado final claro: `VALIDADO`, `VALIDADO CON PENDIENTES` o `BLOQUEADO` |

Más abajo hay un [ejemplo completo con salidas reales](#6-ejemplo-de-principio-a-fin).

## 3. ¿Para quién es?

| Rol | Qué obtiene de MGeller |
|---|---|
| **Ingeniero/a de datos** que modifica un producto | Cierra el cambio sin depender de la memoria: no tiene que recordar todos los lugares donde vive un nombre |
| **Líder técnico o revisor de Pull Request** | Recibe un cambio coherente, en una rama aparte, con un commit limitado a su alcance y un reporte de qué se corrigió y por qué |
| **Gobierno de datos / calidad** | Diccionarios, DDL y metadata alineados entre sí |
| **Operaciones y soporte** | Documentación operativa (horarios, orden de tasks) coherente con los jobs reales |
| **Gerencia / líderes** | Un estado final de tres valores posibles, sin tecnicismos: validado, validado con pendientes o bloqueado |

## 4. Qué hace y qué no hace

**Lo que hace**

- Reconstruye **qué cambió** (desde la conversación, el archivo abierto o el `diff` de Git).
- **Inventaría** el producto completo y dibuja el mapa de dependencias: qué notebook produce o
  consume cada tabla, qué task de qué job ejecuta cada notebook.
- Construye el **mapa de impacto**: cada aparición del nombre anterior y del nuevo, con su contexto.
- **Corrige** lo inequívoco: comentarios, encabezados, docstrings, documentación, consumidores,
  diccionarios JSON, DDL, rutas y dependencias en YAML de jobs y bundles.
- **Valida con pruebas reales**: sintaxis de JSON, YAML y Python/PySpark (celda por celda), imports
  locales, `%run`, rutas y dependencias del bundle, diccionario contra DDL, términos obsoletos y
  secretos.
- **Re-inspecciona** sus propias correcciones (hasta 3 vueltas) para no introducir inconsistencias
  nuevas.
- **Entrega a Git**: commit y push a una rama de trabajo, verificando que el remoto quedó en el
  commit correcto.
- Entrega un **reporte** con hechos verificados y un estado final.

**Lo que NO hace** (garantías)

- **No despliega.** Nunca ejecuta `bundle deploy` ni `bundle run`. "Preparar para producción"
  significa dejar el cambio consistente, validado y publicado en una rama lista para Pull Request.
- **No escribe en ambientes vivos.** No ejecuta `ALTER`, `COMMENT ON`, `INSERT`, `MERGE`, jobs ni
  reprocesos. Si la metadata viva de Unity Catalog debe cambiar, prepara el SQL y lo deja como
  *operación pendiente*.
- **No inventa.** Ni archivos, ni reglas de negocio, ni duraciones, ni resultados de pruebas. Lo
  que no tiene respaldo queda como `PENDIENTE`.
- **No cambia la lógica para que un comentario "cuadre".** Primero decide cuál es el comportamiento
  correcto; si hay dos posibles y nada decide, no toca nada y lo registra como conflicto.
- **No hace operaciones peligrosas de Git:** nunca `git add .`, `--force`, `reset --hard`, `rebase`
  ni `clean`, y nunca hace push a una rama protegida.
- **No lee ni imprime secretos.** No abre `.env`, llaves ni `credentials*.json`.
- **No toca otras skills.** Es independiente de cualquier otra (DABs, Sage, Wanda…).

## 5. Cómo funciona

### 5.1 El flujo en diez fases

MGeller sigue un flujo fijo, de la Fase 0 a la Fase 9. Cada fase usa, cuando corresponde, un
comando del motor.

```text
 cambio de desarrollo
        │
        ▼
 0 Preparar ─► 1 Identificar ─► 2 Inventariar ─► 3 Mapa de impacto ─► 4 Validar
                                                                         │
 9 Reportar ◄─ 8 Entregar a Git ◄─ 7 Verificar ◄─ 6 Corregir ◄─ 5 Fuente de verdad
```

| Fase | Nombre | Qué pasa, en palabras simples | Comando del motor |
|---|---|---|---|
| 0 | **Preparar** | Ubica la raíz del producto (busca `databricks.yml` o la raíz del repositorio), anota qué herramientas hay (`git`, Databricks CLI, PyYAML) y guarda una **línea base**: una foto de los cambios que ya estaban pendientes antes de empezar | `inventario --detectar-raiz`, `git-estado --guardar-linea-base` |
| 1 | **Identificar el cambio** | Escribe tres listas —*solicitado*, *implementado* y *consecuencias esperadas*—, cada punto etiquetado `FACT` (verificado), `DECISION` (lo decidió el usuario) o `ASSUMPTION` (inferido). Si lo solicitado no coincide con lo implementado, eso ya es un hallazgo | `cambios` |
| 2 | **Inventariar** | Clasifica todos los archivos y construye el grafo *tabla → quién la produce y quién la consume*, `%run` y *job → task → notebook*. Los archivos sensibles se listan sin leerse | `inventario` |
| 3 | **Mapa de impacto** | Para cada elemento que cambió (columna, tabla, notebook, función, parámetro, task, horario…) busca **todas** las apariciones del nombre anterior y del nuevo, con su contexto | `impacto` |
| 4 | **Validar la consistencia** | Aplica las reglas R1 a R6 (ver [sección 10](#10-qué-revisa-reglas-y-códigos-de-hallazgo)) | `validar`, `uc-sql`, `contrastar-uc` |
| 5 | **Fuente de verdad** | Para cada inconsistencia decide **qué lado manda** (ver 5.2). Si nada decide, no inventa la regla: la deja como conflicto | — (criterio de la skill) |
| 6 | **Corregir** | Edita solo lo inequívoco, con cambios mínimos y respetando el estilo de cada archivo | — (edición con Genie Code) |
| 7 | **Verificar y re-inspeccionar** | Vuelve a validar, incluidas sus propias correcciones, hasta que no aparezcan inconsistencias nuevas (máximo 3 vueltas) | `validar` |
| 8 | **Entregar a Git** | Commit y push a una rama de trabajo, con salvaguardas | `git-entregar` |
| 9 | **Reportar** | Reporte final con estado y evidencia (ver 8.3) | — |

### 5.2 Qué lado manda cuando dos cosas se contradicen

Cuando, por ejemplo, el diccionario dice una cosa y el código otra, MGeller aplica este orden de
prioridad (salvo que el producto defina otra fuente oficial):

1. La solicitud explícita del usuario y el contexto verificable del cambio.
2. Los contratos de datos, requisitos aprobados y especificaciones funcionales.
3. La implementación efectiva, junto con pruebas y resultados verificables.
4. Los diccionarios, el DDL y la metadata.
5. La documentación, los comentarios y los encabezados.

Si una especificación aprobada contradice la implementación, MGeller **no edita la especificación
para ocultarlo**: corrige el código si la evidencia lo respalda o registra el conflicto.

### 5.3 Quién hace qué: la IA o el motor

| Tarea | Quién la hace | Por qué |
|---|---|---|
| Entender qué se quiso cambiar | La IA (con el contexto de la conversación) | Requiere comprensión |
| Listar archivos, buscar apariciones, validar sintaxis, comparar diccionario y DDL | El motor | Es mecánico, repetible y no admite opinión |
| Decidir qué lado manda ante una contradicción | La IA, siguiendo el orden de prioridad | Requiere criterio |
| Editar comentarios, documentación, diccionarios, DDL, YAML | La IA | Requiere respetar estilo y contexto |
| Comprobar que no quedan referencias obsoletas ni secretos | El motor | Debe ser exhaustivo |
| Hacer commit y push con salvaguardas | El motor | Las reglas de seguridad no deben depender de un modelo |
| Redactar el reporte | La IA, con la plantilla | Requiere síntesis |

### 5.4 Las seis reglas de oro

Estas reglas no se rompen nunca, y están escritas en el `SKILL.md` que lee el asistente:

1. **No inventes.** Lo que no esté respaldado por evidencia queda como `PENDIENTE`.
2. **Separa el repositorio del ambiente vivo.** Se corrigen archivos versionados; no se ejecuta nada
   sobre ambientes activos.
3. **Cambios mínimos y dirigidos.** Sin refactors, renombrados ni reformateos ajenos al cambio.
4. **Git seguro.** Nada de `git add .`, `--force`, `reset --hard`, `rebase`, `clean`, ni push a
   ramas protegidas, ni commits que mezclen trabajo ajeno.
5. **Secretos fuera.** No se abren archivos sensibles ni se imprime un valor secreto jamás.
6. **Honestidad del estado.** Nada se reporta como hecho sin haberlo verificado. Con errores críticos
   sin resolver, el estado final es `BLOQUEADO`.

## 6. Ejemplo de principio a fin

Todas las salidas de esta sección son **reales**: se obtuvieron ejecutando el motor sobre el
producto de ejemplo que trae este repositorio (`tests/fixtures/producto_clientes`). Se abrevian
las rutas largas y algunas líneas.

**El producto de ejemplo** tiene dos notebooks (`Nb_Sat_Cliente`, que escribe la tabla
`sat_cliente`, y `Nb_Dim_Cliente`, que la lee), el DDL de la tabla, su diccionario de datos en JSON,
un job con dos tasks, un README y un documento de operación.

**El cambio de desarrollo.** Ana renombra la columna `FechaNacimiento` a `FechaNacimientoCliente`
**solo dentro de `Nb_Sat_Cliente`**. El código del satélite funciona, pero todo lo demás quedó
describiendo (o leyendo) la columna vieja.

### Paso 1 — Inventariar el producto (Fase 2)

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py inventario --raiz <producto>
```

```text
Raíz del producto: <producto>

[bundle] 1
  - databricks.yml
[documentacion] 2
  - README.md
  - docs/OPERACION.md
[json] 1
  - diccionarios/sat_cliente.json
[notebook] 2
  - notebooks/dwh/Nb_Dim_Cliente.py
  - notebooks/satellites/Nb_Sat_Cliente.py
[python] 2
  - src/utilidades/__init__.py
  - src/utilidades/normalizacion.py
[sql] 1
  - ddl/sat_cliente.sql
[yaml] 1
  - resources/job_clientes.yml

Tablas (clave → productores / consumidores):
  dim_cliente: produce ['notebooks/dwh/Nb_Dim_Cliente.py'] · consume —
  sat_cliente: produce ['ddl/sat_cliente.sql', 'notebooks/satellites/Nb_Sat_Cliente.py'] · consume ['notebooks/dwh/Nb_Dim_Cliente.py']
  stg_cliente: produce — · consume ['notebooks/satellites/Nb_Sat_Cliente.py']

Tareas de jobs:
  job_clientes.sat_cliente → ../notebooks/satellites/Nb_Sat_Cliente.py [existe] depende de —
  job_clientes.dim_cliente → ../notebooks/dwh/Nb_Dim_Cliente.py [existe] depende de ['sat_cliente']
```

Lectura: ya se sabe que `Nb_Dim_Cliente` **consume** `sat_cliente`, así que el cambio de Ana lo
afecta aunque nadie lo haya tocado.

### Paso 2 — Reconstruir el cambio (Fase 1)

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py cambios --raiz <producto>
```

```text
Fuente: git diff contra HEAD (incluye cambios no confirmados y archivos nuevos)

notebooks/satellites/Nb_Sat_Cliente.py [modificado] -2 +2
  -     .withColumn("FechaNacimiento", F.to_date("fecha_nac", "yyyyMMdd"))
  -     .select("Hk_Cliente", "NombreCliente", "FechaNacimiento", "CodigoSegmento", "FechaRegistro")
  +     .withColumn("FechaNacimientoCliente", F.to_date("fecha_nac", "yyyyMMdd"))
  +     .select("Hk_Cliente", "NombreCliente", "FechaNacimientoCliente", "CodigoSegmento", "FechaRegistro")

Identificadores solo en líneas eliminadas (candidatos a renombre/eliminación): FechaNacimiento
Identificadores solo en líneas agregadas: FechaNacimientoCliente
```

### Paso 3 — Mapa de impacto (Fase 3)

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py impacto --raiz <producto> --termino FechaNacimiento
```

```text
== FechaNacimiento: 8 apariciones en 5 archivos
  README.md:4 [documentacion/documentacion] `FechaNacimiento`. El job se describe en [docs/OPERACION.md](docs/OPERACION.md).
  ddl/sat_cliente.sql:5 [sql/sql] FechaNacimiento DATE COMMENT 'Fecha de nacimiento del cliente',
  diccionarios/sat_cliente.json:7 [json/json-valor] {"nombre": "FechaNacimiento", "tipo": "DATE", "descripcion": "Fecha de nacimiento del cliente"},
  notebooks/dwh/Nb_Dim_Cliente.py:4 [notebook/markdown] Construye `Dim_Cliente` a partir de `Sat_Cliente`. Calcula `EdadCliente` desde `FechaNacimiento`.
  notebooks/dwh/Nb_Dim_Cliente.py:20 [notebook/docstring] """Edad en años cumplidos a partir de FechaNacimiento."""
  notebooks/dwh/Nb_Dim_Cliente.py:25 [notebook/cadena] .withColumn("EdadCliente", calcular_edad("FechaNacimiento"))
  notebooks/satellites/Nb_Sat_Cliente.py:9 [notebook/markdown] | Columnas de negocio | `NombreCliente`, `FechaNacimiento`, `CodigoSegmento` |
  notebooks/satellites/Nb_Sat_Cliente.py:27 [notebook/comentario] # Se conserva FechaNacimiento tal como llega del core; la edad se calcula en la dimensión.
```

Lectura: el cambio de Ana tocó **1 archivo**, pero el nombre viejo aparece en **5**. El contexto entre
corchetes le dice a la IA cómo tratar cada aparición: `markdown`, `docstring` y `comentario` son
texto (se actualizan); `cadena` y `codigo` son lógica (aquí `Nb_Dim_Cliente.py:25` es el consumidor
que **se rompería**: lee una columna que ya no existe). La búsqueda es de palabra completa, por eso
`FechaNacimiento` no coincide con el nombre nuevo `FechaNacimientoCliente`: solo aparecen las
referencias al nombre anterior.

### Paso 4 — Validar: el producto está inconsistente (Fases 4 y 7)

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py validar --raiz <producto> --obsoleto FechaNacimiento
```

```text
Validación de <producto>
  [     ok      ] Sintaxis JSON — 1 archivos, 0 con error
  [     ok      ] Sintaxis YAML — 2 archivos, 0 con error
  [     ok      ] Sintaxis Python/PySpark (ast) — 10 bloques, 0 con error
  [     ok      ] Referencias del bundle (estático) — 1 jobs, 2 tasks, 0 pipelines, targets: dev, prod
  [     ok      ] Diccionario de datos vs DDL — 1 diccionarios, 1 DDL, 1 pares comparados
  [    fallo    ] Referencias obsoletas a 'FechaNacimiento' — 8 apariciones
  ERROR         OBSOLETO   README.md:4 — referencia obsoleta a 'FechaNacimiento' [documentacion]: ...
  ERROR         OBSOLETO   ddl/sat_cliente.sql:5 — referencia obsoleta a 'FechaNacimiento' [sql]: ...
  ... (8 errores en total, uno por aparición)
Resumen: {'error': 8, 'advertencia': 0, 'info': 0, 'no-verificado': 0}
```

El comando termina con código de salida `1` (hay errores). Observa que **la sintaxis está bien**: el
producto "compila", pero cuenta historias distintas en distintos lugares. Esa es la clase de
problema que MGeller existe para cazar.

### Paso 5 — Corregir (Fase 6)

La IA corrige las 8 apariciones con cambios mínimos, en **cinco archivos**: el diccionario JSON, el
DDL, `Nb_Dim_Cliente` (encabezado, docstring y uso en código), `Nb_Sat_Cliente` (encabezado y
comentario) y el README. No toca lógica de negocio. El SQL para actualizar la metadata viva de
Unity Catalog **no se ejecuta**: queda preparado como operación pendiente.

### Paso 6 — Re-validar (Fase 7)

```text
  [     ok      ] Sintaxis JSON — 1 archivos, 0 con error
  [     ok      ] Sintaxis YAML — 2 archivos, 0 con error
  [     ok      ] Sintaxis Python/PySpark (ast) — 10 bloques, 0 con error
  [     ok      ] Referencias del bundle (estático) — 1 jobs, 2 tasks, 0 pipelines, targets: dev, prod
  [     ok      ] Diccionario de datos vs DDL — 1 diccionarios, 1 DDL, 1 pares comparados
  [     ok      ] Referencias obsoletas a 'FechaNacimiento' — 0 apariciones
Resumen: {'error': 0, 'advertencia': 0, 'info': 0, 'no-verificado': 0}
```

Código de salida `0`: sin errores.

### Paso 7 — Entregar a Git (Fase 8)

La línea base se guardó **antes de editar** (Fase 0), de modo que el motor sabe que
`Nb_Sat_Cliente.py` ya estaba modificado y **es** el cambio original, mientras que los otros cuatro
archivos son correcciones de MGeller. Como Ana estaba parada en `main` (rama protegida), el motor
creó una rama de trabajo:

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py git-entregar --raiz <producto> \
  --archivos README.md ddl/sat_cliente.sql diccionarios/sat_cliente.json \
             notebooks/dwh/Nb_Dim_Cliente.py notebooks/satellites/Nb_Sat_Cliente.py \
  --cambio-original notebooks/satellites/Nb_Sat_Cliente.py \
  --linea-base linea_base.json \
  --rama-trabajo fix/fecha-nacimiento-cliente \
  --mensaje "fix(clientes): renombra FechaNacimiento a FechaNacimientoCliente en todo el producto" \
  --push
```

```json
{
  "resultado": "completado",
  "rechazos": [],
  "acciones": [
    "rama protegida 'main' → se creó la rama de trabajo 'fix/fecha-nacimiento-cliente' (cambios sin confirmar preservados)",
    "commit 95f3593a60 en 'fix/fecha-nacimiento-cliente' con 5 archivos",
    "push de 'fix/fecha-nacimiento-cliente' a origin: completado y verificado"
  ],
  "commit": "95f3593a60dc43ae4b5f62f7c9c095d80c94f4a7",
  "rama": "fix/fecha-nacimiento-cliente",
  "archivos_commit": ["README.md", "ddl/sat_cliente.sql", "diccionarios/sat_cliente.json",
                      "notebooks/dwh/Nb_Dim_Cliente.py", "notebooks/satellites/Nb_Sat_Cliente.py"],
  "push": "completado y verificado"
}
```

### Paso 8 — El reporte (Fase 9)

La IA entrega un reporte con la [plantilla](skills/mgeller-change-integrity/references/plantilla-reporte.md).
Este es un **ejemplo ilustrativo** del formato para el caso anterior (el contenido exacto lo redacta
el asistente en cada ejecución):

```markdown
## MGeller · producto_clientes · VALIDADO CON PENDIENTES

### Cambio identificado
- Solicitado: renombrar FechaNacimiento → FechaNacimientoCliente (DECISION)
- Implementado: renombre en el satélite (FACT: notebooks/satellites/Nb_Sat_Cliente.py)
- Consecuencias esperadas: consumidor, diccionario, DDL, comentarios y README deben reflejarlo

### Inconsistencias encontradas
| # | Severidad | Regla | Dónde | Problema |
|---|---|---|---|---|
| 1 | alta | R2 | `notebooks/dwh/Nb_Dim_Cliente.py:25` | Consume `FechaNacimiento`, que ya no existe en `sat_cliente` |
| 2 | alta | R3 | `diccionarios/sat_cliente.json:7` | El diccionario conserva el nombre anterior |

### Validaciones
| Prueba | Estado | Detalle |
|---|---|---|
| Referencias obsoletas | ok | 0 apariciones tras corregir |
| databricks bundle validate | no-ejecutada | CLI no disponible |

### Pendientes
- Operación sobre ambiente vivo preparada y NO ejecutada: SQL de COMMENT para Unity Catalog.

### Git
- Rama: `fix/fecha-nacimiento-cliente` (creada desde `main` por ser protegida: sí)
- Push: completado y verificado
```

Es `VALIDADO CON PENDIENTES` y no `VALIDADO` porque quedó una operación sobre un ambiente vivo
preparada pero sin ejecutar (regla de la sección [8.2](#82-los-tres-estados-finales)).

## 7. Requisitos e instalación

### 7.1 Requisitos

| Requisito | Detalle | ¿Obligatorio? |
|---|---|---|
| **Genie Code** | En **modo Agent**, con las *partner-powered AI features* habilitadas | Sí, para usar la skill dentro de Databricks |
| **Cómputo** | Cualquiera que ejecute Python 3.9+ (el cómputo *serverless* sirve) para correr `scripts/mgeller.py` | Sí, para las validaciones automáticas. Sin cómputo, MGeller hace las mismas comprobaciones a mano con las herramientas de Genie Code y marca cada validación automática como `no-ejecutada` |
| **Dependencias de Python** | Ninguna: el motor usa solo la biblioteca estándar | — |
| **PyYAML** | Para validar YAML de jobs y bundles | Opcional. Sin él, los YAML quedan como `no-verificado` (nunca como "válidos"), aunque las rutas de notebooks sí se comprueban |
| **`git`** | Para la entrega automática (commit y push) | Opcional. Sin él, la entrega queda pendiente con los pasos exactos |
| **Databricks CLI** | Para `databricks bundle validate` | Opcional. Sin él, queda la validación estática |

Para trabajar con el motor **fuera** de Databricks (en tu computador, en VS Code, en CI) basta con
Python 3.9 o superior; funciona igual sobre una copia local del repositorio.

### 7.2 Instalar la skill en Databricks

Elige **una** de las dos opciones. En ambas, la carpeta de la skill debe llamarse **exactamente**
`mgeller-change-integrity`.

**Opción A — Git folder registrada (recomendada: queda versionada)**

1. Clona este repositorio como *Git folder* de Databricks, por ejemplo en
   `/Workspace/Users/<usuario>/mgeller-change-integrity`.
2. En Genie Code abre **Settings → Add folder** y registra
   `/Workspace/Users/<usuario>/mgeller-change-integrity/skills`.
   Es la carpeta **padre** de la skill (`skills/`), no la carpeta que contiene el `SKILL.md`.

**Opción B — Copia en la carpeta de skills**

- Personal: `/Users/<usuario>/.assistant/skills/mgeller-change-integrity/`
- Para todo el workspace (requiere administrador): `/Workspace/.assistant/skills/mgeller-change-integrity/`

```bash
databricks workspace import-dir skills/mgeller-change-integrity \
  /Workspace/Users/<usuario>/.assistant/skills/mgeller-change-integrity
```

**Después de instalar o actualizar:** abre un **chat nuevo** en Genie Code. Las ediciones de una
skill no se aplican a chats ya abiertos; si sigues viendo la versión anterior, recarga la pestaña.

> **Nota de estado.** Estas rutas y pasos siguen la documentación de Azure Databricks consultada el
> 2026-10-13 (ver [entorno-genie-code.md](skills/mgeller-change-integrity/references/entorno-genie-code.md)).
> Lo que dice la documentación no garantiza que esté disponible en tu sesión, y **MGeller todavía no
> se ha probado dentro de un workspace real de Databricks** (ver [sección 17](#17-estado-limitaciones-y-pendientes)).

## 8. Cómo usarlo en Genie Code

### 8.1 La invocación

Después de modificar un notebook, en un chat nuevo de Genie Code (modo Agent) escribe:

```text
@mgeller-change-integrity Revisa los cambios que acabamos de realizar en este producto de datos,
corrige todas las inconsistencias relacionadas y prepara los cambios para producción.
```

También se carga sola cuando tu mensaje encaja con su descripción: "revisa los cambios", "deja todo
consistente", "actualiza la documentación y el diccionario", "prepara el cambio para producción",
o cuando renombras, agregas o eliminas columnas, tablas, notebooks o tasks.

"**Preparar para producción**" significa: consistente, validado y publicado en una rama de trabajo
lista para Pull Request. **MGeller nunca despliega.**

### 8.2 Los tres estados finales

Cada ejecución termina con **exactamente uno** de estos estados:

| Estado | Cuándo | Qué significa para ti |
|---|---|---|
| ✅ **VALIDADO** | 0 errores, todas las pruebas obligatorias en `ok` y push verificado | Listo para abrir el Pull Request |
| 🟡 **VALIDADO CON PENDIENTES** | Sin errores críticos, pero queda algo: un conflicto de negocio que requiere decisión, una validación `no-ejecutada`, metadata viva por actualizar o una entrega Git pendiente por límites del entorno | Revisa la lista de pendientes antes de abrir el Pull Request |
| ⛔ **BLOQUEADO** | Errores críticos sin resolver, pruebas obligatorias fallidas o una entrega rechazada por una salvaguarda que requiere tu decisión | No avances hasta resolver lo indicado |

Las validaciones individuales se distinguen así: `ok`, `fallo`, `no-ejecutada` (con el motivo) y
`no-verificado` (el motor no puede dar fe de ello). El motor también usa `parcial` y `no-aplica`
cuando una comprobación solo pudo hacerse en parte o no corresponde al producto.

### 8.3 El reporte

El reporte sigue la [plantilla](skills/mgeller-change-integrity/references/plantilla-reporte.md):

1. **Cambio identificado** (solicitado, implementado, consecuencias esperadas).
2. **Alcance analizado** (raíz, cantidad de archivos por tipo, tablas, jobs, archivos sensibles excluidos).
3. **Inconsistencias** con severidad (`crítica`, `alta`, `media`, `baja`), regla y ubicación `archivo:línea`.
4. **Correcciones aplicadas** y la fuente de verdad que las respaldó.
5. **Validaciones** con su estado.
6. **Pendientes** (conflictos, operaciones sobre ambientes vivos, permisos o validaciones que faltan).
7. **Git** (modo, rama, archivos del commit, hash, mensaje y resultado del push).

El reporte es breve, usa solo hechos verificados, cita `archivo:línea` en vez de repetir contenido
y **nunca incluye valores secretos**.

## 9. Usar el motor por línea de comandos

El motor se puede usar solo, sin IA, sobre cualquier copia local de un producto de datos. Es útil
para revisiones rápidas, para integrarlo en CI o para entender qué hace la skill por debajo.

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py --help
python3 skills/mgeller-change-integrity/scripts/mgeller.py --version
```

### 9.1 Los nueve comandos

| Comando | Para qué sirve | Opciones principales |
|---|---|---|
| `inventario` | Clasifica los archivos del producto y dibuja el grafo de dependencias | `--raiz` (obligatoria), `--detectar-raiz` (sube hasta `databricks.yml` o la raíz Git), `--json` |
| `cambios` | Reconstruye el cambio desde Git (o desde una copia de referencia) | `--raiz`, `--base <rev>` (por defecto `HEAD`), `--referencia <carpeta>` (versión previa si no hay Git), `--max-lineas`, `--json` |
| `impacto` | Encuentra todas las apariciones de uno o más términos, con su contexto y dependencias | `--raiz`, `--termino` (repetible, obligatorio), `--regex`, `--mayusculas`, `--json` |
| `validar` | Validaciones estáticas del producto | `--raiz`, `--archivos` (limita la sintaxis a esos archivos), `--obsoleto` (repetible), `--bundle-cli`, `--target`, `--json` |
| `uc-sql` | Imprime SQL **de solo lectura** para leer la metadata de Unity Catalog | `--tabla catalogo.esquema.tabla` (repetible) |
| `contrastar-uc` | Compara la metadata exportada de Unity Catalog con diccionarios y DDL | `--raiz`, `--uc <archivo.json>`, `--json` |
| `secretos` | Busca secretos en archivos (nunca muestra el valor) | `archivos...`, `--json` |
| `git-estado` | Estado de Git y línea base de cambios preexistentes | `--raiz`, `--protegidas`, `--guardar-linea-base <ruta fuera del repo>` |
| `git-entregar` | Commit y push protegidos de los archivos del alcance | `--raiz`, `--archivos`, `--mensaje`, `--linea-base` / `--sin-linea-base`, `--cambio-original`, `--rama-trabajo`, `--protegidas`, `--push`, `--token-env`, `--autorizar-mezcla` |

**Códigos de salida.** `validar`, `contrastar-uc` y `secretos` terminan con `1` si encuentran
errores o secretos y con `0` si todo está limpio, lo que permite usarlos como compuerta en CI.
Con `--json` la salida es legible por máquina.

**Cómo busca `impacto`.** Es de **palabra completa** y **no distingue mayúsculas** por defecto;
`--mayusculas` activa la distinción y `--regex` interpreta el término como expresión regular.
Clasifica cada aparición por contexto: `codigo`, `cadena`, `comentario`, `docstring`, `markdown`,
`sql`, `json-clave`/`json-valor`, `yaml` y `documentacion`.

### 9.2 Recetas rápidas

```bash
# ¿Dónde se usa esta columna? (usa el nombre anterior y el nuevo)
python3 skills/mgeller-change-integrity/scripts/mgeller.py impacto --raiz <producto> \
  --termino FechaNacimiento --termino FechaNacimientoCliente

# ¿Quedó algo del nombre viejo? ¿Está todo consistente?
python3 skills/mgeller-change-integrity/scripts/mgeller.py validar --raiz <producto> --obsoleto FechaNacimiento

# ¿Hay secretos en estos archivos?
python3 skills/mgeller-change-integrity/scripts/mgeller.py secretos notebooks/*.py resources/*.yml

# Leer la metadata de Unity Catalog (genera SQL de solo lectura; tú lo ejecutas y exportas el resultado)
python3 skills/mgeller-change-integrity/scripts/mgeller.py uc-sql --tabla main.clientes.sat_cliente
python3 skills/mgeller-change-integrity/scripts/mgeller.py contrastar-uc --raiz <producto> --uc filas_uc.json
```

`uc-sql` imprime, por ejemplo:

```sql
-- main.clientes.sat_cliente: columnas (solo lectura)
SELECT table_catalog, table_schema, table_name, column_name, data_type, is_nullable, comment, ordinal_position
FROM `main`.information_schema.columns
WHERE table_schema = 'clientes' AND table_name = 'sat_cliente'
ORDER BY ordinal_position;
```

### 9.3 Desde una celda de Databricks

Dentro de Genie Code, la skill ejecuta el motor desde una celda Python con un pequeño envoltorio
(está en el [SKILL.md](skills/mgeller-change-integrity/SKILL.md)) que localiza el script en las
rutas estándar de skills y lo invoca con `subprocess`. No necesitas hacerlo a mano.

## 10. Qué revisa: reglas y códigos de hallazgo

### 10.1 Las seis reglas de consistencia

El detalle completo está en [reglas-consistencia.md](skills/mgeller-change-integrity/references/reglas-consistencia.md).

| Regla | Qué revisa | Ejemplos de lo que atrapa |
|---|---|---|
| **R1** Código ↔ comentarios, headers, docstrings y documentación | Que el texto que rodea al código describa lo que el código hace hoy | Un comentario que dice "se elimina X" cuando ahora se conserva; un encabezado de notebook con el destino o la clave anteriores; un README que cita una tabla que ya no existe |
| **R2** Notebook ↔ notebook | Que los consumidores de una tabla sigan siendo compatibles con lo que ahora produce el notebook | Columnas, tipos, nulabilidad y supuestos (unicidad, grano, filtros); parámetros compartidos; funciones auxiliares; `%run`; orden de ejecución en el job |
| **R3** Diccionarios de datos JSON | Que el diccionario coincida con el DDL y con la salida real | Columnas faltantes o sobrantes, tipos distintos, descripciones que no coinciden con el `COMMENT`. Respeta el formato del archivo: no reordena ni "normaliza" |
| **R4** Metadata de Unity Catalog | Que lo que hay en UC coincida con el repositorio | Columnas solo en UC o solo en el repo, tipos y descripciones distintos o ausentes. Lee UC solo con `SELECT`; la actualización de metadata viva se entrega como SQL pendiente |
| **R5** YAML, jobs y bundles | Que jobs y bundles apunten a cosas que existen y sean coherentes | Rutas de notebooks inexistentes, dependencias rotas, tasks duplicadas, ciclos, variables sin declarar |
| **R6** Tiempos y metodología de procesamiento | Que las descripciones de la estrategia de carga sigan siendo ciertas | Pasar de carga completa a incremental y que la documentación aún diga "completa". **Nunca inventa duraciones**: sin evidencia, escribe "pendiente de medir" |

### 10.2 Severidad

| Severidad | Significado |
|---|---|
| **crítica** | El producto falla o produce datos incorrectos |
| **alta** | Un consumidor o un job se rompe, o la metadata contradice los datos |
| **media** | Documentación o comentarios engañosos |
| **baja** | Redacción o formato |

Las severidades del **motor** son otras, más simples: `error`, `advertencia`, `info` y
`no-verificado`. La IA las traduce a las severidades del reporte según el contexto.

### 10.3 Códigos de hallazgo del motor

| Código | Severidad del motor | Qué significa |
|---|---|---|
| `JSON-SINTAXIS` | error | Un archivo JSON no se puede leer (coma de más, llave sin cerrar…) |
| `YAML-SINTAXIS` | error / no-verificado | YAML mal formado; sin PyYAML se marca `no-verificado` |
| `PY-SINTAXIS` | error | Error de sintaxis en Python/PySpark (se revisa celda por celda en notebooks) |
| `NB-REFERENCIA` | error | Un `%run` o `dbutils.notebook.run` apunta a un notebook que no existe |
| `IMPORT-LOCAL` | error | Se importa un nombre de un módulo local que ya no existe en él |
| `OBSOLETO` | error | Aparece un término que declaraste obsoleto con `--obsoleto` |
| `OBSOLETO-HISTORICO` | info | El término obsoleto aparece en un `CHANGELOG`: es historia y se conserva |
| `SECRETO` | error | Posible secreto en un archivo (el valor nunca se muestra) |
| `BUNDLE` | no-verificado | Sin PyYAML no se pueden verificar tasks, dependencias ni variables del bundle |
| `BUNDLE-CARGA` | error | No se pudo cargar `databricks.yml` o uno de sus `include` |
| `BUNDLE-VARIABLE` | error | Se usa `${var.x}` y `x` no está declarada |
| `BUNDLE-CLI` | error / no-verificado | `databricks bundle validate` falló o excedió 300 s; o no se pudo ejecutar (sin CLI, o target productivo omitido a propósito) |
| `JOB-RUTA` | error / no-verificado | Una task apunta a un notebook, archivo Python o SQL que no existe, o la ruta está vacía. Las rutas absolutas o con variables quedan `no-verificado` |
| `JOB-DEPENDENCIA` | error | Una task depende de otra que no existe en el job |
| `JOB-TASK-DUPLICADA` | error | Dos tasks del mismo job comparten `task_key` |
| `JOB-CICLO` | error | Las tasks de un job dependen unas de otras en círculo |
| `PIPELINE-RUTA` | error | Una librería de pipeline apunta a un archivo que no existe |
| `DICC-COLUMNA-FALTANTE` | error | Una columna está en el DDL pero no en el diccionario |
| `DICC-COLUMNA-SOBRANTE` | error | Una columna está en el diccionario pero no en el DDL |
| `DICC-TIPO` | error | El tipo en el diccionario difiere del DDL (se normalizan alias: `INTEGER` = `INT`, `LONG` = `BIGINT`…) |
| `DICC-DESCRIPCION` | advertencia | La descripción del diccionario difiere del `COMMENT` del DDL |
| `UC-COLUMNA-SOLO-EN-UC` | advertencia | La columna existe en Unity Catalog pero no en el repositorio |
| `UC-COLUMNA-SOLO-EN-REPO` | advertencia | La columna existe en el repositorio pero no en UC (puede ser un cambio aún no desplegado) |
| `UC-DESCRIPCION` | advertencia | La descripción en UC difiere de la del repositorio |
| `UC-SIN-COMMENT` | advertencia | La columna no tiene comentario en UC |
| `UC-TIPO` | error | El tipo en UC difiere del tipo en el repositorio |

> Una diferencia con Unity Catalog **no dice por sí sola cuál versión es la correcta**: esa decisión
> se toma en la Fase 5 con el orden de prioridad de la [sección 5.2](#52-qué-lado-manda-cuando-dos-cosas-se-contradicen).

### 10.4 Tipos de archivo que entiende

Notebooks de Databricks en formato fuente (archivos cuya primera línea es
`Databricks notebook source`, en Python, SQL o Scala), notebooks `.ipynb`, módulos Python, SQL y DDL,
JSON, YAML (jobs y `databricks.yml`), documentación en Markdown y texto, y archivos de dependencias
(`requirements.txt`, `pyproject.toml`, `environment.yml`…). Las celdas `%scala` y `%r` **no se
compilan**: se reportan como `no-verificado`.

## 11. Git protegido: cómo se entrega sin riesgo

El alcance de Git es **el cambio de desarrollo validado más las correcciones de MGeller**, nunca el
despliegue. La entrega solo se intenta cuando no quedan errores críticos ni pruebas obligatorias
fallidas. Guía completa: [git-protegido.md](skills/mgeller-change-integrity/references/git-protegido.md).

### 11.1 Las tres rutas

`git-estado` detecta el modo de trabajo:

| Modo | Qué significa | Qué pasa |
|---|---|---|
| `git-local` | Hay una copia de trabajo con `.git` y el programa `git` | **Ruta A** — automática (commit y push) |
| `git-folder-databricks` | Carpeta en `/Workspace/...` sin `.git` expuesto (Git folder) | **Ruta B** — MGeller prepara la entrega y tú haces el último paso a mano |
| `sin-git` | No hay repositorio | La entrega queda pendiente y se reporta |

### 11.2 Ruta A — qué hace el motor, paso a paso

1. **Antes de editar**, `git-estado --guardar-linea-base` registra qué archivos ya tenían cambios y
   su huella (hash), en un archivo **fuera** del repositorio.
2. Cada archivo modificado se clasifica como: **cambio validado** (ya estaba modificado y es el
   cambio que pediste revisar), **corrección de MGeller** (no estaba modificado) o **ajeno**
   (estaba modificado pero no pertenece al cambio: queda **fuera** del commit y se reporta).
3. `git-entregar` **rechaza sin tocar nada** si: falta la línea base, hay archivos sensibles o
   secretos, se coló un archivo ajeno, la rama de trabajo es protegida o ya existe, o hay un merge
   o rebase en curso.
4. Si estás en una rama protegida, crea la rama de trabajo con `git switch -c` (conserva tu árbol
   de trabajo sin descartar nada).
5. Hace `git add -- <archivos>` y `git commit --only -- <archivos>`: lo que otra persona tuviera
   en *stage* **no entra** en el commit. Después verifica que el commit contenga exactamente esos
   archivos.
6. Con `--push`: `git push --set-upstream origin HEAD:refs/heads/<rama>` (nunca `--force`) y
   confirma con `git ls-remote` que el remoto apunta al hash del commit.

La rama de trabajo sigue la convención visible del repo (`fix/<desc>`, `feature/<desc>`…); si no
hay ninguna, usa `mgeller/<aaaammdd>-<desc>`. El mensaje del commit sigue la convención del
historial; si no hay, [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/):
`fix(<producto>): alinea <qué> tras <cambio>`.

### 11.3 Ramas protegidas

Por defecto: `main`, `master`, `develop`, `development`, `release`, `release/*`, `releases/*`,
`prod`, `prd`, `production`, `produccion` y `hotfix/*`. Se pueden cambiar con `--protegidas` o
agregar más con la variable de entorno `MGELLER_RAMAS_PROTEGIDAS` (lista separada por comas).

### 11.4 Lo que nunca hace

`git add .` · `git add -A` · `git commit -a` · `git push --force` · `git reset --hard` ·
`git rebase` · `git clean` · `git checkout -- <archivo>` · `git stash` sobre trabajo ajeno · push
a una rama protegida. Una de las pruebas automáticas verifica que el código del motor no contenga
ninguna de estas operaciones.

### 11.5 Ruta B — Git folders de Databricks

Las Git folders no exponen `.git` al cómputo y Databricks no ofrece una API pública para hacer
commit y push desde una Git folder. Por eso MGeller valida y corrige igual, pero **prepara** la
entrega: te indica la rama sugerida, la lista exacta de archivos y el mensaje del commit, y tú haces
el paso final en el diálogo Git de la Git folder (crear o cambiar a la rama, marcar **solo** esos
archivos, pegar el mensaje, *Commit & Push*). Mientras no lo confirmes, el estado Git queda
`pendiente`.

### 11.6 Credenciales

Si el push necesita un token, debes proveerlo en una **variable de entorno** (por ejemplo, leído de
un *secret scope* con `dbutils.secrets.get`) e indicarlo con `--token-env NOMBRE`. El token viaja
como cabecera HTTP mediante variables de entorno de Git; **nunca** se escribe en la URL, en la
configuración del repositorio ni en la salida.

## 12. Seguridad

- **Archivos sensibles:** el motor no los lee, no imprime su contenido y bloquea su commit. Patrones:
  `.env`, `.env.*`, `*.pem`, `*.key`, `*.pfx`, `*.p12`, `*.jks`, `id_rsa*`, `id_ed25519*`,
  `credentials*.json`, `token*.json`, `secret*.json|yml|yaml`, `secrets*`, `.databrickscfg`,
  `.netrc` y `*.keystore`. Se exceptúa `.env.example`.
- **Detección de secretos** en archivos de texto: tokens de Databricks, claves privadas, claves de
  almacenamiento de Azure, firmas SAS, claves de AWS, tokens de GitHub, cadenas JDBC con contraseña y
  asignaciones del tipo `password = "..."`. **Nunca se muestra el valor**, solo el tipo y la línea.
  Las líneas que usan `dbutils.secrets` o `{{secrets/...}}` se consideran correctas.
- **Tokens Git:** solo por variable de entorno (`--token-env`); nunca en la URL ni en la
  configuración del repositorio.
- **Sin escrituras en producción:** ni Unity Catalog, ni jobs, ni despliegues. La metadata viva queda
  como SQL pendiente.
- **Validación de bundles:** `databricks bundle validate` solo se ejecuta contra targets **no
  productivos**; nunca se usa `deploy` para validar sintaxis.

## 13. Estructura del repositorio y pruebas

```text
mgeller-change-integrity/
├── README.md                          ← este documento
├── CHANGELOG.md                       ← historial de versiones
├── LICENSE                            ← términos de uso (propietario / uso interno)
├── Makefile                           ← atajos: test, lint, verificar
├── .gitignore
├── skills/
│   └── mgeller-change-integrity/      ← LA SKILL: lo único que se instala en Genie Code
│       ├── SKILL.md                   ← flujo de fases 0 a 9, reglas de oro, estados finales
│       ├── references/
│       │   ├── reglas-consistencia.md ← reglas R1 a R6 y clasificación de hallazgos
│       │   ├── entorno-genie-code.md  ← qué puede y qué no puede hacer el entorno
│       │   ├── git-protegido.md       ← procedimiento de entrega a Git (rutas A y B)
│       │   └── plantilla-reporte.md   ← formato del reporte final
│       └── scripts/
│           └── mgeller.py             ← el motor determinista (solo biblioteca estándar)
├── tests/
│   ├── test_mgeller.py                ← escenarios de validación
│   └── fixtures/producto_clientes/    ← producto de ejemplo: notebooks, DDL, JSON, bundle, docs
└── herramientas/
    └── lint_skill.py                  ← valida la skill contra la especificación de Agent Skills
```

### 13.1 Verificación local

```bash
make verificar      # lint de la skill + todas las pruebas
make test           # solo las pruebas
make lint           # solo el lint de SKILL.md
```

O sin `make`: `python3 -m unittest discover -s tests -v`. El lint (`herramientas/lint_skill.py`)
necesita PyYAML (`pip install pyyaml`).

### 13.2 Qué cubren las 28 pruebas

Son **27 escenarios de comportamiento más 1 prueba que valida el formato de la skill**. Los escenarios
crean repositorios Git temporales con un remoto local, así que no tocan nada de tu entorno.

| Escenario | Qué demuestra |
|---|---|
| **Columna renombrada** | Reconstruye el cambio desde Git; el impacto alcanza al consumidor, al diccionario JSON, al DDL, al encabezado, a los comentarios y al README; una corrección parcial queda delatada por el contraste diccionario/DDL; tras la corrección integral, 0 errores |
| **Cambio de job** | Un notebook renombrado produce `JOB-RUTA`; un cambio de horario localiza `docs/OPERACION.md`; detecta ciclos, dependencias y variables sin declarar; `bundle validate` nunca se ejecuta contra producción |
| **Código** | Función compartida renombrada (`IMPORT-LOCAL`), sintaxis de notebook/JSON/YAML, `%run` roto, secretos sin imprimir el valor |
| **Git protegido** | Rama de trabajo desde `main`, commit solo del alcance, push verificado, rechazo de trabajo ajeno, secretos, `.env`, ramas protegidas, ausencia de línea base y archivos que ya estaban en *stage* |
| **Sin PyYAML** | Los YAML nunca se dan por válidos; las rutas de notebooks se siguen comprobando |
| **Unidades** | DDL con tipos compuestos, diccionarios en formato de mapa, normalización de tipos, SQL dentro de f-strings, ramas protegidas |
| **Lint** | `SKILL.md` cumple la especificación de Agent Skills |

**Resultado verificado** (octubre de 2026): las 28 pruebas pasan con **Python 3.9** (con PyYAML) y con
**Python 3.12** (sin PyYAML instalado; en esa configuración se omiten 2 pruebas que lo requieren).

## 14. Preguntas frecuentes

**¿MGeller cambia la lógica de mi negocio?**
No. Corrige lo que *describe* el comportamiento (comentarios, documentación, diccionarios, DDL) y
lo que *depende* de un nombre (consumidores, rutas). Si para que algo cuadre habría que cambiar la
lógica y hay dos comportamientos posibles, no aplica ninguno: lo registra como conflicto en
*Pendientes* para que alguien decida.

**¿Puede desplegar mi cambio a producción?**
No. Su límite es dejar el cambio en una rama de trabajo lista para Pull Request. No ejecuta
`bundle deploy`, jobs ni reprocesos.

**¿Qué pasa con la metadata de Unity Catalog?**
La lee (solo con `SELECT` sobre `information_schema`) y la contrasta con el repositorio. Si debe
cambiar, deja el SQL (`ALTER TABLE … COMMENT`, `COMMENT ON …`) preparado como operación pendiente;
solo lo ejecutaría con tu autorización explícita **y** en un ambiente verificado como no productivo.

**¿Funciona fuera de Databricks?**
El motor sí: es Python estándar y trabaja sobre una copia local del repositorio (VS Code, terminal,
CI); ahí la entrega a Git (Ruta A) es la normal y `databricks bundle validate` corre si el CLI está
instalado y autenticado. La skill como tal está escrita para Genie Code: usa sus herramientas y las
rutas de un workspace de Databricks.

**¿Necesito instalar algo en el cómputo de Databricks?**
No. El motor usa solo la biblioteca estándar y MGeller no instala dependencias nuevas para validar.
PyYAML, `git` y Databricks CLI son opcionales; si faltan, lo que dependa de ellos queda
`no-ejecutada` o `no-verificado` y el reporte lo dice.

**¿Y si mi diccionario de datos tiene otro formato?**
El motor reconoce diccionarios con forma `{tabla|table|nombre, columnas|columns|campos: [...]}` y
mapas columna → atributos. Si el tuyo es distinto, la IA lo compara manualmente y lo declara en el
reporte.

**¿Reescribe las duraciones que menciona la documentación?**
No. Una duración solo se actualiza con evidencia (por ejemplo, el historial de ejecuciones). Sin
evidencia, separa lo comprobado de lo que falta medir: "duración: pendiente de medir".

**¿Qué hace si en el mismo archivo hay cambios de otra persona?**
No los incluye en el commit sin tu autorización y los reporta. La línea base guardada en la Fase 0 es
justo lo que permite distinguir tu cambio del trabajo ajeno.

**¿Por qué mi resultado dice `VALIDADO CON PENDIENTES` y no `VALIDADO`?**
Porque algo quedó sin cerrar y MGeller no lo oculta: una validación que no se pudo ejecutar, un
conflicto de negocio que requiere decisión, SQL de metadata preparado pero sin ejecutar, o una
entrega Git que depende de un paso manual. La lista exacta está en la sección *Pendientes* del reporte.

**¿Qué pasa si el producto sigue un estándar propio (por ejemplo un `STANDARDS.md`)?**
Lo respeta como convención del producto. MGeller es independiente y no invoca ni modifica otras skills.

## 15. Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| No veo la skill en Genie Code | La carpeta no se llama exactamente `mgeller-change-integrity`, o registraste la carpeta equivocada | Verifica el nombre. En la Opción A registra la carpeta **padre** (`skills/`), no la que contiene `SKILL.md` |
| Sigo viendo la versión anterior de la skill | Las ediciones no se aplican a chats abiertos | Abre un chat **nuevo** y, si persiste, recarga la pestaña |
| Las skills no hacen nada | Genie Code no está en **modo Agent** | Cambia a modo Agent (las skills solo funcionan ahí) |
| Las validaciones salen `no-ejecutada` | No hay cómputo adjunto o no se puede leer `/Workspace/...` desde el cómputo | Adjunta un cómputo (serverless sirve) y verifica con `os.path.exists("/Workspace/...")`. Mientras tanto MGeller revisa a mano con las herramientas de Genie Code |
| Los YAML aparecen como `no-verificado` | PyYAML no está disponible | Si tu equipo lo permite, instala PyYAML en el cómputo (`pip install pyyaml`) para tener validación completa. MGeller no instala nada por su cuenta, y sin PyYAML nunca da un YAML por válido |
| `bundle validate` aparece `no-ejecutada` | No hay Databricks CLI, o el target es productivo | Instala y autentica el CLI y pasa `--bundle-cli --target <dev>` con un target **no productivo** |
| `git-entregar` responde `rechazado` | Una salvaguarda se activó: falta la línea base, hay archivos sensibles o secretos, se coló un archivo ajeno, la rama de trabajo es protegida o ya existe, hay un merge/rebase en curso | Lee el campo `rechazos` de la respuesta: dice exactamente cuál y cómo resolverla |
| El push falla por credenciales | El motor no tiene token | Entrega el token en una variable de entorno y usa `--token-env NOMBRE` |
| Estoy en una Git folder y no se hace el commit | Las Git folders no exponen `.git` | Es lo esperado (Ruta B): haz *Commit & Push* desde el diálogo Git con los archivos y el mensaje que MGeller te indica |
| `make verificar` falla en el lint con `ModuleNotFoundError: yaml` | Falta PyYAML en tu Python local | `pip install pyyaml` |
| `impacto` no encuentra un nombre que sé que existe | La búsqueda es de **palabra completa** y no distingue mayúsculas: `FechaNacimiento` no coincide dentro de `FechaNacimientoCliente` ni de `col_FechaNacimiento` | Busca cada variante con `--termino` repetido, o usa `--regex` para coincidencias parciales (`--mayusculas` hace que sí distinga mayúsculas) |

## 16. Glosario

| Término | Qué significa |
|---|---|
| **Producto de datos** | Conjunto de notebooks, tablas, jobs, documentación y metadata que juntos entregan un dato listo para que otros lo usen |
| **Notebook** | Documento de Databricks formado por celdas de código (Python, SQL…) y texto que se ejecuta paso a paso |
| **Tabla productora / consumidora** | La que *escribe* un dato / la que lo *lee* |
| **Columna** | Un campo de una tabla, por ejemplo `FechaNacimiento` |
| **DDL** | *Data Definition Language*: las instrucciones SQL (`CREATE TABLE …`) que definen cómo es una tabla |
| **Diccionario de datos** | Archivo (aquí, JSON) que describe cada columna: nombre, tipo y descripción |
| **Unity Catalog (UC)** | El catálogo central de Databricks donde viven las tablas y su metadata |
| **`information_schema`** | Vistas de solo lectura de Unity Catalog con la lista de tablas y columnas |
| **Metadata** | Datos sobre los datos: descripciones, tipos, comentarios |
| **Job / task** | Un proceso programado de Databricks / cada paso individual dentro de un job |
| **Declarative Automation Bundles (DABs) y `databricks.yml`** | El archivo de configuración que describe jobs y su despliegue como código |
| **Genie Code** | El asistente de IA de Databricks. En *modo Agent* puede ejecutar tareas de varios pasos |
| **Skill (Agent Skill)** | Carpeta con un `SKILL.md` (más `scripts/` y `references/`) que enseña a un asistente una tarea especializada, según la especificación abierta de Agent Skills |
| **Motor** | El programa `mgeller.py`: hace las comprobaciones mecánicas sin usar IA |
| **Línea base** | Foto de los cambios pendientes antes de que MGeller edite nada; permite distinguir tu cambio del trabajo ajeno |
| **Rama protegida** | Rama (como `main`) a la que nunca se empuja directamente |
| **Rama de trabajo** | Rama nueva creada para un cambio concreto |
| **Commit / push** | Guardar un cambio en el historial de Git / enviarlo al servidor remoto |
| **Pull Request (PR)** | Solicitud para fusionar una rama en otra después de que alguien la revise |
| **Git folder** | Carpeta del workspace de Databricks conectada a un repositorio Git |
| **Serverless** | Cómputo administrado por Databricks que no requiere crear ni configurar un clúster |
| **FACT / DECISION / ASSUMPTION** | Etiquetas de evidencia: verificado / decidido por el usuario / inferido |
| **Conventional Commits** | Convención de mensajes de commit: `tipo(alcance): descripción` |
| **Término obsoleto** | Un nombre que ya no debería aparecer en el producto (por ejemplo, el nombre anterior de una columna) |

## 17. Estado, limitaciones y pendientes

### 17.1 Estado

**v1.0.0, borrador (*draft*).** El motor y los escenarios pasan localmente con Python 3.9 y 3.12, con y
sin PyYAML. **Todavía no se ha probado dentro de un workspace de Azure Databricks.**

### 17.2 Pruebas pendientes en Databricks

No se pueden ejecutar desde fuera del workspace:

1. La skill aparece en *Settings* y se invoca con `@mgeller-change-integrity` en un chat nuevo.
2. `scripts/mgeller.py` se ejecuta desde una celda (serverless y clúster clásico) leyendo `/Workspace/...`.
3. PyYAML, `git` y Databricks CLI: registrar qué hay disponible en el cómputo.
4. Sobre una copia del producto de ejemplo en una Git folder: el escenario de columna renombrada de
   punta a punta, incluida la entrega por el diálogo Git (Ruta B).
5. Lectura de `information_schema` con `uc-sql` + `contrastar-uc` en un catálogo de desarrollo.

### 17.3 Limitaciones conocidas

- **Sin diff ni Git:** reconstruye el cambio con la conversación y el archivo abierto, y deja la
  etiqueta `ASSUMPTION` visible. Con `cambios --referencia <copia_anterior>` puede comparar contra
  una copia de la versión previa.
- **Dentro de una Git folder** no hay `git diff` desde el cómputo: se apoya en la conversación, el
  archivo y una copia de referencia si existe.
- **Un nombre usado en varios productos:** limita las correcciones a la raíz del producto y lista los
  demás como *impacto potencial*.
- **Celdas `%scala` / `%r`:** no se compilan; se reportan como `no-verificado`.
- **Historial completo de la conversación:** MGeller usa solo el contexto que realmente ve.
- **Permisos insuficientes** en Unity Catalog, el workspace o Git: completa lo posible y lista el
  permiso que falta.

## 18. Versionado, autoría y licencia

- **Versión actual:** 1.0.0 — [SemVer](https://semver.org/lang/es/). Historial en [CHANGELOG.md](CHANGELOG.md).
- **Autoría:** Luis Diego Rodríguez Oviedo.
- **Licencia:** todos los derechos reservados; uso interno y propietario. Ver [LICENSE](LICENSE).

**Documentación relacionada**

- [SKILL.md](skills/mgeller-change-integrity/SKILL.md): el flujo operativo completo que sigue el asistente.
- [Reglas de consistencia](skills/mgeller-change-integrity/references/reglas-consistencia.md).
- [Capacidades del entorno](skills/mgeller-change-integrity/references/entorno-genie-code.md).
- [Git protegido](skills/mgeller-change-integrity/references/git-protegido.md).
- [Plantilla del reporte](skills/mgeller-change-integrity/references/plantilla-reporte.md).
