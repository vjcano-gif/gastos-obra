-- Trazabilidad de lo que entra desde su Excel historico.
--
-- Al cruzar la matriz con lo que ya trajo Gmail quedan dos grupos:
--   a) Filas que SI corresponden a una factura ya cargada: solo heredan
--      la clasificacion (proyecto, capitulo, actividad, corte). No se
--      crea nada.
--   b) Filas que NO tienen factura electronica y nunca la van a tener:
--      695 facturas de papel, 266 documentos equivalentes, 143 cuentas
--      de cobro, 81 de nomina. Son COSTO REAL del proyecto. Si no
--      entran, el costo por capitulo y el cash flow jamas van a cuadrar
--      con los numeros que ellos manejan hoy.
--
-- El grupo (b) entra como factura con fuente='matriz'. Se marca el origen
-- exacto (archivo + fila) por dos razones: se puede deshacer la
-- importacion completa, y volver a correrla no duplica nada.

alter table public.facturas drop constraint if exists facturas_fuente_check;
alter table public.facturas add constraint facturas_fuente_check
  check (fuente in ('xml', 'pdf', 'ocr', 'correo', 'manual', 'matriz'));

alter table public.facturas add column if not exists origen_matriz text;

comment on column public.facturas.origen_matriz is
  'Fila de origen en el Excel historico ("MATRIZ GASTOS!2360"). Permite '
  'reejecutar la importacion sin duplicar y revertirla por completo.';

-- La idempotencia se apoya en este indice: dos corridas de la importacion
-- sobre la misma fila chocan en vez de duplicar el movimiento.
create unique index if not exists facturas_origen_matriz_unico
  on public.facturas (user_id, origen_matriz) where origen_matriz is not null;

-- Mismo tratamiento para los abonos del cliente que vienen de la hoja
-- MATRIZ INGRESOS.
alter table public.anticipos add column if not exists origen_matriz text;
create unique index if not exists anticipos_origen_matriz_unico
  on public.anticipos (user_id, origen_matriz) where origen_matriz is not null;
