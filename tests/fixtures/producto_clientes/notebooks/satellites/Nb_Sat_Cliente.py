# Databricks notebook source
# MAGIC %md
# MAGIC # Nb_Sat_Cliente
# MAGIC Carga el satélite `Sat_Cliente` con los atributos descriptivos del cliente.
# MAGIC
# MAGIC | Atributo | Valor |
# MAGIC |---|---|
# MAGIC | Destino | `{catalogo_dv}.clientes.sat_cliente` |
# MAGIC | Columnas de negocio | `NombreCliente`, `FechaNacimiento`, `CodigoSegmento` |
# MAGIC | Estrategia | append-only por `Hk_Diff` |

# COMMAND ----------

from pyspark.sql import functions as F
from utilidades.normalizacion import normalizar_texto

# COMMAND ----------

catalogoDv = dbutils.widgets.get("catalogo_dv")
TABLA_ORIGEN = f"{catalogoDv}.clientes.stg_cliente"
TABLA_DESTINO = f"{catalogoDv}.clientes.sat_cliente"

# COMMAND ----------

dfOrigen = spark.table(TABLA_ORIGEN)

# Se conserva FechaNacimiento tal como llega del core; la edad se calcula en la dimensión.
dfSat = (
    dfOrigen
    .withColumn("NombreCliente", normalizar_texto(F.col("nombre")))
    .withColumn("FechaNacimiento", F.to_date("fecha_nac", "yyyyMMdd"))
    .withColumn("CodigoSegmento", F.col("segmento"))
    .select("Hk_Cliente", "NombreCliente", "FechaNacimiento", "CodigoSegmento", "FechaRegistro")
)

# COMMAND ----------

dfSat.write.mode("append").saveAsTable(TABLA_DESTINO)
