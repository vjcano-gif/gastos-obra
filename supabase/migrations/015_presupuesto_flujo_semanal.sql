-- Presupuesto de obra y su programacion semanal (hoja "Flujo Semanal
-- Casa 61"). Es el plan contra el que se mide la ejecucion real.
--
-- Su hoja tiene tres niveles: CAPITULO > ACTIVIDAD > SUB ACTIVIDAD, y
-- para cada subactividad una cantidad (MT2/uds), un costo unitario y el
-- costo total. La subactividad NO se vuelve una dimension propia: en su
-- archivo es texto libre por proyecto ("Vaciado de Loza", "Bomba",
-- "Casetones"), no un catalogo compartido entre obras. Convertirla en
-- tabla obligaria a mantener un catalogo que nadie usa.
--
-- El presupuesto es POR PROYECTO: la misma actividad tiene cantidades y
-- precios distintos en cada obra.

create table if not exists public.presupuesto (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  proyecto_id uuid not null references public.proyectos (id) on delete cascade,
  capitulo_id uuid references public.capitulos (id) on delete set null,
  actividad_id uuid references public.actividades (id) on delete set null,
  subactividad text,
  unidad text,                               -- mt2, uds, gl
  cantidad numeric(18, 4),
  costo_unitario numeric(18, 2),
  -- Se guarda calculado y no se deriva al vuelo: ellos ajustan el total a
  -- mano en algunas filas (globales, sumas negociadas) y ese valor
  -- negociado es el que manda sobre cantidad x unitario.
  costo_total numeric(18, 2) not null default 0,
  orden integer not null default 0,
  created_at timestamptz not null default now()
);
create index if not exists presupuesto_proyecto on public.presupuesto (proyecto_id, orden);

-- ------------------------------------------------------ programacion semanal
-- Cuanto de esa linea de presupuesto se planea ejecutar en cada semana.
-- Una linea se reparte entre varias semanas (en su hoja, un vaciado de
-- cubierta de 66M queda en tres semanas de 22,2M).
create table if not exists public.presupuesto_semana (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  presupuesto_id uuid not null references public.presupuesto (id) on delete cascade,
  anio integer not null,
  semana integer not null check (semana between 1 and 53),
  valor numeric(18, 2) not null default 0,
  unique (presupuesto_id, anio, semana)
);
create index if not exists presupuesto_semana_periodo
  on public.presupuesto_semana (user_id, anio, semana);

comment on table public.presupuesto_semana is
  'Plan semanal por linea de presupuesto; se compara contra el gasto real.';

-- ------------------------------------------------------------------- RLS
alter table public.presupuesto enable row level security;
alter table public.presupuesto_semana enable row level security;

create policy presupuesto_lectura on public.presupuesto
  for select using (public.mi_empresa() = user_id);
create policy presupuesto_escritura on public.presupuesto
  for all
  using (public.mi_empresa() = user_id and public.puede_editar())
  with check (public.mi_empresa() = user_id and public.puede_editar());

create policy presupuesto_semana_lectura on public.presupuesto_semana
  for select using (public.mi_empresa() = user_id);
create policy presupuesto_semana_escritura on public.presupuesto_semana
  for all
  using (public.mi_empresa() = user_id and public.puede_editar())
  with check (public.mi_empresa() = user_id and public.puede_editar());

grant select, insert, update, delete on public.presupuesto, public.presupuesto_semana to authenticated;
grant all on public.presupuesto, public.presupuesto_semana to service_role;
