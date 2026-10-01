"""Ferramentas do agente: SQL fixo e parametrizado sobre as views do schema `agente`.

Nenhuma ferramenta recebe escopo (cliente/usuário) como parâmetro: o escopo vem do
wa_id e é aplicado pela view agente.vw_cargas.
"""
from datetime import date

from app import db
from app.formatacao import (SITUACOES, br, formatar_carga, normalizar_identificador,
                            resumo_carga)

DESCRICAO_SITUACOES = (
    "pre_embarque = ainda na China, sem data de embarque; "
    "em_transito = embarcada e navegando ('no mar'); "
    "chegou = chegou ao Brasil / em desembaraço aduaneiro ('no porto', 'na alfândega'); "
    "liberada = DUIMP desembaraçada, aguardando entrega; "
    "entregue = entregue ao cliente; "
    "finalizada = processo encerrado no sistema.")

STATUS_ETAPA = {"completed": "concluída", "not_applicable": "não aplicável",
                "blocked": "bloqueada", "pending": "pendente", "current": "iniciada"}


def montar_tools(etapas: list) -> list[dict]:
    lista_etapas = "; ".join(f"{e['ordem']}. {e['nome']}" for e in etapas)
    maior_etapa = max((e["ordem"] for e in etapas), default=16)
    prop_situacao = {"type": "string", "enum": list(SITUACOES), "description": DESCRICAO_SITUACOES}
    prop_etapa = {"type": "integer", "minimum": 1, "maximum": maior_etapa,
                  "description": f"Número da etapa do kanban. Etapas: {lista_etapas}."}
    prop_cliente = {"type": "string", "description": "Parte do nome do cliente (ex.: JACK inclui JACK (CBP), "
                                                     "JACK (XQSY) etc.). Só faz efeito para usuários internos."}
    prop_bloqueada = {"type": "boolean", "description": "true = somente cargas bloqueadas (presença de carga "
                                                        "ou Siscomex Carga, sem data de desbloqueio)."}
    return [
        {
            "name": "consultar_carga",
            "description": "Retorna a situação completa de UMA carga: etapa, navio, previsão de chegada, "
                           "canal, bloqueio, demurrage. Aceita o código de referência (ex.: LIN023, JA-ST001), "
                           "a referência do embarque, o número do BL ou o número de um contêiner, "
                           "mesmo digitado sem hífen ou com espaços.",
            "input_schema": {"type": "object", "properties": {
                "identificador": {"type": "string", "description": "Código, BL ou contêiner, como o usuário escreveu."}},
                "required": ["identificador"]},
        },
        {
            "name": "historico_carga",
            "description": "Linha do tempo de UMA carga pelas etapas do processo, com datas de início e "
                           "conclusão. Use para 'desde quando', 'quando foi registrada a DUIMP', "
                           "'o que já foi feito'.",
            "input_schema": {"type": "object", "properties": {
                "identificador": {"type": "string", "description": "Código, BL ou contêiner."}},
                "required": ["identificador"]},
        },
        {
            "name": "contar_cargas",
            "description": "Conta cargas em andamento. Sem filtros, devolve o total por situação. "
                           "Com filtros, devolve o total e a divisão por etapa. "
                           "Use para 'quantas cargas...', 'como estão as cargas'.",
            "input_schema": {"type": "object", "properties": {
                "situacao": prop_situacao, "etapa": prop_etapa,
                "cliente": prop_cliente, "bloqueada": prop_bloqueada}},
        },
        {
            "name": "listar_cargas",
            "description": "Lista até 10 cargas com filtros combináveis. Use para 'quais cargas...', "
                           "'cargas que chegam esta semana', 'cargas perto de demurrage', 'cargas no porto X'.",
            "input_schema": {"type": "object", "properties": {
                "situacao": prop_situacao,
                "etapa": prop_etapa,
                "porto": {"type": "string", "description": "Parte do nome do porto (ex.: Santos, Navegantes, RJ)."},
                "cliente": prop_cliente,
                "bloqueada": prop_bloqueada,
                "eta_de": {"type": "string", "description": "Previsão de chegada a partir de (AAAA-MM-DD)."},
                "eta_ate": {"type": "string", "description": "Previsão de chegada até (AAAA-MM-DD)."},
                "demurrage_vence_em_ate_dias": {"type": "integer", "minimum": 0, "maximum": 60,
                                                "description": "Cargas cujo prazo de demurrage AINDA NÃO venceu e vence "
                                                               "nos próximos N dias ('perto de entrar em demurrage')."},
                "em_demurrage": {"type": "boolean",
                                 "description": "true = somente cargas cujo prazo de demurrage JÁ venceu "
                                                "(contêiner ainda não devolvido)."},
                "ordenar_por": {"type": "string", "enum": ["eta", "demurrage", "etapa"]}}},
        },
    ]


# ---------------------------------------------------------------- validação

def _data(s) -> date | None:
    try:
        return date.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def _int(v, lo: int, hi: int) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def _like(s, max_len: int = 60) -> str | None:
    if not isinstance(s, str) or not s.strip():
        return None
    return s.strip()[:max_len].replace("\\", "").replace("%", "").replace("_", " ")


def _situacao(v) -> str | None:
    return v if v in SITUACOES else None


# ---------------------------------------------------------------- consultas

# norm_id ignora separadores e zeros à esquerda: 'lin 23' encontra LIN023.
# Alguns itens de container_numbers trazem vários números ('TGBU6285400/EMCEXV6045').
SQL_EXATO = """
select * from agente.vw_cargas
where agente.norm_id(reference_code) = agente.norm_id($1)
   or agente.norm_id(referencia_embarque) = agente.norm_id($1)
   or agente.norm_id(bl_number) = agente.norm_id($1)
   or agente.norm_id($1) in (select agente.norm_id(y)
                             from unnest(container_numbers) x,
                                  regexp_split_to_table(x, '[/;,[:space:]]+') y)
limit 5"""

