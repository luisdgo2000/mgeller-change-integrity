"""Funciones de normalización compartidas por los notebooks del producto."""
from pyspark.sql import functions as F


def normalizar_texto(columna):
    """Recorta espacios y pasa a mayúsculas."""
    return F.upper(F.trim(columna))
