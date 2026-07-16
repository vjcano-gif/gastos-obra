-- Esquema base: control de gastos e ingresos por proyecto de obra
-- Sin datos personales ni UUIDs quemados: el usuario se crea en Supabase Auth
-- y las semillas (tipos de gasto, reglas) las inserta la app en el primer inicio.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- proyectos
create table if not exists public.proyectos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  nombre text not null,
  codigo text not null,                      -- corto, para renombrar archivos: TORRE1
  cliente_nombre text,
  cliente_nit text,
  cliente_email text,
  presupuesto_total numeric(18,2),
  estado text not null default 'activo' check (estado in ('activo','cerrado')),
  created_at timestamptz not null default now(),
  unique (user_id, codigo)
);

-- ------------------------------------------------------------- tipos_gasto
create table if not exists public.tipos_gasto (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  nombre text not null,
  capitulo text,                             -- capítulo de obra: estructura, acabados...
  concepto_retencion text not null default 'compras'
    check (concepto_retencion in ('compras','servicios','honorarios','arriendos','ninguno')),
  activo boolean not null default true,
  unique (user_id, nombre)
);

-- ---------------------------------------------------------------- facturas
-- Una fila por documento: facturas, notas crédito/débito, cuentas de cobro,
-- consignaciones de clientes y registros manuales.
create table if not exists public.facturas (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  proyecto_id uuid references public.proyectos (id) on delete set null,
  tipo_gasto_id uuid references public.tipos_gasto (id) on delete set null,

  sentido text not null default 'gasto' check (sentido in ('gasto','ingreso')),
  tipo_documento text not null default 'factura' check (tipo_documento in
    ('factura','nota_credito','nota_debito','cuenta_cobro','consignacion','manual','otro')),

  cufe text,                                 -- código único DIAN (solo facturas electrónicas)
  numero text,                               -- número de factura visible (FE3456)
  proveedor_nombre text,
  proveedor_nit text,
  cliente_nit text,
  fecha_emision date,
  fecha_vencimiento date,
  plazo_dias integer,
  forma_pago text check (forma_pago in ('contado','credito')),

  valor_bruto numeric(18,2) default 0,
  descuentos numeric(18,2) default 0,
  iva numeric(18,2) default 0,
  impoconsumo numeric(18,2) default 0,
  excluidos numeric(18,2) default 0,
  cargos numeric(18,2) default 0,            -- fletes, propinas y otros cargos
  ajuste numeric(18,2) default 0,
  retenciones_xml numeric(18,2) default 0,   -- retenciones informadas en el XML
  total numeric(18,2) not null default 0,

  -- retenciones calculadas por el motor (congeladas; ver detalle en jsonb)
  rete_fuente numeric(18,2) default 0,
  rete_iva numeric(18,2) default 0,
  rete_ica numeric(18,2) default 0,
  detalle_retenciones jsonb,                 -- [{tipo, regla_id, tarifa, base, valor, vigencia}]

  descripcion text,                          -- consolidado de todos los ítems
  concepto text,
  metodo_pago text check (metodo_pago in ('TC','TD','contado','transferencia')),
  pagador text check (pagador in ('empresa','cliente')),
  estado text not null default 'extraida' check (estado in
    ('extraida','asignada','aprobada','pagada','anulada')),
  confianza text not null default 'alta' check (confianza in ('alta','baja')),
  fuente text not null default 'xml' check (fuente in ('xml','pdf','ocr','correo','manual')),

  gmail_message_id text,
  hash_adjunto text,                         -- huella del archivo para dedup
  posible_duplicado_de uuid references public.facturas (id) on delete set null,
  notas text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists facturas_cufe_unico
  on public.facturas (user_id, cufe) where cufe is not null;
create unique index if not exists facturas_hash_unico
  on public.facturas (user_id, hash_adjunto) where hash_adjunto is not null;
create index if not exists facturas_proyecto on public.facturas (proyecto_id);
create index if not exists facturas_fecha on public.facturas (user_id, fecha_emision);

-- ----------------------------------------------------------- factura_items
create table if not exists public.factura_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  factura_id uuid not null references public.facturas (id) on delete cascade,
  linea integer not null default 1,
  descripcion text,
  cantidad numeric(18,4) default 1,
  unidad text,
  precio_unitario numeric(18,2) default 0,
  descuento numeric(18,2) default 0,
  iva numeric(18,2) default 0,
  total numeric(18,2) default 0
);
create index if not exists items_factura on public.factura_items (factura_id);

