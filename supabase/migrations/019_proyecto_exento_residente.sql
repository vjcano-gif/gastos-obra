-- Dos cosas que el usuario definio que son del PROYECTO, no de la factura:
--
--  1. Exento de AIU (#2). Antes era un check por factura; su modelo dice
--     que la exencion es del proyecto. Se agrega el flag al proyecto y la
--     factura lo hereda. El check por factura se conserva para el caso
--     raro (marcar una sola factura exenta en un proyecto que no lo es):
--     el calculo usa exento = factura.exento_aiu OR proyecto.exento_aiu.
--
--  2. Residente responsable (#1, metodo B). El residente de obra es quien
--     debe clasificar los gastos de SU proyecto (proyecto/capitulo/
--     actividad). No se vuelve usuario con login; se asigna un residente
--     por defecto al proyecto y las facturas lo heredan, con trazabilidad
--     de quien es el responsable. La clasificacion la sigue digitando el
--     administrativo, pero queda claro de quien es la obra.

alter table public.proyectos add column if not exists exento_aiu boolean not null default false;
alter table public.proyectos add column if not exists residente_id uuid
  references public.residentes (id) on delete set null;

comment on column public.proyectos.exento_aiu is
  'Proyecto exento de AIU: sus facturas no generan comision por defecto.';
comment on column public.proyectos.residente_id is
  'Residente responsable de clasificar los gastos de este proyecto.';
