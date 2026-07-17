-- Clasificacion de obra: capitulo (categoria de presupuesto: Estructura,
-- Acabados...), actividad (tarea especifica dentro de un capitulo) y
-- residente (persona responsable en obra). Catalogos editables por el
-- usuario, asignables a cada factura desde Revision.
--
-- Nota para el propio autor de esta migracion: 001 y 002 solo otorgaron
-- permisos a "authenticated" y 003/004 tuvieron que corregir por separado
-- el permiso de "service_role" que quedo faltando. Esta vez el GRANT para
-- ambos roles va en la MISMA migracion, para no repetir ese error.

create table if not exists public.capitulos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  nombre text not null,
  orden integer not null default 0,
  created_at timestamptz not null default now(),
  unique (user_id, nombre)
);

create table if not exists public.actividades (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  capitulo_id uuid references public.capitulos (id) on delete cascade,
  nombre text not null,
  created_at timestamptz not null default now(),
  unique (user_id, capitulo_id, nombre)
);

create table if not exists public.residentes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  nombre text not null,
  activo boolean not null default true,
  created_at timestamptz not null default now(),
  unique (user_id, nombre)
);

alter table public.facturas add column if not exists capitulo_id uuid references public.capitulos (id) on delete set null;
alter table public.facturas add column if not exists actividad_id uuid references public.actividades (id) on delete set null;
alter table public.facturas add column if not exists residente_id uuid references public.residentes (id) on delete set null;

alter table public.capitulos enable row level security;
alter table public.actividades enable row level security;
alter table public.residentes enable row level security;

create policy compartido_capitulos on public.capitulos
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);
create policy compartido_actividades on public.actividades
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);
create policy compartido_residentes on public.residentes
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

grant select, insert, update, delete on public.capitulos, public.actividades, public.residentes to authenticated;
grant all on public.capitulos, public.actividades, public.residentes to service_role;
