-- DDL del satélite de cliente
CREATE TABLE IF NOT EXISTS ${catalogo_dv}.clientes.sat_cliente (
  Hk_Cliente BINARY NOT NULL COMMENT 'Hash key del cliente',
  NombreCliente STRING COMMENT 'Nombre normalizado del cliente',
  FechaNacimiento DATE COMMENT 'Fecha de nacimiento del cliente',
  CodigoSegmento STRING COMMENT 'Código del segmento comercial',
  FechaRegistro TIMESTAMP NOT NULL COMMENT 'Fecha de registro en Data Vault'
)
CLUSTER BY (Hk_Cliente);
