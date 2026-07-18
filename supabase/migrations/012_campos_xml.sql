-- Campos del XML DIAN y del correo que el esquema no capturaba:
alter table public.facturas add column if not exists remitente_correo text;
alter table public.facturas add column if not exists cliente_nombre text;
alter table public.facturas add column if not exists rete_fuente_xml numeric(18,2) default 0;
alter table public.facturas add column if not exists rete_iva_xml numeric(18,2) default 0;
alter table public.facturas add column if not exists rete_ica_xml numeric(18,2) default 0;
alter table public.facturas add column if not exists flete numeric(18,2) default 0;
alter table public.facturas add column if not exists propina numeric(18,2) default 0;

alter table public.factura_items add column if not exists total_con_iva numeric(18,2);
