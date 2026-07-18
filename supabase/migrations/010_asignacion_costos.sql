-- Full costing: una factura (o un articulo individual) puede repartirse
-- entre varios proyectos. facturas.proyecto_id sigue siendo el caso simple
-- (proyecto unico); cuando existen filas aqui, el reparto MANDA sobre el
-- proyecto unico en los reportes.
create table if not exists public.asignacion_costos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  factura_id uuid not null references public.facturas (id) on delete cascade,
  factura_item_id uuid references public.factura_items (id) on delete cascade,
  proyecto_id uuid not null references public.proyectos (id) on delete cascade,
  porcentaje numeric(7, 4) check (porcentaje > 0 and porcentaje <= 100),
  monto numeric(18, 2) not null,
  metodo text not null default 'porcentaje'
    check (metodo in ('porcentaje', 'monto', 'area', 'presupuesto', 'manual')),
  base_asignacion text,           -- criterio usado (ej. "m2: A=120, B=80")
  creado_por uuid,
  created_at timestamptz not null default now()
);

create index if not exists asignacion_costos_factura on public.asignacion_costos (factura_id);
create index if not exists asignacion_costos_proyecto on public.asignacion_costos (proyecto_id);

alter table public.asignacion_costos enable row level security;

create policy asignacion_costos_lectura on public.asignacion_costos
  for select using (public.mi_empresa() = user_id);
create policy asignacion_costos_escritura on public.asignacion_costos
  for all
  using (public.mi_empresa() = user_id and public.puede_editar())
  with check (public.mi_empresa() = user_id and public.puede_editar());

grant select, insert, update, delete on public.asignacion_costos to authenticated;
grant all on public.asignacion_costos to service_role;
