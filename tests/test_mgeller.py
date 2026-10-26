"""
Escenarios de validación de MGeller.

Cada escenario copia el producto de ejemplo (tests/fixtures/producto_clientes) a un repo Git
temporal con un remoto bare, aplica un cambio de desarrollo realista y comprueba que el motor
(scripts/mgeller.py) lo detecta, mapea su impacto, valida y entrega a Git con las salvaguardas.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parents[1]
SKILL = RAIZ_REPO / "skills" / "mgeller-change-integrity"
SCRIPT = SKILL / "scripts" / "mgeller.py"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "producto_clientes"

sys.path.insert(0, str(SCRIPT.parent))
import mgeller  # noqa: E402

ENV_GIT = {**os.environ, "GIT_AUTHOR_NAME": "Prueba", "GIT_AUTHOR_EMAIL": "prueba@example.com",
           "GIT_COMMITTER_NAME": "Prueba", "GIT_COMMITTER_EMAIL": "prueba@example.com"}


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=ENV_GIT)
    if r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} falló: {r.stderr}")
    return r.stdout.strip()


def correr(*args: str) -> tuple[int, dict | str]:
    r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=ENV_GIT)
    try:
        return r.returncode, json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.returncode, r.stdout + r.stderr


class ProductoTemporal:
    """Repo Git con el producto de ejemplo en `main`, publicado en un remoto bare."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="mgeller-"))
        self.remoto = self.tmp / "remoto.git"
        self.repo = self.tmp / "repo"
        git(self.tmp, "init", "--bare", "-b", "main", str(self.remoto))
        shutil.copytree(FIXTURE, self.repo)
        git(self.repo, "init", "-b", "main")
        git(self.repo, "add", "--", *[p.relative_to(self.repo).as_posix() for p in sorted(self.repo.rglob("*")) if p.is_file()])
        git(self.repo, "commit", "-m", "chore: producto inicial")
        git(self.repo, "remote", "add", "origin", str(self.remoto))
        git(self.repo, "push", "-u", "origin", "main")
        git(self.repo, "remote", "set-head", "origin", "main")

    def ruta(self, rel: str) -> Path:
        return self.repo / rel

    def reemplazar(self, rel: str, viejo: str, nuevo: str, todas: bool = True):
        p = self.ruta(rel)
        texto = p.read_text(encoding="utf-8")
        assert viejo in texto, f"'{viejo}' no está en {rel}"
        p.write_text(texto.replace(viejo, nuevo) if todas else texto.replace(viejo, nuevo, 1), encoding="utf-8")

    def limpiar(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def errores(salida: dict, regla: str | None = None) -> list[dict]:
    return [h for h in salida["hallazgos"] if h["severidad"] == "error" and (regla is None or h["regla"] == regla)]


# ----------------------------------------------------------------------------------------------
# Escenario 1: cambio de columna que exige actualizar notebook dependiente y diccionario JSON
# ----------------------------------------------------------------------------------------------

class EscenarioCambioDeColumna(unittest.TestCase):
    SAT = "notebooks/satellites/Nb_Sat_Cliente.py"
    DIM = "notebooks/dwh/Nb_Dim_Cliente.py"

    def setUp(self):
        self.p = ProductoTemporal()
        # Cambio de desarrollo: el usuario renombra la columna solo en el código del satélite.
        self.p.reemplazar(self.SAT, '.withColumn("FechaNacimiento"', '.withColumn("FechaNacimientoCliente"')
        self.p.reemplazar(self.SAT, '"NombreCliente", "FechaNacimiento",', '"NombreCliente", "FechaNacimientoCliente",')

    def tearDown(self):
        self.p.limpiar()

    def test_reconstruye_el_cambio_desde_git(self):
        codigo, salida = correr("cambios", "--raiz", str(self.p.repo), "--json")
        self.assertEqual(codigo, 0)
        self.assertEqual(list(salida["archivos"]), [self.SAT])
        self.assertIn("FechaNacimientoCliente", salida["senales"]["solo_en_agregadas"])
        # FechaNacimiento sigue en una línea agregada (comentario intacto no cuenta; el select sí cambia)
        self.assertNotIn("FechaNacimientoCliente", salida["senales"]["solo_en_eliminadas"])

    def test_mapa_de_impacto_va_mas_alla_del_diff(self):
        codigo, salida = correr("impacto", "--raiz", str(self.p.repo), "--termino", "FechaNacimiento",
                                "--termino", "sat_cliente", "--json")
        self.assertEqual(codigo, 0)
        col = salida["terminos"]["FechaNacimiento"]
        for esperado in (self.DIM, "diccionarios/sat_cliente.json", "ddl/sat_cliente.sql", "README.md", self.SAT):
            self.assertIn(esperado, col["archivos"])
        contextos = {(a["archivo"], a["contexto"]) for a in col["apariciones"]}
        self.assertIn((self.SAT, "comentario"), contextos, "el comentario obsoleto del satélite debe aparecer")
        self.assertIn((self.DIM, "docstring"), contextos)
        self.assertIn((self.DIM, "cadena"), contextos, "el consumidor usa la columna en código")
        tabla = salida["terminos"]["sat_cliente"]["dependencias_estructurales"]["tabla"]
        self.assertEqual(tabla["consumidores"], [self.DIM])
        self.assertIn(self.SAT, tabla["productores"])

    def test_detecta_referencias_obsoletas_y_luego_valida_tras_corregir(self):
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--obsoleto", "FechaNacimiento", "--json")
        self.assertEqual(codigo, 1)
        archivos_con_error = {h["archivo"] for h in errores(salida, "OBSOLETO")}
        self.assertTrue({self.DIM, "diccionarios/sat_cliente.json", "ddl/sat_cliente.sql", "README.md", self.SAT}
                        <= archivos_con_error)

        # Corrección parcial: solo el diccionario → el contraste diccionario/DDL lo delata.
        self.p.reemplazar("diccionarios/sat_cliente.json", '"FechaNacimiento"', '"FechaNacimientoCliente"')
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        self.assertEqual(codigo, 1)
        reglas = {h["regla"] for h in errores(salida)}
        self.assertIn("DICC-COLUMNA-FALTANTE", reglas)
        self.assertIn("DICC-COLUMNA-SOBRANTE", reglas)

        # Corrección integral (lo que MGeller aplicaría): DDL, consumidor, comentarios y documentación.
        self.p.reemplazar("ddl/sat_cliente.sql", "FechaNacimiento DATE", "FechaNacimientoCliente DATE")
        self.p.reemplazar(self.DIM, "FechaNacimiento", "FechaNacimientoCliente")
        self.p.reemplazar(self.SAT, "`FechaNacimiento`", "`FechaNacimientoCliente`")
        self.p.reemplazar(self.SAT, "# Se conserva FechaNacimiento", "# Se conserva FechaNacimientoCliente")
        self.p.reemplazar("README.md", "`FechaNacimiento`", "`FechaNacimientoCliente`")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--obsoleto", "FechaNacimiento", "--json")
        self.assertEqual(codigo, 0, json.dumps(errores(salida), ensure_ascii=False, indent=1))


# ----------------------------------------------------------------------------------------------
# Escenario 2: cambio de job que exige revisar YAML y documentación operativa
# ----------------------------------------------------------------------------------------------

class EscenarioCambioDeJob(unittest.TestCase):
    JOB = "resources/job_clientes.yml"

    def setUp(self):
        self.p = ProductoTemporal()

    def tearDown(self):
        self.p.limpiar()

    def test_notebook_renombrado_rompe_la_ruta_del_job(self):
        git(self.p.repo, "mv", "notebooks/dwh/Nb_Dim_Cliente.py", "notebooks/dwh/Nb_Dim_ClienteV2.py")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        self.assertEqual(codigo, 1)
        rutas = errores(salida, "JOB-RUTA")
        self.assertEqual(len(rutas), 1)
        self.assertIn("Nb_Dim_Cliente.py", rutas[0]["mensaje"])
        self.assertEqual(rutas[0]["archivo"], self.JOB)

        self.p.reemplazar(self.JOB, "Nb_Dim_Cliente.py", "Nb_Dim_ClienteV2.py")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        self.assertEqual(codigo, 0, errores(salida))

    def test_cambio_de_horario_localiza_la_documentacion_operativa(self):
        self.p.reemplazar(self.JOB, '"0 0 2 * * ?"', '"0 30 4 * * ?"')
        codigo, salida = correr("cambios", "--raiz", str(self.p.repo), "--json")
        self.assertEqual(list(salida["archivos"]), [self.JOB])
        codigo, salida = correr("impacto", "--raiz", str(self.p.repo), "--termino", "02:00", "--termino", "job_clientes", "--json")
        self.assertIn("docs/OPERACION.md", salida["terminos"]["02:00"]["archivos"])
        self.assertIn("docs/OPERACION.md", salida["terminos"]["job_clientes"]["archivos"])
        # Tras alinear la documentación no queda la hora anterior.
        self.p.reemplazar("docs/OPERACION.md", "diaria a las 02:00", "diaria a las 04:30")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--obsoleto", "02:00", "--json")
        self.assertEqual(codigo, 0, errores(salida))

    @unittest.skipUnless(mgeller.HAY_YAML, "requiere PyYAML")
    def test_dependencias_variables_y_ciclos_del_job(self):
        self.p.reemplazar(self.JOB, "- task_key: sat_cliente\n          notebook_task:",
                          "- task_key: sat_cliente\n          depends_on:\n            - task_key: dim_cliente\n          notebook_task:")
        self.p.reemplazar(self.JOB, "${var.catalogo_dwh}", "${var.catalogo_oro}")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        reglas = {h["regla"] for h in errores(salida)}
        self.assertIn("JOB-CICLO", reglas)
        self.assertIn("BUNDLE-VARIABLE", reglas)
        self.p.reemplazar(self.JOB, "- task_key: sat_cliente\n          depends_on:\n            - task_key: dim_cliente\n",
                          "- task_key: sat_cliente\n")
        self.p.reemplazar(self.JOB, "- task_key: sat_cliente\n          notebook_task",
                          "- task_key: sat_cliente\n          depends_on:\n            - task_key: no_existe\n          notebook_task")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        self.assertIn("JOB-DEPENDENCIA", {h["regla"] for h in errores(salida)})

    def test_bundle_cli_ausente_se_reporta_como_no_verificado(self):
        if shutil.which("databricks"):
            self.skipTest("Databricks CLI presente; este caso cubre su ausencia")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--bundle-cli", "--target", "dev", "--json")
        prueba = next(p for p in salida["pruebas"] if p["prueba"] == "databricks bundle validate")
        self.assertEqual(prueba["estado"], "no-ejecutada")

    def test_bundle_cli_nunca_contra_target_productivo(self):
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--bundle-cli", "--target", "prod", "--json")
        prueba = next(p for p in salida["pruebas"] if p["prueba"] == "databricks bundle validate")
        self.assertEqual(prueba["estado"], "no-ejecutada")


# ----------------------------------------------------------------------------------------------
# Escenario 3: otras inconsistencias de código
# ----------------------------------------------------------------------------------------------

class EscenarioCodigo(unittest.TestCase):
    def setUp(self):
        self.p = ProductoTemporal()

    def tearDown(self):
        self.p.limpiar()

    def test_funcion_compartida_renombrada_rompe_el_import(self):
        self.p.reemplazar("src/utilidades/normalizacion.py", "def normalizar_texto", "def normalizar_cadena")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        imp = errores(salida, "IMPORT-LOCAL")
        self.assertEqual([h["archivo"] for h in imp], ["notebooks/satellites/Nb_Sat_Cliente.py"])

    def test_sintaxis_de_notebook_json_y_yaml(self):
        self.p.reemplazar("notebooks/dwh/Nb_Dim_Cliente.py", "dfDim = (", "dfDim = ((")
        self.p.reemplazar("diccionarios/sat_cliente.json", '"columnas": [', '"columnas": [,')
        self.p.ruta("resources/roto.yml").write_text("a: [1, 2\n", encoding="utf-8")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        reglas = {h["regla"] for h in errores(salida)}
        self.assertTrue({"PY-SINTAXIS", "JSON-SINTAXIS"} <= reglas, reglas)
        if mgeller.HAY_YAML:
            self.assertIn("YAML-SINTAXIS", reglas)
        else:
            self.assertIn("YAML-SINTAXIS", {h["regla"] for h in salida["hallazgos"] if h["severidad"] == "no-verificado"},
                          "sin PyYAML un YAML nunca se da por válido")

    def test_run_a_notebook_inexistente(self):
        nb = self.p.ruta("notebooks/dwh/Nb_Dim_Cliente.py")
        nb.write_text(nb.read_text(encoding="utf-8") + "\n# COMMAND ----------\n\n# MAGIC %run ../comun/Nb_Config\n",
                      encoding="utf-8")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        self.assertIn("NB-REFERENCIA", {h["regla"] for h in errores(salida)})

    def test_secreto_se_detecta_sin_imprimir_su_valor(self):
        valor = "dapi" + "0123456789abcdef" * 2
        nb = self.p.ruta("notebooks/dwh/Nb_Dim_Cliente.py")
        nb.write_text(nb.read_text(encoding="utf-8") + f'\nTOKEN = "{valor}"\n', encoding="utf-8")
        codigo, salida = correr("validar", "--raiz", str(self.p.repo), "--json")
        self.assertIn("SECRETO", {h["regla"] for h in errores(salida)})
        self.assertNotIn(valor, json.dumps(salida))


# ----------------------------------------------------------------------------------------------
# Escenario 4: entrega protegida a Git
# ----------------------------------------------------------------------------------------------

class EscenarioGitProtegido(unittest.TestCase):
    SAT = "notebooks/satellites/Nb_Sat_Cliente.py"
    DIC = "diccionarios/sat_cliente.json"

    def setUp(self):
        self.p = ProductoTemporal()
        self.base = self.p.tmp / "linea_base.json"
        # Trabajo previo ajeno (README) + el cambio de desarrollo a validar (satélite)
        self.p.reemplazar("README.md", "(fixture)", "(fixture, borrador del usuario)")
        self.p.reemplazar(self.SAT, '.withColumn("FechaNacimiento"', '.withColumn("FechaNacimientoCliente"')
        codigo, est = correr("git-estado", "--raiz", str(self.p.repo), "--guardar-linea-base", str(self.base))
        self.assertEqual(codigo, 0)
        self.assertTrue(est["rama_protegida"])
        # Corrección de MGeller
        self.p.reemplazar(self.DIC, '"FechaNacimiento"', '"FechaNacimientoCliente"')

    def tearDown(self):
        self.p.limpiar()

    def entregar(self, *extra: str, archivos=(SAT, DIC)) -> tuple[int, dict]:
        return correr("git-entregar", "--raiz", str(self.p.repo), "--archivos", *[str(self.p.ruta(a)) for a in archivos],
                      "--mensaje", "fix(clientes): alinea FechaNacimientoCliente", "--linea-base", str(self.base),
                      "--cambio-original", self.SAT, *extra)

    def test_entrega_completa_en_rama_de_trabajo(self):
        codigo, r = self.entregar("--rama-trabajo", "mgeller/fecha-nacimiento", "--push")
        self.assertEqual(codigo, 0, r)
        self.assertEqual(r["rama"], "mgeller/fecha-nacimiento")
        self.assertEqual(r["archivos_commit"], sorted([self.SAT, self.DIC]))
        self.assertEqual(r["push"], "completado y verificado")
        self.assertEqual(git(self.p.remoto, "rev-parse", "refs/heads/mgeller/fecha-nacimiento"), r["commit"])
        self.assertEqual(git(self.p.remoto, "rev-parse", "refs/heads/main"), git(self.p.repo, "rev-parse", "main"),
                         "main no se toca")
        self.assertIn("README.md", git(self.p.repo, "status", "--porcelain"), "el trabajo ajeno sigue sin confirmar")

    def test_cambio_original_con_ruta_absoluta(self):
        codigo, r = correr("git-entregar", "--raiz", str(self.p.repo), "--archivos", str(self.p.ruta(self.SAT)),
                           "--mensaje", "fix: x", "--linea-base", str(self.base),
                           "--cambio-original", str(self.p.ruta(self.SAT)), "--rama-trabajo", "mgeller/abs")
        self.assertEqual(codigo, 0, r)
        self.assertEqual(r["archivos_commit"], [self.SAT])

    def test_rechaza_rama_protegida_sin_rama_de_trabajo(self):
        codigo, r = self.entregar("--push")
        self.assertEqual(codigo, 1)
        self.assertEqual(r["resultado"], "rechazado")
        self.assertEqual(git(self.p.repo, "rev-list", "--count", "HEAD"), "1", "no se creó ningún commit")

    def test_rechaza_rama_de_trabajo_protegida(self):
        codigo, r = self.entregar("--rama-trabajo", "release/2026.10")
        self.assertEqual(codigo, 1)

    def test_no_mezcla_cambios_preexistentes_ajenos(self):
        codigo, r = self.entregar("--rama-trabajo", "mgeller/x", archivos=(self.SAT, self.DIC, "README.md"))
        self.assertEqual(codigo, 1)
        self.assertTrue(any("README.md" in m for m in r["rechazos"]))

    def test_exige_linea_base(self):
        codigo, r = correr("git-entregar", "--raiz", str(self.p.repo), "--archivos", str(self.p.ruta(self.DIC)),
                           "--mensaje", "x", "--rama-trabajo", "mgeller/x")
        self.assertEqual(codigo, 1)
        self.assertTrue(any("linea-base" in m for m in r["rechazos"]))

    def test_rechaza_secretos_y_archivos_sensibles(self):
        self.p.ruta(".env").write_text("TOKEN=abc\n", encoding="utf-8")
        nb = self.p.ruta(self.DIC)
        nb.write_text(nb.read_text(encoding="utf-8").replace('"Atributos', '"password": "SuperSecreta123", "x": "Atributos'),
                      encoding="utf-8")
        codigo, r = self.entregar("--rama-trabajo", "mgeller/x", archivos=(self.SAT, self.DIC, ".env"))
        self.assertEqual(codigo, 1)
        texto = " ".join(r["rechazos"])
        self.assertIn(".env", texto)
        self.assertIn("posible secreto", texto)
        self.assertNotIn("SuperSecreta123", json.dumps(r))
        self.assertEqual(git(self.p.repo, "rev-parse", "--abbrev-ref", "HEAD"), "main", "no se cambió de rama")

    def test_no_arrastra_archivos_que_ya_estaban_en_stage(self):
        self.p.reemplazar("docs/OPERACION.md", "sin medición", "pendiente de medición")
        git(self.p.repo, "add", "--", "docs/OPERACION.md")
        codigo, r = self.entregar("--rama-trabajo", "mgeller/x")
        self.assertEqual(codigo, 0, r)
        self.assertNotIn("docs/OPERACION.md", r["archivos_commit"])
        self.assertIn("docs/OPERACION.md", git(self.p.repo, "diff", "--cached", "--name-only"))

    def test_el_motor_no_usa_operaciones_git_prohibidas(self):
        fuente = SCRIPT.read_text(encoding="utf-8")
        for prohibido in ('"add", "."', '"add", "-A"', '"--force"', '"-f"', '"reset"', '"--hard"', '"rebase"',
                          '"push", "-f"', '"checkout", "--"', '"clean"'):
            self.assertNotIn(prohibido, fuente, prohibido)


# ----------------------------------------------------------------------------------------------
# Unidades del parser
# ----------------------------------------------------------------------------------------------

class Unidades(unittest.TestCase):
    def test_ddl_con_tipos_compuestos_y_comentarios(self):
        t = mgeller.extraer_ddl("CREATE OR REPLACE TABLE c.s.t (a DECIMAL(18,2) NOT NULL COMMENT 'Monto, en colones', "
                                "b ARRAY<STRUCT<x: INT, y: STRING>>, CONSTRAINT pk PRIMARY KEY (a))")
        self.assertEqual([c["nombre"] for c in t[0]["columnas"]], ["a", "b"])
        self.assertEqual(t[0]["columnas"][0]["tipo"], "DECIMAL(18,2)")
        self.assertEqual(t[0]["columnas"][0]["comentario"], "Monto, en colones")
        self.assertFalse(t[0]["columnas"][0]["nullable"])

    def test_diccionario_en_formato_mapa(self):
        d = mgeller.extraer_diccionarios({"tables": [{"table_name": "x", "columns": {"a": {"type": "int"}}}]}, "d.json")
        self.assertEqual(d[0]["tabla"], "x")
        self.assertEqual(d[0]["columnas"][0]["nombre"], "a")

    def test_normalizacion_de_tipos(self):
        self.assertEqual(mgeller.normalizar_tipo("INTEGER"), mgeller.normalizar_tipo("int"))
        self.assertEqual(mgeller.normalizar_tipo("decimal(18, 2)"), "decimal(18,2)")

    def test_sql_en_fstring_y_contexto_de_cadena(self):
        codigo = ('cat = "dv"\n'
                  'df = spark.sql(f"""SELECT a FROM {cat}.esq.origen o\n'
                  '   JOIN {cat}.esq.otra t ON o.id = t.id""")\n'
                  'spark.sql(f"INSERT INTO {cat}.esq.destino SELECT * FROM {cat}.esq.origen")\n'
                  'from pyspark.sql import functions as F  # no es una tabla\n')
        lee, escribe = mgeller.tablas_en_texto("", python=codigo)
        self.assertEqual({mgeller.clave_tabla(t) for t in lee}, {"origen", "otra"})
        self.assertEqual({mgeller.clave_tabla(t) for t in escribe}, {"destino"})
        rangos = mgeller.contexto_lineas_python(codigo)
        self.assertEqual(mgeller._contexto_en(rangos, 3, 10, "codigo"), "cadena")
        self.assertEqual(mgeller._contexto_en(rangos, 5, 45, "codigo"), "comentario")

    def test_ramas_protegidas(self):
        p = mgeller.RAMAS_PROTEGIDAS_DEFECTO
        self.assertTrue(mgeller.es_protegida("main", p, None))
        self.assertTrue(mgeller.es_protegida("release/1.0", p, None))
        self.assertTrue(mgeller.es_protegida("trunk", p, "trunk"))
        self.assertFalse(mgeller.es_protegida("feature/x", p, "main"))


class SinPyYAML(unittest.TestCase):
    """Simula un cómputo sin PyYAML: nada se da por válido y las rutas se siguen comprobando."""

    def setUp(self):
        self.p = ProductoTemporal()
        self.original = mgeller.HAY_YAML
        mgeller.HAY_YAML = False

    def tearDown(self):
        mgeller.HAY_YAML = self.original
        self.p.limpiar()

    def test_yaml_no_verificado_y_rutas_comprobadas(self):
        git(self.p.repo, "mv", "notebooks/dwh/Nb_Dim_Cliente.py", "notebooks/dwh/Nb_Dim_ClienteV2.py")
        hallazgos, pruebas = mgeller.validar_producto(self.p.repo, [], False, None)
        estados = {p["prueba"]: p["estado"] for p in pruebas}
        self.assertEqual(estados["Sintaxis YAML"], "no-ejecutada")
        self.assertEqual(estados["Referencias del bundle (estático)"], "parcial")
        self.assertIn("JOB-RUTA", {h.regla for h in hallazgos if h.severidad == "error"})


class LintDeLaSkill(unittest.TestCase):
    @unittest.skipUnless(mgeller.HAY_YAML, "el lint requiere PyYAML")
    def test_skill_cumple_la_especificacion(self):
        r = subprocess.run([sys.executable, str(RAIZ_REPO / "herramientas" / "lint_skill.py"), str(SKILL)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
