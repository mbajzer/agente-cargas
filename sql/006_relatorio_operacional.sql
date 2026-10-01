-- =====================================================================
-- Relatório operacional (template "OPERACIONAL 1") para o conector MCP.
-- Rodar como postgres, DEPOIS do 001_agente.sql. Somente cria uma view e um grant.
--
-- Herda o escopo de agente.vw_cargas (interno vê tudo; cliente só as suas cargas).
-- Diferente de vw_cargas, inclui "Custo Importação R$" (financeiro): só é exposto
-- para perfil 'interno'; para 'cliente' a coluna vem nula.
-- =====================================================================
create or replace view agente.vw_relatorio_operacional as
with escopo as (
  select perfil from agente.vw_usuarios_ativos
  where wa_id = current_setting('app.wa_id', true)
),
extra as (
  select fv.load_id,
    max(fv.value_text)   filter (where f.chave = 'orgao_anuente')          as orgao_anuente,
    max(fv.value_text)   filter (where f.chave = 'certificados_oa')        as certificados_oa,
    max(fv.value_text)   filter (where f.chave = 'item_produto_pendente')  as item_produto_pendente,
    max(fv.value_date)   filter (where f.chave = 'data_registro_li_lpco')  as data_registro_li_lpco,
    max(fv.value_date)   filter (where f.chave = 'data_pagamento_gru_lpco') as data_pagamento_gru,
    max(fv.value_date)   filter (where f.chave = 'data_deferimento_lpco')  as data_deferimento,
    max(fv.value_date)   filter (where f.chave = 'data_desbloqueio_e9')    as data_desbloqueio,
    max(fv.value_number) filter (where f.chave = 'custo_importacao')       as custo_importacao
  from public.op_load_stage_field_values fv
  join public.op_stage_fields f on f.id = fv.field_id
  where not fv.is_na
    and f.chave in ('orgao_anuente', 'certificados_oa', 'item_produto_pendente',
                    'data_registro_li_lpco', 'data_pagamento_gru_lpco', 'data_deferimento_lpco',
                    'data_desbloqueio_e9', 'custo_importacao')
    and fv.load_id in (select load_id from agente.vw_cargas)   -- herda o escopo
  group by fv.load_id
)
select
  c.load_id,
  c.reference_code                                   as referencia,
  c.cliente,
  c.importadora                                      as empresa_importadora,
  c.categoria                                        as categoria_produtos,
  c.bl_number                                        as bl,
  c.navio,
  x.orgao_anuente,
  x.certificados_oa,
  x.item_produto_pendente,
  c.eta                                              as data_chegada_atualizada,
  c.bloqueio                                         as bloqueado_ou_liberado,
  x.data_desbloqueio,
  x.data_registro_li_lpco,
  x.data_pagamento_gru,
  x.data_deferimento,
  c.canal_dta,
  c.canal_duimp,
  coalesce(c.data_liberacao_duimp, c.data_liberacao_dta) as data_liberacao,
  c.data_entrega                                     as entrega_ao_cliente,
  case when (select perfil from escopo) = 'interno' then x.custo_importacao end as custo_importacao,
  -- apoio a filtros
  c.situacao, c.etapa_ordem, c.etapa_nome, c.porto
from agente.vw_cargas c
left join extra x on x.load_id = c.load_id;

grant select on agente.vw_relatorio_operacional to agente_app;
