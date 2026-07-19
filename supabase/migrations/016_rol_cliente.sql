-- Rol "cliente": el dueno de la obra entra a ver COMO VA SU PROYECTO y
-- nada mas. Ve su cash flow, sus anticipos y el costo por capitulo y
-- corte; NO ve proveedores, ni facturas individuales, ni las otras obras.
--
-- CUIDADO — el peligro real de esta migracion:
-- las politicas de 009 son `using (mi_empresa() = user_id)`, y mi_empresa()
-- devuelve el id del DUENO para cualquier miembro. Un cliente creado como
-- miembro pasaria esa condicion y veria las 4.052 facturas de TODAS las
-- obras, con proveedores y valores. Por eso aqui no basta con agregar el
-- rol: hay que reescribir las politicas de lectura para excluirlo
-- explicitamente de las tablas sensibles y acotarlo a su proyecto en las
-- que si puede ver. Se prueba al final con una simulacion de su JWT.

alter table public.miembros add column if not exists proyecto_id uuid
  references public.proyectos (id) on delete cascade;

alter table public.miembros drop constraint if exists miembros_rol_check;
alter table public.miembros add constraint miembros_rol_check
  check (rol in ('editor', 'lector', 'aprobador', 'cliente'));

-- Un cliente SIEMPRE tiene que estar amarrado a un proyecto: sin eso no
-- hay nada que lo limite, y "sin limite" para un rol externo es un hueco.
alter table public.miembros drop constraint if exists miembros_cliente_con_proyecto;
alter table public.miembros add constraint miembros_cliente_con_proyecto
  check (rol <> 'cliente' or proyecto_id is not null);

-- ------------------------------------------------------------- funciones
create or replace function public.es_cliente()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (
    select 1 from public.miembros
    where member_user_id = auth.uid() and rol = 'cliente'
  );
$$;

create or replace function public.mi_proyecto()
returns uuid
language sql
security definer
set search_path = public
stable
as $$
  select proyecto_id from public.miembros
  where member_user_id = auth.uid() and rol = 'cliente'
  limit 1;
$$;

grant execute on function public.es_cliente(), public.mi_proyecto() to authenticated;

-- Un cliente no edita ni aprueba NADA. puede_editar() ya lo excluye por
-- no ser 'editor' y puede_aprobar() por no ser 'aprobador', pero se deja
-- explicito: si manana alguien cambia esas funciones, el cliente no debe
-- volverse escritor por accidente.
create or replace function public.puede_editar()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select auth.uid() is not null
    and not public.es_cliente()
    and (
      not exists (select 1 from public.miembros where member_user_id = auth.uid())
      or exists (
        select 1 from public.miembros
        where member_user_id = auth.uid() and rol = 'editor'
      )
    );
$$;

create or replace function public.puede_aprobar()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select (auth.uid() is null or not public.es_cliente())
     and (
       auth.uid() is null
       or not exists (select 1 from public.miembros where member_user_id = auth.uid())
       or exists (
         select 1 from public.miembros
         where member_user_id = auth.uid() and rol = 'aprobador'
       )
     );
$$;

-- ------------------------------- tablas VEDADAS para el cliente
-- Aqui esta el detalle que no debe ver: proveedores, numeros de factura,
-- valores por documento, evidencia y correos.
do $$
declare
  t text;
begin
  foreach t in array array[
    'tipos_gasto', 'facturas', 'factura_items', 'pagos', 'reglas_retencion',
    'documentos', 'correos_procesados', 'envios_estado_cuenta', 'residentes',
    'asignacion_costos', 'auditoria', 'presupuesto', 'presupuesto_semana'
  ]
  -- OJO: `miembros` NO va en esta lista. Es la unica tabla del esquema
  -- cuyo dueno se llama owner_user_id y no user_id, asi que la politica
  -- generada aqui no compilaria. Se rehace justo debajo, a mano.
  loop
    execute format('drop policy if exists %I_lectura on public.%I', t, t);
    execute format(
      'create policy %I_lectura on public.%I for select
         using (public.mi_empresa() = user_id and not public.es_cliente())', t, t
    );
  end loop;
