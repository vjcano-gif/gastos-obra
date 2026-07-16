-- Multiusuario sobre un mismo "workspace": todas las tablas ya guardan sus
-- filas bajo el user_id del PRIMER usuario (el dueno/owner). En vez de migrar
-- cada tabla a un esquema de tenant nuevo, agregamos una tabla de miembros y
-- una funcion que resuelve, para cualquier usuario logueado, a que owner_id
-- pertenece. El owner administra sus miembros desde la app (pagina Usuarios).

create table if not exists public.miembros (
  id uuid primary key default gen_random_uuid(),
  owner_user_id uuid not null references auth.users (id) on delete cascade,
  member_user_id uuid not null references auth.users (id) on delete cascade,
  email text not null,
  rol text not null default 'editor' check (rol in ('editor', 'lector')),
  created_at timestamptz not null default now(),
  unique (owner_user_id, member_user_id)
);

alter table public.miembros enable row level security;

-- El owner ve y administra su propia lista de miembros.
create policy owner_administra_miembros on public.miembros
  for all using (auth.uid() = owner_user_id) with check (auth.uid() = owner_user_id);

-- Un miembro invitado puede ver la fila que lo describe (para saber a que
-- workspace pertenece), pero no puede modificarla ni ver a otros miembros.
create policy miembro_ve_su_fila on public.miembros
  for select using (auth.uid() = member_user_id);

-- Resuelve el "workspace_id" del usuario logueado: si es owner de datos
-- propios, es el mismo; si fue invitado como miembro, es el owner_user_id
-- de su fila en miembros. security definer para poder leer miembros de
-- otros aunque el RLS de arriba restrinja el acceso directo por SELECT.
create or replace function public.mi_empresa()
returns uuid
language sql
security definer
set search_path = public
stable
as $$
  select coalesce(
    (select owner_user_id from public.miembros where member_user_id = auth.uid() limit 1),
    auth.uid()
  );
$$;

grant execute on function public.mi_empresa() to authenticated;

-- Reemplaza las politicas de las tablas de datos: en vez de auth.uid() = user_id,
-- ahora es mi_empresa() = user_id, para que el owner y sus miembros compartan
-- exactamente los mismos datos, sin duplicar filas ni columnas nuevas.
-- Los nombres de las politicas viejas se listan explicitos (no siguen un
-- patron uniforme con el nombre de tabla) para no fallar al borrarlas.
drop policy if exists propietario_proyectos on public.proyectos;
create policy compartido_proyectos on public.proyectos
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

drop policy if exists propietario_tipos_gasto on public.tipos_gasto;
create policy compartido_tipos_gasto on public.tipos_gasto
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

drop policy if exists propietario_facturas on public.facturas;
create policy compartido_facturas on public.facturas
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

drop policy if exists propietario_items on public.factura_items;
create policy compartido_items on public.factura_items
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

drop policy if exists propietario_pagos on public.pagos;
create policy compartido_pagos on public.pagos
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

drop policy if exists propietario_reglas on public.reglas_retencion;
create policy compartido_reglas on public.reglas_retencion
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

drop policy if exists propietario_documentos on public.documentos;
create policy compartido_documentos on public.documentos
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

drop policy if exists propietario_correos on public.correos_procesados;
create policy compartido_correos on public.correos_procesados
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

drop policy if exists propietario_envios on public.envios_estado_cuenta;
create policy compartido_envios on public.envios_estado_cuenta
  for all using (public.mi_empresa() = user_id) with check (public.mi_empresa() = user_id);

-- La migracion 001 dejo el bucket 'documentos' privado pero SIN politica de
-- storage.objects: nadie (ni el owner) podia leer ni subir archivos via el
-- cliente anon+JWT. Los documentos se guardan bajo la ruta "{owner_id}/...",
-- asi que la misma funcion mi_empresa() sirve para compartirlos con miembros.
drop policy if exists compartido_documentos_storage on storage.objects;
create policy compartido_documentos_storage on storage.objects
  for all
  using (bucket_id = 'documentos' and (storage.foldername(name))[1] = public.mi_empresa()::text)
  with check (bucket_id = 'documentos' and (storage.foldername(name))[1] = public.mi_empresa()::text);
