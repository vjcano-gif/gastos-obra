-- La clasificacion (capitulo, actividad, tipo de gasto) debe poder variar
-- articulo por articulo dentro de una misma factura (ej: cemento va a
-- Estructura, pintura de la misma compra va a Acabados). Se agregan las
-- mismas tres columnas que ya tiene facturas, pero en factura_items. Las
-- columnas en facturas se dejan como estan: sirven de clasificacion
-- general de respaldo para facturas sin items (manuales, consignaciones).
alter table public.factura_items add column if not exists tipo_gasto_id uuid references public.tipos_gasto (id) on delete set null;
alter table public.factura_items add column if not exists capitulo_id uuid references public.capitulos (id) on delete set null;
alter table public.factura_items add column if not exists actividad_id uuid references public.actividades (id) on delete set null;