SQL_PARCIAL = """
select * from agente.vw_cargas
where agente.norm_id(reference_code) like '%' || agente.norm_id($1) || '%'
   or agente.norm_id(referencia_embarque) like '%' || agente.norm_id($1) || '%'
order by atualizado_em desc
limit 5"""


async def resolver_carga(wa_id: str, identificador) -> list:
    n = normalizar_identificador(identificador if isinstance(identificador, str) else "")[:40]
    if len(n) < 3:
        return []
    rows = await db.consultar(wa_id, SQL_EXATO, n)
    if not rows and len(n) >= 4:
        rows = await db.consultar(wa_id, SQL_PARCIAL, n)
    return rows


async def executar_ferramenta(nome: str, args: dict, usuario, hoje: date) -> dict:
    wa_id = usuario.wa_id

    if nome in ("consultar_carga", "historico_carga"):
        ident = args.get("identificador")
        rows = await resolver_carga(wa_id, ident)
        # Mesma resposta para "não existe" e "não é deste cliente": evita enumeração
        if not rows:
            return {"resultado": "nao_encontrada", "identificador": ident}
        if len(rows) > 1:
            return {"resultado": "varias_encontradas",
                    "candidatas": [resumo_carga(r, hoje) for r in rows]}
        carga = rows[0]
        if nome == "consultar_carga":
            return {"carga": formatar_carga(carga, hoje)}
        etapas = await db.consultar(wa_id, """
            select ordem, nome, status, is_current, started_at, completed_at
            from agente.vw_carga_etapas
            where load_id = $1 and (is_current or started_at is not null or completed_at is not null)
            order by ordem""", carga["load_id"])
        return {"codigo": carga["reference_code"],
                "situacao": SITUACOES.get(carga["situacao"]),
                "etapas": [{k: v for k, v in {
                    "etapa": f"{e['ordem']}. {e['nome']}",
                    "status": "atual" if e["is_current"] else STATUS_ETAPA.get(e["status"], e["status"]),
                    "inicio": br(e["started_at"]),
                    "conclusao": br(e["completed_at"]),
                }.items() if v} for e in etapas]}

    if nome == "contar_cargas":
        situacao, etapa = _situacao(args.get("situacao")), _int(args.get("etapa"), 1, 99)
        cliente, bloqueada = _like(args.get("cliente")), args.get("bloqueada") is True
        if situacao is None and etapa is None and cliente is None and not bloqueada:
            rows = await db.consultar(wa_id, "select situacao, count(*) as n from agente.vw_cargas group by 1")
            por = {r["situacao"]: r["n"] for r in rows}
            return {"total_em_andamento": sum(n for s, n in por.items() if s != "finalizada"),
                    "por_situacao": {SITUACOES[s]: por[s] for s in SITUACOES if s in por}}
        rows = await db.consultar(wa_id, """
            select etapa_ordem, etapa_nome, count(*) as n from agente.vw_cargas
            where ($1::text is null or situacao = $1)
              and ($1::text is not null or situacao <> 'finalizada')
              and ($2::int is null or etapa_ordem = $2)
              and ($3::text is null or cliente ilike '%' || $3 || '%')
              and (not $4::bool or bloqueio = 'bloqueada')
            group by 1, 2 order by 1 nulls last""", situacao, etapa, cliente, bloqueada)
        return {"filtro": {k: v for k, v in {"situacao": SITUACOES.get(situacao), "etapa": etapa,
                                             "cliente": cliente, "bloqueada": bloqueada or None}.items() if v},
                "quantidade": sum(r["n"] for r in rows),
                "por_etapa": [{"etapa": f"{r['etapa_ordem']}. {r['etapa_nome']}" if r["etapa_ordem"]
                               else "sem etapa", "quantidade": r["n"]} for r in rows]}

    if nome == "listar_cargas":
        ordenar = args.get("ordenar_por") if args.get("ordenar_por") in ("eta", "demurrage", "etapa") else "eta"
        rows = await db.consultar(wa_id, """
            select *, count(*) over () as total from agente.vw_cargas
            where ($1::text is null or situacao = $1)
              and ($1::text is not null or situacao <> 'finalizada')
              and ($2::int  is null or etapa_ordem = $2)
              and ($3::text is null or porto ilike '%' || $3 || '%')
              and ($4::text is null or cliente ilike '%' || $4 || '%')
              and ($5::date is null or eta >= $5)
              and ($6::date is null or eta <= $6)
              and ($7::int  is null or data_limite_demurrage between $8::date and $8::date + $7)
              and (not $11::bool or data_limite_demurrage < $8::date)
              and ($7::int is null and not $11::bool
                   or (data_entrega_container is null and situacao in ('chegou', 'liberada')))
              and (not $10::bool or bloqueio = 'bloqueada')
            order by case when $9::text = 'demurrage' then data_limite_demurrage end nulls last,
                     case when $9::text = 'etapa' then etapa_ordem end nulls last,
                     eta nulls last
            limit 10""",
            _situacao(args.get("situacao")), _int(args.get("etapa"), 1, 99),
            _like(args.get("porto")), _like(args.get("cliente")),
            _data(args.get("eta_de")), _data(args.get("eta_ate")),
            _int(args.get("demurrage_vence_em_ate_dias"), 0, 60), hoje, ordenar,
            args.get("bloqueada") is True, args.get("em_demurrage") is True)
        total = rows[0]["total"] if rows else 0
        return {"total": total, "exibindo": len(rows), "cargas": [resumo_carga(r, hoje) for r in rows]}

    return {"erro": "ferramenta_desconhecida"}
