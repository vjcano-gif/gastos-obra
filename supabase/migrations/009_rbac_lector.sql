-- Hallazgo de auditoria: el rol "lector" de miembros era cosmetico. Las
-- politicas compartido_* eran "for all" para cualquier miembro del
-- workspace, asi que un lector podia editar o borrar datos via la API
-- (aunque la interfaz no se lo mostrara). Se separa lectura de escritura.
--
-- puede_editar(): true para el dueno del workspace y para miembros con
-- rol 'editor'; false para miembros con rol 'lector'.
create or replace function public.puede_editar()
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select auth.uid() is not null and (
    not exists (select 1 from public.miembros where member_user_id = auth.uid())
    or exists (
      select 1 from public.miembros
      where member_user_id = auth.uid() and rol = 'editor'
    )
  );
$$;

grant execute on function public.puede_editar() to authenticated;

-- Por cada tabla de datos: una politica de solo-select para todo el
-- workspace, y una de escritura que ademas exige puede_editar(). Las
-- politicas son permisivas (OR entre ellas), asi que el select pasa por
-- la de lectura aunque la de escritura tambien aplique al select.
do $$
declare
  t text;
begin
  foreach t in array array[
    'proyectos', 'tipos_gasto', 'facturas', 'factura_items', 'pagos',
    'reglas_retencion', 'documentos', 'correos_procesados',
    'envios_estado_cuenta', 'capitulos', 'actividades', 'residentes',
    'hitos_proyecto'
  ]
  loop
    execute format('drop policy if exists compartido_%I on public.%I', t, t);
    -- nombres viejos de 002/005/006 que no siguen el patron compartido_<tabla>
    execute format('drop policy if exists compartido_items on public.%I', t);
    execute format('drop policy if exists compartido_correos on public.%I', t);
    execute format('drop policy if exists compartido_envios on public.%I', t);
    execute format('drop policy if exists compartido_reglas on public.%I', t);
    execute format('drop policy if exists compartido_hitos_proyecto on public.%I', t);
    execute format(
      'create policy %I_lectura on public.%I for select using (public.mi_empresa() = user_id)', t, t
    );
    execute format(
      'create policy %I_escritura on public.%I for all
         using (public.mi_empresa() = user_id and public.puede_editar())
         with check (public.mi_empresa() = user_id and public.puede_editar())',
      t, t
    );
  end loop;
end $$;

-- Mismo tratamiento para los archivos en Storage: el lector puede VER
-- documentos (firmar URLs) pero no subir, reemplazar ni borrar.
drop policy if exists compartido_documentos_storage on storage.objects;
create policy documentos_storage_lectura on storage.objects
  for select
  using (bucket_id = 'documentos' and (storage.foldername(name))[1] = public.mi_empresa()::text);
create policy documentos_storage_escritura on storage.objects
  for all
  using (
    bucket_id = 'documentos'
    and (storage.foldername(name))[1] = public.mi_empresa()::text
    and public.puede_editar()
  )
  with check (
    bucket_id = 'documentos'
    and (storage.foldername(name))[1] = public.mi_empresa()::text
    and public.puede_editar()
  );