-- ------------------------------------------------------------------- pagos
-- Abonos parciales y anticipos: una factura queda 'pagada' cuando la suma
-- de sus pagos cubre el total.
create table if not exists public.pagos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  factura_id uuid not null references public.facturas (id) on delete cascade,
  fecha date not null default current_date,
  monto numeric(18,2) not null,
  medio text,
  notas text,
  created_at timestamptz not null default now()
);
create index if not exists pagos_factura on public.pagos (factura_id);

-- ------------------------------------------------------- reglas_retencion
-- Reglas con vigencia: nunca se editan tarifas históricas; se cierra la
-- vigencia de la regla vieja y se crea una nueva desde la fecha del cambio.
create table if not exists public.reglas_retencion (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  tipo text not null check (tipo in ('retefuente','reteiva','reteica')),
  concepto text not null,                    -- compras, servicios, honorarios, arriendos
  tarifa numeric(8,4) not null,              -- porcentaje: 2.5 = 2.5%
  base_minima_uvt numeric(10,2) not null default 0,
  municipio text,                            -- solo reteica
  vigencia_desde date not null,
  vigencia_hasta date,                       -- null = vigente
  notas text,
  created_at timestamptz not null default now()
);

-- Valor de la UVT por año (editable en Configuración)
create table if not exists public.uvt (
  anio integer primary key,
  valor numeric(12,2) not null
);

-- -------------------------------------------------------------- documentos
create table if not exists public.documentos (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  factura_id uuid not null references public.facturas (id) on delete cascade,
  storage_path text not null,
  nombre_original text,
  nombre_renombrado text,                    -- AAAAMMDD-PROVEEDOR-NUM-FORMAPAGO-PROYECTO
  mime text,
  hash text,
  created_at timestamptz not null default now()
);

-- ------------------------------------------------------ correos_procesados
-- Capa de deduplicación por correo: un mensaje jamás se procesa dos veces.
create table if not exists public.correos_procesados (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  gmail_message_id text not null,
  procesado_en timestamptz not null default now(),
  resultado text,                            -- factura | ingreso | ignorado | error
  detalle text,
  unique (user_id, gmail_message_id)
);

-- -------------------------------------------------------- envios_estado
-- Historial de estados de cuenta enviados al cliente de cada proyecto.
create table if not exists public.envios_estado_cuenta (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users (id) on delete cascade,
  proyecto_id uuid not null references public.proyectos (id) on delete cascade,
  enviado_a text not null,
  asunto text,
  enviado_en timestamptz not null default now(),
  resumen jsonb
);

-- --------------------------------------------------------------------- RLS
alter table public.proyectos enable row level security;
alter table public.tipos_gasto enable row level security;
alter table public.facturas enable row level security;
alter table public.factura_items enable row level security;
alter table public.pagos enable row level security;
alter table public.reglas_retencion enable row level security;
alter table public.documentos enable row level security;
alter table public.correos_procesados enable row level security;
alter table public.envios_estado_cuenta enable row level security;

create policy propietario_proyectos on public.proyectos
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy propietario_tipos_gasto on public.tipos_gasto
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy propietario_facturas on public.facturas
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy propietario_items on public.factura_items
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy propietario_pagos on public.pagos
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy propietario_reglas on public.reglas_retencion
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy propietario_documentos on public.documentos
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy propietario_correos on public.correos_procesados
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy propietario_envios on public.envios_estado_cuenta
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- La tabla uvt es de solo lectura para usuarios autenticados;
-- se administra desde la app con service_role o por el propietario único.
alter table public.uvt enable row level security;
create policy uvt_lectura on public.uvt for select to authenticated using (true);

-- Bucket privado para documentos (crear también desde el panel si prefieres):
insert into storage.buckets (id, name, public)
  values ('documentos', 'documentos', false)
  on conflict (id) do nothing;
