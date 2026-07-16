-- Al crear el proyecto se desactivo "Automatically expose new tables", lo
-- que impidio que Postgres le diera permisos basicos de tabla al rol
-- "authenticated" (RLS restringe FILAS, pero antes de eso el rol necesita
-- permiso sobre la TABLA misma). Sin este GRANT, cualquier consulta desde
-- la app (que usa authenticated) fallaba con "permission denied", sin
-- importar que las politicas de RLS estuvieran bien escritas.
grant usage on schema public to authenticated;

grant select, insert, update, delete on
  public.proyectos,
  public.tipos_gasto,
  public.facturas,
  public.factura_items,
  public.pagos,
  public.reglas_retencion,
  public.documentos,
  public.correos_procesados,
  public.envios_estado_cuenta,
  public.miembros
to authenticated;

grant select on public.uvt to authenticated;

-- Las tablas usan gen_random_uuid() como default de "id", pero no necesitan
-- secuencias; nada mas que otorgar aqui. Si en el futuro se agregan tablas
-- nuevas, recuerda que necesitan su propio GRANT (o reactivar "Automatically
-- expose new tables" en Database Settings, con RLS ya activo por tabla).
