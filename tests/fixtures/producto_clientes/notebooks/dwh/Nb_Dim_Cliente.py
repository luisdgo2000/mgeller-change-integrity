# Databricks notebook source
# MAGIC %md
# MAGIC # Nb_Dim_Cliente
# MAGIC Construye `Dim_Cliente` a partir de `Sat_Cliente`. Calcula `EdadCliente` desde `FechaNacimiento`.

# COMMAND ----------

from pyspark.sql import functions as F

# COMMAND ----------

catalogoDv = dbutils.widgets.get("catalogo_dv")
catalogoDwh = dbutils.widgets.get("catalogo_dwh")
TABLA_SAT = f"{catalogoDv}.clientes.sat_cliente"
TABLA_DIM = f"{catalogoDwh}.clientes.dim_cliente"

# COMMAND ----------

def calcular_edad(columnaFecha):
    """Edad en años cumplidos a partir de FechaNacimiento."""
    return F.floor(F.months_between(F.current_date(), F.col(columnaFecha)) / 12)

dfDim = (
    spark.table(TABLA_SAT)
    .withColumn("EdadCliente", calcular_edad("FechaNacimiento"))
    .select("Hk_Cliente", "NombreCliente", "EdadCliente", "CodigoSegmento")
)

# COMMAND ----------

dfDim.write.mode("overwrite").saveAsTable(TABLA_DIM)
