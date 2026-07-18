-- Parametrizacion de proyecto: fechas de inicio/fin del contrato, y un
-- cronograma de hitos (abonos del cliente y entregables) con su propia
-- fecha programada y, para abonos, el monto esperado.
alter table public.proyectos add column if not exists fecha_inicio date;
alter table public.proyectos add column if not exists fecha_fin date;

create table if not exists public.hitos_proyecto (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  proyecto_id uuid not null references public.proyectos (id) on delete cascade,
  tipo text not null check (tipo in ('abono', 'entregable')),
  descripcion text not null,
  fecha date not null,
  monto numeric(14, 2),
  cumplido boolean not null default false,
  created_at timestamptz not null default now()
);

alter table public.hitos_proyecto enable row level security;

create policy compartido_hitos_proyecto on public.hitos_proyecto
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

grant select, insert, update, delete on public.hitos_proyecto to authenticated;
grant all on public.hitos_proyecto to service_role;
