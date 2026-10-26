# Entrega protegida a Git

El alcance de Git es **el cambio de desarrollo validado y las correcciones de MGeller**, nunca el
despliegue. La entrega solo se intenta cuando no quedan errores críticos ni pruebas obligatorias
fallidas.

## 1. Detecta el modo

`mgeller.py git-estado --raiz <RAIZ>` devuelve `modo`:

| Modo | Qué significa | Ruta |
|---|---|---|
| `git-local` | Hay un working tree con `.git` y el binario `git` | **A** |
| `git-folder-databricks` | Carpeta en `/Workspace/...` sin `.git` expuesto (Git folder) | **B** |
| `sin-git` | No hay repositorio | Reporta la entrega como pendiente |

## 2. Ruta A — Git local (automática)

1. **Antes de editar**: `git-estado --guardar-linea-base /tmp/mgeller_linea_base.json` (fuera del repo).
   Registra qué archivos ya tenían cambios y su hash.
2. Revisa en el estado: rama, rama predeterminada del remoto, `rama_protegida`, `operacion_en_curso`,
   archivos en stage y cambios preexistentes.
3. Clasifica cada archivo modificado:
   - **Cambio validado**: ya estaba modificado y es el cambio que el usuario pidió revisar →
     va en `--archivos` y en `--cambio-original`.
   - **Corrección de MGeller**: no estaba modificado en la línea base → va en `--archivos`.
   - **Ajeno**: estaba modificado y no pertenece al cambio → **fuera** del commit; se reporta.
4. Nombre de rama: sigue la convención visible del repo (`git branch -r`, p. ej. `fix/<desc>`,
   `feature/<desc>`); si no hay ninguna, `mgeller/<aaaammdd>-<desc>`.
5. Mensaje: sigue la convención del historial (`git log --oneline -20`); si no hay, Conventional
   Commits: `fix(<producto>): alinea <qué> tras <cambio>` con un cuerpo que liste qué se corrigió.
6. Ejecuta `git-entregar` (ver SKILL.md, Fase 8). El motor:
   - rechaza sin tocar nada si falta la línea base, hay archivos sensibles o secretos, un archivo
     ajeno se coló, la rama de trabajo es protegida o ya existe, o hay merge/rebase en curso;
   - en una rama protegida crea la rama de trabajo con `git switch -c` (conserva el árbol de trabajo
     sin descartar nada);
   - hace `git add -- <archivos>` y `git commit --only -- <archivos>`: lo que otro ya tenía en stage
     no entra en el commit;
   - verifica que el commit contenga exactamente esos archivos;
   - con `--push`: `git push --set-upstream origin HEAD:refs/heads/<rama>` (nunca `--force`) y
     verifica con `git ls-remote` que el remoto apunte al hash del commit.
7. Registra en el reporte: rama, archivos del commit, hash, mensaje y resultado del push **tal como
   los devolvió el motor**.

Credenciales: si el push necesita un token, el usuario debe proveerlo en una variable de entorno
(p. ej. leído de un secret scope con `dbutils.secrets.get` y pasado al proceso), y se indica con
`--token-env NOMBRE`. El token viaja como cabecera HTTP por variables de entorno de Git; nunca se
escribe en la URL, en la configuración del repo ni en la salida.

## 3. Ruta B — Git folder de Databricks

Las Git folders no exponen `.git` al cómputo y Databricks no ofrece una API pública para hacer
commit/push desde una Git folder (la API de Repos solo cambia de rama o actualiza). Por eso:

1. Valida y corrige igual que siempre; `cambios` no tendrá diff de Git: apóyate en la conversación,
   el archivo abierto y, si existe, una copia de referencia (`cambios --referencia`).
2. Prepara la entrega: rama sugerida, lista exacta de archivos, mensaje de commit.
3. Indica al usuario el paso manual en el diálogo Git de la Git folder: crear/cambiar a la rama de
   trabajo, marcar **solo** esos archivos, pegar el mensaje, *Commit & Push*. El estado Git queda
   `pendiente (requiere el diálogo Git de la Git folder)` hasta que el usuario lo confirme.
4. Alternativa automática (solo si el usuario la autoriza explícitamente y hay `git` en el cómputo y un
   token en un secret scope): clonar el remoto en un directorio temporal del driver, copiar ahí los
   archivos del alcance exportados en formato fuente, y ejecutar la Ruta A sobre ese clon con
   `--token-env`. Después, el usuario debe hacer *Pull* en la Git folder. No la uses sin autorización:
   publica desde fuera de la Git folder.

## 4. Nunca

`git add .` · `git add -A` · `git commit -a` · `git push --force` · `git reset --hard` · `git rebase` ·
`git clean` · `git checkout -- <archivo>` · `git stash` sobre trabajo ajeno · push a `main`, `master`,
`develop`, `release/*`, `prod*`, `hotfix/*` o la rama predeterminada del remoto (configurable con
`--protegidas` o la variable `MGELLER_RAMAS_PROTEGIDAS`).
