# MGeller — integridad del cambio en productos de datos

Skill para **Databricks Genie Code** (`@mgeller-change-integrity`) que, después de modificar un
producto de datos, encuentra todo lo que ese cambio afecta y lo deja consistente: notebooks
consumidores, comentarios, headers, docstrings, documentación, diccionarios JSON, DDL, metadata de
Unity Catalog, YAML de jobs y Declarative Automation Bundles. Corrige lo inequívoco, valida con
pruebas reales y entrega a Git (commit y push) en una rama de trabajo, sin mezclar trabajo ajeno y
sin desplegar ni escribir en producción.

> Un cambio no se considera completo hasta que el código, la documentación, los metadatos, los
> diccionarios, las configuraciones y las dependencias afectadas describen el comportamiento real.

![Python](https://img.shields.io/badge/python-3.9%E2%80%933.12-blue)
![Licencia](https://img.shields.io/badge/licencia-uso%20interno-lightgrey)

## Estado

**v1.0.0, draft.** El motor y los escenarios pasan localmente con Python 3.9 y 3.12, con y sin
PyYAML. **Todavía no se ha probado dentro de un workspace de Azure Databricks**: falta la sección
[Pruebas en Databricks](#pruebas-en-databricks).

## Requisitos

| Requisito | Detalle |
|---|---|
| Genie Code | Modo Agent, con *partner-powered AI features* habilitadas |
| Cómputo | Cualquiera que ejecute Python 3.9+ (serverless sirve) para `scripts/mgeller.py` |
| Dependencias | Ninguna. PyYAML opcional (sin él, los YAML quedan `no-verificado`) |
| Opcionales | `git` (entrega automática), Databricks CLI (`bundle validate`) |

## Instalación en Databricks

Elige una opción. En ambas la carpeta de la skill debe llamarse exactamente `mgeller-change-integrity`.

**A. Git folder registrada (recomendada, versionada).**
1. Publica este repo en tu proveedor Git (Azure Repos o GitHub) y clónalo como Git folder, por
   ejemplo en `/Workspace/Users/<usuario>/mgeller-change-integrity`.
2. En Genie Code: **Settings → Add folder** y registra
   `/Workspace/Users/<usuario>/mgeller-change-integrity/skills` (la carpeta *padre* de la skill, no la
   que contiene `SKILL.md`).

**B. Copia en la carpeta de skills.**
- Personal: `/Users/<usuario>/.assistant/skills/mgeller-change-integrity/`
- Workspace (admin): `/Workspace/.assistant/skills/mgeller-change-integrity/`

```bash
databricks workspace import-dir skills/mgeller-change-integrity /Workspace/Users/<usuario>/.assistant/skills/mgeller-change-integrity
```

Abre un **chat nuevo** después de instalar o actualizar la skill (las ediciones no aplican a chats
abiertos; si ves la versión anterior, recarga la pestaña).

## Uso

En Genie Code, después de modificar un notebook:

```
@mgeller-change-integrity Revisa los cambios que acabamos de realizar en este producto de datos,
corrige todas las inconsistencias relacionadas y prepara los cambios para producción.
```

"Preparar para producción" = consistente, validado y publicado en una rama de trabajo lista para
Pull Request. MGeller nunca despliega.

El motor también funciona fuera de Databricks, sobre una copia local del repositorio:

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py inventario --raiz <producto>
```

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py impacto --raiz <producto> --termino FechaNacimiento
```

```bash
python3 skills/mgeller-change-integrity/scripts/mgeller.py validar --raiz <producto> --obsoleto FechaNacimiento
```

## Estructura

```
mgeller-change-integrity/
├── skills/mgeller-change-integrity/   # la skill (lo que se instala en Genie Code)
│   ├── SKILL.md                       # flujo de 9 fases, reglas y estados finales
│   ├── references/                    # reglas R1–R6, entorno, Git protegido, plantilla de reporte
│   └── scripts/mgeller.py             # motor determinista (solo biblioteca estándar)
├── tests/
│   ├── fixtures/producto_clientes/    # producto de ejemplo: notebooks, DDL, JSON, bundle, docs
│   └── test_mgeller.py                # escenarios de validación
└── herramientas/lint_skill.py         # valida la skill contra la especificación de Agent Skills
```

## Verificación local

```bash
make verificar
```

Los escenarios crean repos Git temporales con un remoto local y cubren:

| Escenario | Qué demuestra |
|---|---|
| Columna renombrada | Reconstruye el cambio desde Git; el impacto alcanza al consumidor, el diccionario JSON, el DDL, el header, comentarios y README; la corrección parcial queda delatada por diccionario vs DDL; tras la corrección integral, 0 errores |
| Cambio de job | Notebook renombrado ⇒ `JOB-RUTA`; cambio de horario ⇒ localiza `docs/OPERACION.md`; ciclos, dependencias y variables no declaradas; `bundle validate` nunca contra prod |
| Código | Función compartida renombrada (`IMPORT-LOCAL`), sintaxis de notebook/JSON/YAML, `%run` roto, secretos sin imprimir el valor |
| Git protegido | Rama de trabajo desde `main`, commit solo del alcance, push verificado con `ls-remote`, rechazo de trabajo ajeno, secretos, `.env`, ramas protegidas, ausencia de línea base, archivos ya en stage |
| Sin PyYAML | Los YAML nunca se dan por válidos; las rutas de notebooks se siguen comprobando |

## Pruebas en Databricks

Pendientes; no se pueden ejecutar desde fuera del workspace:

1. La skill aparece en *Settings* y se invoca con `@mgeller-change-integrity` en un chat nuevo.
2. `scripts/mgeller.py` se ejecuta desde una celda (serverless y clúster clásico) leyendo `/Workspace/...`.
3. PyYAML, `git` y Databricks CLI: registrar qué hay disponible en el cómputo.
4. Sobre una copia del producto de ejemplo en una Git folder: escenario de columna renombrada de
   punta a punta, incluida la entrega por el diálogo Git (Ruta B).
5. Lectura de `information_schema` con `uc-sql` + `contrastar-uc` en un catálogo de desarrollo.

## Seguridad

- El motor no lee archivos sensibles (`.env`, llaves, `credentials*.json`…), no imprime valores
  secretos y bloquea su commit.
- Los tokens Git solo se aceptan por variable de entorno (`--token-env`) y viajan como cabecera HTTP;
  nunca en la URL ni en la configuración del repo.
- Sin escrituras en Unity Catalog, jobs ni despliegues: la metadata viva queda como SQL pendiente.

## Documentación

- [SKILL.md](skills/mgeller-change-integrity/SKILL.md): flujo operativo.
- [Reglas de consistencia](skills/mgeller-change-integrity/references/reglas-consistencia.md).
- [Capacidades del entorno](skills/mgeller-change-integrity/references/entorno-genie-code.md).
- [Git protegido](skills/mgeller-change-integrity/references/git-protegido.md).
- [CHANGELOG.md](CHANGELOG.md).

## Licencia

Uso interno. Ver [LICENSE](LICENSE).
