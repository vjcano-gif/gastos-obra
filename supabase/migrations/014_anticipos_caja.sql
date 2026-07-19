-- Lo que falta para armar el Cash Flow del proyecto tal como lo llevan
-- hoy en Excel (hoja "Cash flow Casa Chipre").
--
-- Dos cosas que NO son facturas pero mueven la caja de la obra:
--   1. ANTICIPOS: los abonos del cliente. Ya existia `sentido='ingreso'`
--      en facturas, pero no alcanza: el cash flow los necesita partidos
--      por BANCOS vs EFECTIVO (son dos filas distintas en su hoja) y con
--      el numero de recibo de caja con el que los concilian ("RC 169").
--      Meter eso en `facturas` habria sido forzar una tabla de costos a
--      cargar campos de tesoreria que no le corresponden.
--   2. MOVIMIENTOS DE CAJA: el GMF 4x1000, "Otros Gastos" y los "pagos
--      exentos" del cash flow. No tienen factura ni proveedor: son
--      ajustes de caja, y sin ellos el saldo NUNCA cuadra con el de
--      ellos (en el corte 1 de Casa Vieja 61 son 20 millones).

-- -------------------------------------------------------------- anticipos
create table if not exists public.anticipos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  proyecto_id uuid not null references public.proyectos (id) on delete cascade,
  corte_id uuid references public.cortes (id) on delete set null,
  fecha date not null,
  valor numeric(18, 2) not null,
  modo_pago text not null default 'por_identificar',
  recibo text,                               -- "RC 169"
  detalle text,
  legalizacion text,                         -- encima / debajo
  created_at timestamptz not null default now(),
  check (modo_pago in ('bancos', 'efectivo', 'pago_directo', 'por_identificar')),
  check (legalizacion is null or legalizacion in ('encima', 'debajo'))
);
create index if not exists anticipos_proyecto on public.anticipos (proyecto_id, fecha);
create index if not exists anticipos_corte on public.anticipos (corte_id);

comment on table public.anticipos is
  'Abonos del cliente al proyecto. Alimentan el cash flow (hoja Cash Flow).';

-- ------------------------------------------------------- movimientos_caja
create table if not exists public.movimientos_caja (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  proyecto_id uuid not null references public.proyectos (id) on delete cascade,
  corte_id uuid references public.cortes (id) on delete set null,
  fecha date not null,
  concepto text not null default 'otros',
  descripcion text,
  -- Positivo = sale plata de la caja del proyecto. El GMF y los otros
  -- gastos son salidas; se deja el signo libre por si aparece un reintegro.
  valor numeric(18, 2) not null,
  exento_aiu boolean not null default true,  -- un impuesto no genera comision
  created_at timestamptz not null default now(),
  check (concepto in ('gmf', 'otros_gastos', 'pago_exento', 'ajuste'))
);
create index if not exists movimientos_caja_proyecto on public.movimientos_caja (proyecto_id, fecha);

comment on column public.movimientos_caja.concepto is
  'gmf = 4x1000; pago_exento = pagos que no entran a la base de AIU.';

-- ------------------------------------------------------------------- RLS
alter table public.anticipos enable row level security;
alter table public.movimientos_caja enable row level security;

create policy anticipos_lectura on public.anticipos
  for select using (public.mi_empresa() = user_id);
create policy anticipos_escritura on public.anticipos
  for all
  using (public.mi_empresa() = user_id and public.puede_editar())
  with check (public.mi_empresa() = user_id and public.puede_editar());

create policy movimientos_caja_lectura on public.movimientos_caja
  for select using (public.mi_empresa() = user_id);
create policy movimientos_caja_escritura on public.movimientos_caja
  for all
  using (public.mi_empresa() = user_id and public.puede_editar())
  with check (public.mi_empresa() = user_id and public.puede_editar());

grant select, insert, update, delete on public.anticipos, public.movimientos_caja to authenticated;
grant all on public.anticipos, public.movimientos_caja to service_role;