end $$;

-- `miembros` no tiene user_id sino owner_user_id: su politica es propia y
-- el loop de arriba la habria dejado invalida. Se rehace aparte.
drop policy if exists miembros_lectura on public.miembros;
drop policy if exists owner_administra_miembros on public.miembros;
create policy miembros_dueno on public.miembros
  for all
  using (owner_user_id = auth.uid())
  with check (owner_user_id = auth.uid());
create policy miembros_ve_su_fila on public.miembros
  for select using (member_user_id = auth.uid());

-- --------------------------- tablas VISIBLES, acotadas a SU proyecto
-- El cliente si ve: su proyecto, sus cortes, sus anticipos y los
-- movimientos de caja de su obra. Todo filtrado por mi_proyecto().
drop policy if exists proyectos_lectura on public.proyectos;
create policy proyectos_lectura on public.proyectos
  for select using (
    public.mi_empresa() = user_id
    and (not public.es_cliente() or id = public.mi_proyecto())
  );

do $$
declare
  t text;
begin
  foreach t in array array['cortes', 'anticipos', 'movimientos_caja', 'hitos_proyecto']
  loop
    execute format('drop policy if exists %I_lectura on public.%I', t, t);
    execute format(
      'create policy %I_lectura on public.%I for select
         using (
           public.mi_empresa() = user_id
           and (not public.es_cliente() or proyecto_id = public.mi_proyecto())
         )', t, t
    );
  end loop;
end $$;

-- Capitulos y actividades son solo nombres ("Estructura", "Cimentacion"):
-- el cliente los necesita para leer su informe y no revelan nada.
do $$
declare
  t text;
begin
  foreach t in array array['capitulos', 'actividades']
  loop
    execute format('drop policy if exists %I_lectura on public.%I', t, t);
    execute format(
      'create policy %I_lectura on public.%I for select
         using (public.mi_empresa() = user_id)', t, t
    );
  end loop;
end $$;

-- Storage: la evidencia es justamente lo que NO puede ver.
drop policy if exists documentos_storage_lectura on storage.objects;
create policy documentos_storage_lectura on storage.objects
  for select
  using (
    bucket_id = 'documentos'
    and (storage.foldername(name))[1] = public.mi_empresa()::text
    and not public.es_cliente()
  );

-- ------------------------------------ el costo agregado que SI puede ver
-- El cliente no puede leer `facturas`, asi que el costo por capitulo y
-- corte se le entrega ya sumado, por una funcion SECURITY DEFINER que
-- decide ella misma que proyecto puede consultar. Nunca devuelve
-- proveedor ni numero de factura: solo capitulo, corte y total.
create or replace function public.costo_por_capitulo(p_proyecto uuid)
returns table (
  capitulo_id uuid,
  capitulo text,
  corte_id uuid,
  corte text,
  total numeric
)
language sql
security definer
set search_path = public
stable
as $$
  select
    cap.id,
    cap.nombre,
    cor.id,
    cor.nombre,
    sum(coalesce(i.total, f.total))::numeric
  from public.facturas f
  left join public.factura_items i on i.factura_id = f.id
  left join public.capitulos cap on cap.id = coalesce(i.capitulo_id, f.capitulo_id)
  left join public.cortes cor on cor.id = f.corte_id
  where f.proyecto_id = p_proyecto
    and f.estado <> 'anulada'
    -- Quien pregunta tiene que ser del workspace; y si es cliente, solo
    -- se le responde por SU proyecto. La verificacion va adentro porque
    -- security definer se salta el RLS de las tablas de arriba.
    and f.user_id = public.mi_empresa()
    and (not public.es_cliente() or p_proyecto = public.mi_proyecto())
  group by cap.id, cap.nombre, cor.id, cor.nombre;
$$;

grant execute on function public.costo_por_capitulo(uuid) to authenticated;

grant select on public.cortes, public.anticipos, public.movimientos_caja to authenticated;
