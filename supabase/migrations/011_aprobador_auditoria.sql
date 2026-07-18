-- Rol "aprobador": aprobar o marcar pagada una factura deja de ser algo
-- que cualquier editor puede hacer. El dueno del workspace siempre puede.
alter table public.miembros drop constraint if exists miembros_rol_check;
alter table public.miembros add constraint miembros_rol_check
  check (rol in ('editor', 'lector', 'aprobador'));

create or replace function public.puede_aprobar()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  -- auth.uid() null = backend de confianza (worker con service_role o SQL
  -- directo): no se bloquea. Usuarios: dueno (sin fila en miembros) o
  -- miembro con rol aprobador.
  select auth.uid() is null
      or not exists (select 1 from public.miembros where member_user_id = auth.uid())
      or exists (
        select 1 from public.miembros
        where member_user_id = auth.uid() and rol = 'aprobador'
      );
$$;

grant execute on function public.puede_aprobar() to authenticated;

create or replace function public.tg_facturas_aprobacion()
returns trigger
language plpgsql
security definer
as $$
begin
  if new.estado in ('aprobada', 'pagada')
     and new.estado is distinct from old.estado
     and not public.puede_aprobar() then
    raise exception 'Solo un aprobador o el dueno puede aprobar o marcar pagada una factura';
  end if;
  return new;
end;
$$;

drop trigger if exists facturas_aprobacion on public.facturas;
create trigger facturas_aprobacion
  before update on public.facturas
  for each row execute function public.tg_facturas_aprobacion();

-- Auditoria de cambios HUMANOS (auth.uid() presente) sobre las tablas
-- criticas. Los barridos del worker no se auditan aqui: inundarian la
-- tabla y su historia ya queda en correos_procesados.
create table if not exists public.auditoria (
  id bigint generated always as identity primary key,
  user_id uuid not null,          -- workspace dueno de los datos
  actor uuid,                     -- quien hizo el cambio (auth.uid())
  tabla text not null,
  registro_id uuid,
  accion text not null,
  cambios jsonb,
  created_at timestamptz not null default now()
);

create index if not exists auditoria_registro on public.auditoria (tabla, registro_id);

alter table public.auditoria enable row level security;
create policy auditoria_lectura on public.auditoria
  for select using (public.mi_empresa() = user_id);
-- sin politica de escritura para authenticated: solo los triggers
-- (security definer) y service_role insertan.
grant select on public.auditoria to authenticated;
grant all on public.auditoria to service_role;

create or replace function public.tg_auditar()
returns trigger
language plpgsql
security definer
as $$
declare
  dif jsonb;
begin
  if auth.uid() is null then
    -- accion del worker o SQL directo: no auditar aqui
    if tg_op = 'DELETE' then return old; end if;
    return new;
  end if;

  if tg_op = 'UPDATE' then
    select jsonb_object_agg(n.key, jsonb_build_object('antes', o.value, 'despues', n.value))
      into dif
      from jsonb_each(to_jsonb(old)) o
      join jsonb_each(to_jsonb(new)) n using (key)
      where o.value is distinct from n.value;
    if dif is null or dif = '{}'::jsonb then
      return new;
    end if;
    insert into public.auditoria (user_id, actor, tabla, registro_id, accion, cambios)
    values (new.user_id, auth.uid(), tg_table_name, new.id, 'update', dif);
    return new;
  elsif tg_op = 'DELETE' then
    insert into public.auditoria (user_id, actor, tabla, registro_id, accion, cambios)
    values (old.user_id, auth.uid(), tg_table_name, old.id, 'delete', to_jsonb(old));
    return old;
  end if;
  return new;
end;
$$;

drop trigger if exists auditar_facturas on public.facturas;
create trigger auditar_facturas
  after update or delete on public.facturas
  for each row execute function public.tg_auditar();

drop trigger if exists auditar_pagos on public.pagos;
create trigger auditar_pagos
  after update or delete on public.pagos
  for each row execute function public.tg_auditar();
