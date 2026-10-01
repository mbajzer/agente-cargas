-- =====================================================================
-- 005: políticas RLS para a role do app nas tabelas do schema agente
--
-- Este projeto tem o event trigger `ensure_rls`, que liga RLS em toda tabela
-- nova. Sem políticas, a agente_app não consegue gravar (dedup, histórico,
-- auditoria) e as leituras voltam vazias. Mantemos o RLS ligado e liberamos
-- somente o que o app usa. Rodar como postgres no SQL Editor. Idempotente.
--
-- agente.usuarios fica SEM política de propósito: o app só lê usuários pela
-- view agente.vw_usuarios_ativos (que roda como dono), nunca a tabela.
-- =====================================================================

drop policy if exists agente_app_mensagens on agente.mensagens;
create policy agente_app_mensagens on agente.mensagens
  for all to agente_app using (true) with check (true);

drop policy if exists agente_app_historico on agente.historico;
create policy agente_app_historico on agente.historico
  for all to agente_app using (true) with check (true);

drop policy if exists agente_app_auditoria on agente.auditoria;
create policy agente_app_auditoria on agente.auditoria
  for all to agente_app using (true) with check (true);

-- As políticas "for all" não ampliam privilégios: a agente_app continua só com
-- SELECT e INSERT nessas tabelas (grants do 001), sem UPDATE nem DELETE.
