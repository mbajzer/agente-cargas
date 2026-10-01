-- =====================================================================
-- Validação das premissas do agente contra os dados reais da AGT.
-- Rodar como postgres, DEPOIS do 001_agente.sql. Somente leitura.
-- =====================================================================

-- 1) Todas as chaves de campo usadas pela view existem e estão ativas?
--    Esperado: 21 linhas, todas com ativo = true em ao menos uma etapa.
select f.chave, bool_or(f.ativo) as ativo, string_agg(s.ordem::text, ',' order by s.ordem) as etapas
from public.op_stage_fields f
join public.op_stages s on s.id = f.stage_id
where f.chave in (
  'cliente_principal', 'referencia_embarque', 'definicao_di_dta', 'canal', 'canal_di',
  'numero_dta', 'numero_di_duimp', 'local_dta', 'bloqueado_liberado_e8', 'bloqueado_liberado_e9',
  'transportadora', 'data_saida_embarque', 'atualizacao_data_chegada', 'data_chegada_real',
  'presenca_carga', 'data_liberacao_e11', 'data_liberacao_e12', 'data_entrega',
  'entrega_container', 'ed_espera_documentos', 'ed_espera_documentos_ativado_em')
group by f.chave
order by f.chave;

-- 2) Formato real dos códigos: reference_code x referencia_embarque x BL.
--    Define como os usuários vão digitar o código no WhatsApp.
select l.reference_code, v.value_text as referencia_embarque, l.bl_number
from public.op_loads l
left join public.op_load_stage_field_values v
  on v.load_id = l.id
 and v.field_id in (select id from public.op_stage_fields where chave = 'referencia_embarque')
where l.archived_at is null
order by l.created_at desc
limit 30;

-- 3) Situação derivada x etapa do kanban (simula um usuário interno).
--    Procure incoerências, ex.: 'pre_embarque' em etapas 8+ (data de embarque não preenchida).
begin;
  insert into agente.usuarios (wa_id, nome, perfil) values ('__validacao__', 'Validação', 'interno');
  select set_config('app.wa_id', '__validacao__', true);
  select etapa_ordem, etapa_nome, situacao, count(*)
  from agente.vw_cargas
  group by 1, 2, 3
  order by 1, 3;
  -- Esperado: igual ao total de cargas não arquivadas
  select (select count(*) from agente.vw_cargas) as na_view,
         (select count(*) from public.op_loads where archived_at is null) as nao_arquivadas;
rollback;

-- 4) Nomes de clientes a usar em agente.usuarios.clientes
select coalesce(nullif(btrim(v.value_text), ''), '(vazio)') as cliente_principal, count(*) as cargas
from public.op_loads l
left join public.op_load_stage_field_values v
  on v.load_id = l.id
 and v.field_id in (select id from public.op_stage_fields where chave = 'cliente_principal')
where l.archived_at is null
group by 1
order by 2 desc;

-- 5) Isolamento: um cliente fictício NÃO pode ver cargas de outros.
--    Troque 'NOME DO CLIENTE' por um nome da consulta 4.
begin;
  insert into agente.usuarios (wa_id, nome, perfil, clientes)
  values ('__cliente_teste__', 'Teste', 'cliente', array['NOME DO CLIENTE']);
  select set_config('app.wa_id', '__cliente_teste__', true);
  select cliente, count(*) from agente.vw_cargas group by 1;   -- só pode aparecer 1 cliente
  select set_config('app.wa_id', 'numero_inexistente', true);
  select count(*) as deve_ser_zero from agente.vw_cargas;
rollback;

-- 6) Tempo da view (esperado < 200 ms para ~400 cargas / ~35 mil valores)
-- explain analyze select * from agente.vw_cargas;  -- rodar dentro de um begin/set_config como acima
