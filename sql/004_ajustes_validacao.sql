-- =====================================================================
-- 004: ajustes após validação com os dados reais da AGT (28/09/2026)
-- Rodar como postgres no SQL Editor. Idempotente; mesmas colunas da view,
-- então vw_carga_etapas e os grants existentes continuam valendo.
--
--  * norm_id(): busca por código tolera zeros à esquerda ('lin23' = 'LIN023')
--  * bloqueio: "Bloqueado" na etapa 9 com data de desbloqueio conta como liberada
--  * situação 'liberada': também a partir da etapa 13 (NF e ICMS), pois
--    data_liberacao_e12 quase nunca é preenchida
-- (gerado a partir de 001_agente.sql, que continua sendo a fonte da verdade)
-- =====================================================================

-- Igual a norm(), mas ignora zeros à esquerda em cada número:
-- 'lin23' = 'LIN-023' = 'LIN023' (códigos reais: LIN023, TAU081, JA-ST001, YC-CBP012)
create or replace function agente.norm_id(txt text) returns text
language sql immutable parallel safe as $$
  select regexp_replace(agente.norm(txt), '(^|[A-Z])0+([0-9])', '\1\2', 'g')
$$;

create or replace view agente.vw_cargas as
with escopo as (
  select perfil, array(select lower(btrim(x)) from unnest(clientes) x) as clientes
  from agente.vw_usuarios_ativos
  where wa_id = current_setting('app.wa_id', true)
),
campos as (
  select fv.load_id,
    max(fv.value_text)  filter (where f.chave = 'cliente_principal')          as cliente_principal,
    max(fv.value_text)  filter (where f.chave = 'referencia_embarque')        as referencia_embarque,
    max(fv.value_text)  filter (where f.chave = 'definicao_di_dta')           as regime,
    max(fv.value_text)  filter (where f.chave = 'canal')                      as canal_dta,
    max(fv.value_text)  filter (where f.chave = 'canal_di')                   as canal_duimp,
    max(fv.value_text)  filter (where f.chave = 'numero_dta')                 as numero_dta,
    max(fv.value_text)  filter (where f.chave = 'numero_di_duimp')            as numero_duimp,
    max(fv.value_text)  filter (where f.chave = 'local_dta')                  as local_dta,
    max(fv.value_text)  filter (where f.chave = 'bloqueado_liberado_e8')      as bloqueio_presenca,
    max(fv.value_text)  filter (where f.chave = 'bloqueado_liberado_e9')      as bloqueio_sis_carga,
    max(fv.value_text)  filter (where f.chave = 'transportadora')             as transportadora,
    max(fv.value_date)  filter (where f.chave = 'data_saida_embarque')        as data_embarque,
    max(fv.value_date)  filter (where f.chave = 'atualizacao_data_chegada')   as eta_atualizada,
    max(fv.value_date)  filter (where f.chave = 'data_chegada_real')          as data_chegada_real,
    max(fv.value_date)  filter (where f.chave = 'presenca_carga')             as data_presenca_carga,
    max(fv.value_date)  filter (where f.chave = 'data_liberacao_e11')         as data_liberacao_dta,
    max(fv.value_date)  filter (where f.chave = 'data_liberacao_e12')         as data_liberacao_duimp,
    max(fv.value_date)  filter (where f.chave = 'data_desbloqueio_e9')        as data_desbloqueio,
    max(fv.value_date)  filter (where f.chave = 'data_entrega')               as data_entrega,
    max(fv.value_date)  filter (where f.chave = 'entrega_container')          as data_entrega_container,
    bool_or(fv.value_boolean) filter (where f.chave = 'ed_espera_documentos') as ed_ativa,
    max(fv.value_datetime) filter (where f.chave = 'ed_espera_documentos_ativado_em') as ed_ativada_em,
    max(fv.updated_at) as campos_atualizados_em
  from public.op_load_stage_field_values fv
  join public.op_stage_fields f on f.id = fv.field_id
  where not fv.is_na
    and f.chave in (
      'cliente_principal', 'referencia_embarque', 'definicao_di_dta', 'canal', 'canal_di',
      'numero_dta', 'numero_di_duimp', 'local_dta', 'bloqueado_liberado_e8', 'bloqueado_liberado_e9',
      'transportadora', 'data_saida_embarque', 'atualizacao_data_chegada', 'data_chegada_real',
      'presenca_carga', 'data_liberacao_e11', 'data_liberacao_e12', 'data_desbloqueio_e9', 'data_entrega',
      'entrega_container', 'ed_espera_documentos', 'ed_espera_documentos_ativado_em')
  group by fv.load_id
),
cargas as (
  select
    l.id                                             as load_id,
    l.reference_code,
    c.referencia_embarque,
    coalesce(nullif(btrim(c.cliente_principal), ''), nullif(btrim(l.client_name), '')) as cliente,
    s.ordem                                          as etapa_ordem,
    s.nome                                           as etapa_nome,
    st.started_at                                    as etapa_desde,
    l.main_importer_company                          as importadora,
    l.shipper_name                                   as exportadora,
    l.freight_agent                                  as agente_cargas,
    l.product_category                               as categoria,
    l.vessel                                         as navio,
    l.port                                           as porto,
    l.bl_number,
    l.container_numbers,
    c.data_embarque,
    -- o card e os relatórios priorizam atualizacao_data_chegada sobre op_loads.eta_date
    coalesce(c.eta_atualizada, l.eta_date)           as eta,
    coalesce(l.real_arrival_date, c.data_chegada_real) as data_chegada,
    c.data_presenca_carga,
    nullif(c.regime, 'NAO_DEFINIDO')                 as regime,
    c.canal_dta, c.canal_duimp, c.numero_dta, c.numero_duimp, c.local_dta,
    c.data_liberacao_dta, c.data_liberacao_duimp,
    -- a equipe mantém "Bloqueado" na etapa 9 e registra a data de desbloqueio:
    -- com data de desbloqueio preenchida, a carga está liberada
    case
      when c.data_desbloqueio is not null then 'liberada'
      else case lower(coalesce(nullif(btrim(c.bloqueio_sis_carga), ''), nullif(btrim(c.bloqueio_presenca), '')))
        when 'bloqueado' then 'bloqueada' when 'bloqueada' then 'bloqueada'
        when 'liberado'  then 'liberada'  when 'liberada'  then 'liberada' when 'livre' then 'liberada'
      end
    end                                              as bloqueio,
    c.transportadora,
    c.data_entrega,
    c.data_entrega_container,
    -- mesma regra do campo calculado data_demurrage (etapa 6): chegada atualizada + 19 dias,
    -- ou data de ativação da ED + 19 dias quando a flag ED estiver ativa
    coalesce(case when c.ed_ativa then (c.ed_ativada_em at time zone 'America/Sao_Paulo')::date end,
             c.eta_atualizada) + 19                  as data_limite_demurrage,
    case
      when l.finalized_at is not null                          then 'finalizada'
      when c.data_entrega is not null                          then 'entregue'
      -- data_liberacao_e12 quase nunca é preenchida; a etapa 13 (NF e ICMS) em diante
      -- só ocorre após o desembaraço (todas as cargas lá têm nº e canal da DUIMP)
      when c.data_liberacao_duimp is not null or s.ordem >= 13 then 'liberada'
      when coalesce(l.real_arrival_date, c.data_chegada_real, c.data_presenca_carga) is not null
                                                               then 'chegou'
      when c.data_embarque is not null                         then 'em_transito'
      else 'pre_embarque'
    end                                              as situacao,
    greatest(l.updated_at, c.campos_atualizados_em)  as atualizado_em
  from public.op_loads l
  left join public.op_stages s on s.id = l.current_stage_id
  left join public.op_load_stage_statuses st on st.load_id = l.id and st.stage_id = l.current_stage_id
  left join campos c on c.load_id = l.id
  where l.archived_at is null
)
select cargas.*
from cargas
where exists (
  select 1 from escopo e
  where e.perfil = 'interno'
     or (e.perfil = 'cliente' and lower(cargas.cliente) = any (e.clientes))
);

grant execute on function agente.norm_id(text) to agente_app;
