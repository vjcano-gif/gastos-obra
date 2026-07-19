-- Datos de pago que la matriz lleva por factura y que hacen falta para
-- reproducir sus tableros SEGUI (obligaciones pendientes):
--   Saldo Calculado -> lo que queda por pagar de esa factura
--   Valor pagado / Fecha de pago -> el pago (o abono) registrado
--
-- Sin el saldo, "cuánto debo" habría que adivinarlo desde estado_pago, y
-- las facturas de Gmail nunca clasificadas (estado_pago 'pendiente' por
-- defecto) inflarían el total. Con el saldo de la matriz, "pendiente" es
-- exactamente saldo > 0, que es como ellos lo miran: su SEGUI da
-- $53.695.352 y así se puede cuadrar.

alter table public.facturas add column if not exists saldo numeric(18, 2);
alter table public.facturas add column if not exists valor_pagado numeric(18, 2);
alter table public.facturas add column if not exists fecha_pago date;

comment on column public.facturas.saldo is
  'Lo que queda por pagar (matriz: Saldo Calculado). NULL = sin dato de pago; saldo > 0 = cuenta por pagar.';

create index if not exists facturas_saldo on public.facturas (user_id) where saldo > 0;
