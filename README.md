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

1. **Supabase**: crear proyecto nuevo → SQL Editor → pegar
   `supabase/migrations/001_esquema.sql` → Run, y luego
   `supabase/migrations/002_miembros.sql` → Run (agrega el soporte multiusuario
   y corrige los permisos del bucket de documentos).
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
   RESEND_API_KEY = ""   # para enviar estados de cuenta (opcional)
   EMAIL_FROM = ""       # remitente verificado en Resend (opcional)
   ```
5. **Barrido inicial**: GitHub → Actions → "Sincronizar buzón" → Run workflow →
   `backfill_desde = 2026-01-01` (o la fecha que se acuerde).
6. Entrar a la app, crear los **proyectos** en Configuración y validar en
   Configuración → Reglas de retención las tarifas con el contador del cliente.
   Registrar el valor de la **UVT** del año en curso.
7. Desde **Usuarios**, el dueño invita al resto del equipo por correo; cada
   invitado define su propia contraseña y ve los mismos datos.

## Reglas de negocio clave

- Deduplicación por capas: CUFE → id del correo → hash del adjunto → heurística
  de consignaciones (posible duplicado queda para decisión humana).
- Las notas crédito restan del costo del proyecto.
- Las reglas de retención nunca se editan: se cierra la vigencia y se crea una
  nueva. El valor calculado queda congelado en cada factura con su detalle.
- Todo lo extraído sin XML (PDF, OCR, correo) entra con confianza baja y pasa
  por revisión antes de contar en informes definitivos.
