-- El XML DIAN trae mas datos de los que se estaban aprovechando:
-- descuento e iva POR ARTICULO ya existian en el esquema (factura_items)
-- pero el parser nunca los llenaba. Se agregan ademas columnas nuevas
-- para tarifa de IVA y codigo del articulo (por linea), y orden de
-- compra / moneda a nivel de factura.
alter table public.facturas add column if not exists orden_compra text;
alter table public.facturas add column if not exists moneda text default 'COP';

alter table public.factura_items add column if not exists codigo_articulo text;
alter table public.factura_items add column if not exists tarifa_iva numeric(6, 2);
