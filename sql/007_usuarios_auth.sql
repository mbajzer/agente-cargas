-- =====================================================================
-- Mapeia o usuário autenticado no Supabase Auth (claim `sub` do token OAuth do conector MCP)
-- para o cadastro do agente: auth.users.id -> profiles.user_id -> agente.usuarios.profile_id.
-- Rodar como postgres. Só cria uma view e um grant.
-- Só entra quem tem linha ativa em agente.usuarios com profile_id preenchido e profile ativo.
-- =====================================================================
create or replace view agente.vw_usuarios_auth as
select p.user_id as auth_user_id, u.wa_id, u.nome, u.perfil, u.clientes
from agente.usuarios u
join public.profiles p on p.id = u.profile_id
where u.ativo and p.ativo and p.user_id is not null;

grant select on agente.vw_usuarios_auth to agente_app;
