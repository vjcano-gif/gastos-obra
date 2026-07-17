-- Migracion 003 solo otorgo permisos al rol "authenticated" (la app).
-- El worker (GitHub Actions) usa la service_role key, que conecta como el
-- rol "service_role" de Postgres. Ese rol se salta RLS, pero TODAVIA
-- necesita el permiso base de tabla (GRANT), que "Automatically expose
-- new tables" tampoco le dio. Sin esto, el barrido de correos fallaba con
-- "permission denied for table reglas_retencion" (y habria fallado igual
-- en cualquier otra tabla que el worker tocara despues).
grant usage on schema public to service_role;

grant all on
  public.proyectos,
  public.tipos_gasto,
  public.facturas,
  public.factura_items,
  public.pagos,
  public.reglas_retencion,
  public.documentos,
  public.correos_procesados,
  public.envios_estado_cuenta,
  public.miembros,
  public.uvt
to service_role;
