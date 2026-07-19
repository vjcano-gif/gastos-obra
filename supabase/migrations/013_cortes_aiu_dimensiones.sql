-- Modelo real de la constructora, tomado del archivo que llevan hoy
-- ("MATRIZ Movimientos Contables" y "Cash Flow Casa Vieja 61").
--
-- Tres cosas que faltaban y que son el eje de su operacion:
--   1. CORTE: periodo de ejecucion de la obra (normalmente mensual, pero
--      con fechas propias por proyecto). Toda su informacion gerencial
--      esta cortada asi: capitulo x corte, cash flow por corte.
--   2. AIU / comision: el %AIU vive en el PROYECTO y de ahi sale lo que
--      Espacios gana. Formulas verificadas contra sus cifras reales:
--        Casa Vieja 61  1.684.702 x 14%  =   235.858  (AIU gastos)
--        Casa Vieja 61    530.000 x 14%  =    74.200  (AIU pagos directos)
--        Arrayanes 40  42.842.500 x 11%  = 4.712.675  (Total Comision)
--      Gastos y pagos directos se calculan por SEPARADO porque el pago
--      directo del cliente no pasa por la caja de Espacios.
--   3. Pagador heredado del proyecto: espacios / cliente / mixto. Solo
--      cuando es mixto hay que digitarlo factura por factura; en los
--      otros dos casos se hereda y el usuario no digita nada.
--
-- NO se crean dimensiones nuevas de capitulo/actividad: ya existen desde
-- 005 y aqui solo se les agrega el codigo con el que ellos las nombran
-- ("0,01", "1,02"), que es como aparecen en todos sus reportes.

-- ------------------------------------------------------------- proyectos
alter table public.proyectos add column if not exists pct_aiu numeric(7, 4) not null default 0;
alter table public.proyectos add column if not exists pagador_modo text not null default 'espacios';

do $$ begin
  alter table public.proyectos add constraint proyectos_pagador_modo_valido
    check (pagador_modo in ('espacios', 'cliente', 'mixto'));
exception when duplicate_object then null; end $$;

comment on column public.proyectos.pct_aiu is
  'AIU del contrato (0.14 = 14%). Base de la comision de Espacios.';
comment on column public.proyectos.pagador_modo is
  'Quien paga las facturas. Si es mixto se digita por factura; si no, se hereda.';

-- ----------------------------------------------------------------- cortes
-- Periodo de ejecucion. Las fechas permiten asignar el corte solo, a
-- partir de la fecha de emision, en vez de que alguien lo digite.
create table if not exists public.cortes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  proyecto_id uuid not null references public.proyectos (id) on delete cascade,
  numero integer not null,
  nombre text not null,                      -- "Corte 1"
  fecha_inicio date,
  fecha_fin date,
  descripcion text,                          -- "De 29 de mayo al 23 de octubre"
  cerrado boolean not null default false,
  created_at timestamptz not null default now(),
  unique (user_id, proyecto_id, numero),
  check (fecha_fin is null or fecha_inicio is null or fecha_fin >= fecha_inicio)
);
create index if not exists cortes_proyecto on public.cortes (proyecto_id, numero);

-- ---------------------------------------------------------------- facturas
alter table public.facturas add column if not exists corte_id uuid references public.cortes (id) on delete set null;
alter table public.facturas add column if not exists exento_aiu boolean not null default false;
alter table public.facturas add column if not exists legalizacion text;
alter table public.facturas add column if not exists comision_aiu numeric(18, 2) not null default 0;
alter table public.facturas add column if not exists estado_pago text not null default 'pendiente';

do $$ begin
  alter table public.facturas add constraint facturas_legalizacion_valida
    check (legalizacion is null or legalizacion in ('encima', 'debajo'));
exception when duplicate_object then null; end $$;

-- estado_pago es un eje DISTINTO de estado. `estado` es el flujo interno
-- (extraida -> asignada -> aprobada); `estado_pago` es la realidad de
-- tesoreria, que es lo que responde "a quien le debo y cuanto". Mezclarlos
-- en una sola columna era lo que hacia que no se pudiera contestar ninguna
-- de las dos preguntas bien.
do $$ begin
  alter table public.facturas add constraint facturas_estado_pago_valido
    check (estado_pago in
      ('pendiente', 'parcial', 'pagada', 'pendiente_reporte', 'anulada'));
