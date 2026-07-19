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

1. **Supabase**: crear proyecto nuevo y correr **todas** las migraciones de
   `supabase/migrations/` en orden numérico en el SQL Editor (001, 002, …).
   Notas: si al crear el proyecto dejaste activado "Automatically expose new
   tables", 003 y 004 son redundantes pero inofensivas (ese toggle es el que
   aplica los GRANT); si lo desactivaste, son obligatorias — sin ellas toda
   la app falla con "permission denied" aunque el RLS esté perfecto.
   A partir de 009 el rol `lector` deja de poder escribir, y 011 agrega el
   rol `aprobador` + la auditoría de cambios.
   **013–017 traen el modelo real de la constructora**: cortes de obra,
   %AIU y comisión, pagador heredado del proyecto, anticipos del cliente,
   presupuesto semanal, el rol `cliente` y la trazabilidad del histórico
   importado. Van en orden y **la 016 debe correrse completa**: es la que
   cierra el acceso del cliente a las facturas (sin ella, un cliente
   invitado vería todas las obras).
   En Authentication → Users → crear el usuario dueño (correo + contraseña).
   Copiar: URL del proyecto, `anon key`, `service_role key` y el UUID del usuario.
2. **Google Cloud**: reutilizar el proyecto OAuth existente; agregar el correo del
   buzón como *test user* y generar el refresh token (scope `gmail.readonly`).
   Si el buzón del cliente no es Google, configurar reenvío automático a un Gmail
   espejo dedicado.
3. **GitHub**: crear repo privado con este contenido. En Settings → Secrets →
   Actions crear: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `APP_USER_ID`,
   `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`,
   `PDF_PASSWORDS` (opcional, separadas por coma) y **`OPENAI_API_KEY`**.
   Sin `OPENAI_API_KEY` el sistema funciona, pero apagado en tres frentes:
   no sugiere tipo de gasto para proveedores nuevos, no extrae datos de
   documentos sin XML (cuentas de cobro, consignaciones en el cuerpo del
   correo) y **no hace OCR** de PDFs escaneados ni de fotos de recibos —
   esos documentos se guardan pero entran a Revisión sin datos.
   `LLM_MODEL_VISION` (opcional) cambia el modelo de OCR: por defecto
   `gpt-4o-mini`; `gpt-4o` acierta más en fotos difíciles y cuesta más.
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

## El modelo de la constructora (cortes, AIU, cash flow)

El sistema replica el archivo que llevan hoy en Excel. Cuatro conceptos:

- **Corte de obra**: periodo de ejecución (normalmente mensual) con fechas
  propias por proyecto. Es el eje de todos sus informes: capítulo × corte,
  cash flow por corte. Si el corte tiene fechas, **cada factura cae sola en
  el suyo** — una columna menos que digitar.
- **%AIU**: vive en el proyecto y es la base de la comisión de Espacios. Se
  calcula por separado sobre los gastos y sobre los pagos directos del
  cliente, porque el pago directo genera comisión pero no sale de la caja.
  Una factura marcada *exenta de AIU* no entra en la base.
- **Pagador**: se define al crear el proyecto (Espacios / Cliente / Mixto).
  Solo el modo *mixto* obliga a indicarlo factura por factura.
- **Cash flow**: `caja final = caja inicial + anticipos − subtotal`, donde
  `subtotal = gastos + AIU gastos + AIU pagos directos + GMF + otros`. El
  saldo se encadena de un corte al siguiente. Verificado contra los cortes
  1 y 2 de Casa Vieja 61 en `tests/test_cash_flow.py`.

**Módulo del cliente**: un usuario con rol `cliente` queda amarrado a un
proyecto y solo entra a *Cash Flow del proyecto*: sus anticipos, el costo
por capítulo y corte, y su caja. No ve proveedores, facturas individuales,
evidencia ni las otras obras — lo garantiza el RLS de la migración 016, no
la interfaz.

## Importar el histórico de Excel

Su matriz tiene ~2.359 movimientos, la mayoría ya clasificados a mano.
`worker/importar_matriz.py` los cruza contra las facturas que ya llegaron
por Gmail (por número + NIT, número + valor o número + proveedor) y
**hereda la clasificación sin pisar nada**: si algo ya estaba clasificado
en la app, esa decisión manda. Ante cualquier ambigüedad no empareja —
heredar mal es peor que dejar vacío, porque nadie lo revisa después.

Lo que nunca tuvo factura electrónica (papel, cuenta de cobro, nómina)
entra como movimiento propio con `fuente='matriz'` y confianza baja, para
que el costo del proyecto cuadre. Todo queda marcado con su fila de origen,
así que la importación es reejecutable y reversible.

Se lanza desde GitHub → Actions → "Importar matriz histórica", **primero
con `simular` activado** para ver el informe sin escribir nada.

Antes de importar, carga el catálogo de obra desde Configuración →
Capítulos → "Cargar el catálogo de obra": son sus 17 capítulos y 154
actividades con la numeración que ya usan. Sin eso no hay con qué
emparejar la clasificación.

## Reglas de negocio clave

- Deduplicación por capas: CUFE → id del correo → hash del adjunto → heurística
  de consignaciones (posible duplicado queda para decisión humana).
- Las notas crédito restan del costo del proyecto.
- Las reglas de retención nunca se editan: se cierra la vigencia y se crea una
  nueva. El valor calculado queda congelado en cada factura con su detalle.
- Todo lo extraído sin XML (PDF, OCR, correo) entra con confianza baja y pasa
  por revisión antes de contar en informes definitivos.
