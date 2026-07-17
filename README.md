# Gastos de obra — control de costos por proyecto

Sistema para constructoras: lee el buzón de facturación electrónica (XML DIAN),
extrae facturas y consignaciones, deduplica, calcula retenciones con vigencias,
guarda la evidencia y muestra gastos vs ingresos por proyecto. Un dueño por
workspace, que puede invitar a su equipo a compartir los mismos datos.

## Arquitectura

- **app/** — Streamlit (Streamlit Cloud): Revisión, Dashboard, Cuentas por pagar,
  Estado de cuenta, Configuración, Usuarios.
- **worker/** — barrido del buzón cada 6 horas (GitHub Actions).
- **supabase/** — migraciones SQL (Postgres + Storage privado, RLS por workspace).

## Montaje (una sola vez por cliente)

1. **Supabase**: crear proyecto nuevo. **Si al crearlo dejas activado
   "Automatically expose new tables", puedes saltarte el paso 003** (ese
   toggle es justamente el que aplica los GRANT automáticamente). Si lo
   desactivaste (o no estás seguro), corre las tres migraciones en orden en
   el SQL Editor: `001_esquema.sql` → Run, `002_miembros.sql` → Run (agrega
   el soporte multiusuario y corrige los permisos del bucket de documentos),
   `003_grants.sql` → Run (le da permiso de tabla al rol `authenticated`;
   sin esto toda la app falla con "permission denied" aunque las políticas
   de RLS estén perfectas).
   En Authentication → Users → crear el usuario dueño (correo + contraseña).
   Copiar: URL del proyecto, `anon key`, `service_role key` y el UUID del usuario.
2. **Google Cloud**: reutilizar el proyecto OAuth existente; agregar el correo del
   buzón como *test user* y generar el refresh token (scope `gmail.readonly`).
   Si el buzón del cliente no es Google, configurar reenvío automático a un Gmail
   espejo dedicado.
3. **GitHub**: crear repo privado con este contenido. En Settings → Secrets →
   Actions crear: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `APP_USER_ID`,
   `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`,
   `OPENAI_API_KEY` (opcional), `PDF_PASSWORDS` (opcional, separadas por coma).
4. **Streamlit Cloud**: nueva app → este repo → archivo `app/Home.py`.
   En Secrets pegar:
   ```toml
   SUPABASE_URL = "https://xxxx.supabase.co"
   SUPABASE_ANON_KEY = "..."
   SUPABASE_SERVICE_ROLE_KEY = "..."   # necesaria para que el dueño invite usuarios
   RESEND_API_KEY = ""   # para enviar estados de cuenta (opcional, necesita dominio verificado)
   EMAIL_FROM = ""       # remitente verificado en Resend (opcional)
   ADMIN_CONTACTO = "Victor - WhatsApp 3xx xxx xxxx"   # se muestra en "olvidé mi contraseña"
   ```
5. **Barrido inicial**: GitHub → Actions → "Sincronizar buzón" → Run workflow →
   `backfill_desde = 2026-01-01` (o la fecha que se acuerde).
6. Entrar a la app, crear los **proyectos** en Configuración y validar en
   Configuración → Reglas de retención las tarifas con el contador del cliente.
   Registrar el valor de la **UVT** del año en curso.
7. **Usuarios del equipo**: el correo incluido de Supabase tiene un límite muy
   bajo (~2/hora, igual en el plan gratis y en Pro — no se arregla pagando,
   solo conectando un SMTP propio como Resend). Mientras no haya un dominio
   verificado, el dueño crea cada usuario manualmente en Supabase →
   Authentication → Users → Add user → **Create new user** (correo +
   contraseña que él mismo define y le entrega a la persona, con "Auto
   confirm user" activado — no se envía ningún correo). Después, en la
   página **Usuarios** de la app, el dueño lo vincula a su mismo workspace.
   Si alguien olvida su contraseña, se la restablece el dueño desde ese
   mismo panel de Supabase.

## Reglas de negocio clave

- Deduplicación por capas: CUFE → id del correo → hash del adjunto → heurística
  de consignaciones (posible duplicado queda para decisión humana).
- Las notas crédito restan del costo del proyecto.
- Las reglas de retención nunca se editan: se cierra la vigencia y se crea una
  nueva. El valor calculado queda congelado en cada factura con su detalle.
- Todo lo extraído sin XML (PDF, OCR, correo) entra con confianza baja y pasa
  por revisión antes de contar en informes definitivos.