exception when duplicate_object then null; end $$;

create index if not exists facturas_corte on public.facturas (corte_id);
create index if not exists facturas_estado_pago on public.facturas (user_id, estado_pago);

comment on column public.facturas.exento_aiu is
  'Se excluye de la base de comision (ellos lo marcan "Exento AIU").';
comment on column public.facturas.legalizacion is
  'Encima/Debajo: si el movimiento va por encima o por debajo de la legalizacion.';

-- --------------------------------------------------- vocabularios ampliados
-- forma_pago: ademas de contado/credito, ellos usan abonos y la
-- legalizacion de anticipos, que son movimientos distintos.
alter table public.facturas drop constraint if exists facturas_forma_pago_check;
alter table public.facturas add constraint facturas_forma_pago_check
  check (forma_pago is null or forma_pago in
    ('contado', 'credito', 'abono', 'legalizacion_anticipo', 'anulada'));

-- metodo_pago: el vocabulario viejo (TC/TD/contado) era el de los codigos
-- DIAN y no cubre lo que ellos manejan (cheque, cuentas por pagar, pago
-- directo del cliente). Se traduce el dato existente en vez de ampliar la
-- lista con dos vocabularios mezclados. La equivalencia es la de la DIAN:
-- codigo 10 = Efectivo, 48 = Tarjeta Credito, 49 = Tarjeta Debito.
alter table public.facturas drop constraint if exists facturas_metodo_pago_check;

update public.facturas set metodo_pago = case metodo_pago
  when 'TC'      then 'tarjeta_credito'
  when 'TD'      then 'tarjeta_debito'
  when 'contado' then 'efectivo'
  else metodo_pago
end
where metodo_pago in ('TC', 'TD', 'contado');

alter table public.facturas add constraint facturas_metodo_pago_check
  check (metodo_pago is null or metodo_pago in
    ('efectivo', 'transferencia', 'cheque', 'tarjeta_credito',
     'tarjeta_credito_vr', 'tarjeta_debito', 'cuentas_x_pagar',
     'pago_directo_cliente', 'anulada'));

-- pagador: se agrega el valor 'mixto' para el caso en que una misma
-- factura se reparte, y se conservan empresa/cliente que ya se usaban.
alter table public.facturas drop constraint if exists facturas_pagador_check;
alter table public.facturas add constraint facturas_pagador_check
  check (pagador is null or pagador in ('empresa', 'cliente', 'mixto'));

-- ------------------------------------------- codigos en las dimensiones
-- Sus capitulos y actividades tienen numeracion propia ("0,01 Planos",
-- "1,02 Marcacion") y asi los leen todos. Se agrega el codigo a las
-- tablas que YA existen desde 005: no se crean dimensiones nuevas.
alter table public.capitulos add column if not exists codigo text;
alter table public.actividades add column if not exists codigo text;

create unique index if not exists capitulos_codigo_unico
  on public.capitulos (user_id, codigo) where codigo is not null;
create unique index if not exists actividades_codigo_unico
  on public.actividades (user_id, codigo) where codigo is not null;

-- ------------------------------------------------------------------- RLS
alter table public.cortes enable row level security;

create policy cortes_lectura on public.cortes
  for select using (public.mi_empresa() = user_id);
create policy cortes_escritura on public.cortes
  for all
  using (public.mi_empresa() = user_id and public.puede_editar())
  with check (public.mi_empresa() = user_id and public.puede_editar());

grant select, insert, update, delete on public.cortes to authenticated;
grant all on public.cortes to service_role;

-- ------------------------------------------------ corte segun la fecha
-- Devuelve el corte al que corresponde una fecha dentro de un proyecto.
-- Es lo que evita que alguien tenga que digitar el corte en cada factura.
create or replace function public.corte_de_fecha(p_proyecto uuid, p_fecha date)
returns uuid
language sql
stable
as $$
  select id from public.cortes
  where proyecto_id = p_proyecto
    and p_fecha is not null
    and fecha_inicio is not null
    and p_fecha >= fecha_inicio
    and (fecha_fin is null or p_fecha <= fecha_fin)
  order by numero
  limit 1;
$$;
