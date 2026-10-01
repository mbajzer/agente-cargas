"""Servidor MCP (somente leitura) para o Claude consultar as cargas da AGT/Luveo.

Reaproveita as consultas do agente de WhatsApp (app.ferramentas), que rodam nas views do
schema `agente` com a role agente_app. O escopo vem do usuário cadastrado em
agente.usuarios cujo wa_id está em MCP_WA_ID (use um usuário 'interno' dedicado);
o Claude nunca escolhe o escopo.
"""
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_access_token

from app import db, ferramentas
from app.seguranca import buscar_usuario, buscar_usuario_por_auth

log = logging.getLogger("agente.mcp")



def _criar_auth():
    """OAuth do Supabase em produção (SUPABASE_URL + MCP_PUBLIC_URL); token fixo só para teste local."""
    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    if supabase_url:
        from fastmcp.server.auth.providers.supabase import SupabaseProvider
        base_url = os.environ.get("MCP_PUBLIC_URL", "").strip()
        if not base_url:
            raise RuntimeError("MCP_PUBLIC_URL é obrigatória com SUPABASE_URL (URL pública deste servidor)")
        return SupabaseProvider(project_url=supabase_url, base_url=base_url,
                                algorithm=os.environ.get("SUPABASE_JWT_ALG", "ES256"))
    token = os.environ.get("MCP_TOKEN", "").strip()
    if len(token) < 32:
        raise RuntimeError("Defina SUPABASE_URL (OAuth) ou, só em teste local, MCP_TOKEN com >= 32 caracteres")
    from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
    return StaticTokenVerifier({token: {"client_id": "dev-local", "scopes": []}})


@asynccontextmanager
async def _lifespan(_server):
    await db.init()
    try:
        yield
    finally:
        await db.close()


mcp = FastMCP("Luveo", auth=_criar_auth(), lifespan=_lifespan)

Situacao = Literal["pre_embarque", "em_transito", "chegou", "liberada", "entregue", "finalizada"]


def _qtd(out: dict) -> int:
    if "carga" in out:
        return 1
    if "linhas" in out:
        return out["total"]
    return out.get("total", out.get("quantidade", out.get("total_em_andamento",
                   len(out.get("candidatas", out.get("etapas", [])))))) or 0


async def _auditar(wa_id: str, ferramenta: str, params: dict, out: dict):
    # Acessório: se falhar, registra no log e segue, sem perder a resposta.
    try:
        async with db.pool.acquire() as con:
            await con.execute("insert into agente.auditoria (wa_id, ferramenta, parametros, qtd_resultados) "
                              "values ($1, $2, $3::jsonb, $4)",
                              wa_id, "mcp:" + ferramenta,
                              json.dumps(params, ensure_ascii=False, default=str), _qtd(out))
    except Exception:
        log.exception("falha ao gravar auditoria")


async def _usuario():
    """Quem está chamando: no OAuth, o usuário do Supabase Auth (claim `sub`) cadastrado em
    agente.usuarios; no teste local com token fixo, o usuário MCP_WA_ID. O escopo nunca vem do Claude."""
    if os.environ.get("SUPABASE_URL", "").strip():
        token = get_access_token()
        sub = (token.claims or {}).get("sub") if token else None
        usuario = await buscar_usuario_por_auth(sub) if sub else None
        if usuario is None:
            log.warning("mcp: usuário autenticado sem cadastro ativo em agente.usuarios (sub=%s)", sub)
            raise PermissionError("Seu usuário não tem acesso ao conector. Peça liberação ao administrador.")
        return usuario
    usuario = await buscar_usuario(os.environ["MCP_WA_ID"])
    if usuario is None:
        raise RuntimeError("Usuário MCP_WA_ID não cadastrado/ativo em agente.usuarios")
    return usuario


async def _rodar(nome: str, args: dict) -> dict:
    usuario = await _usuario()
    resultado = await ferramentas.executar_ferramenta(nome, args, usuario, date.today())
    params = {k: v for k, v in args.items() if v is not None}
    log.info("mcp %s %s", nome, params)
    await _auditar(usuario.wa_id, nome, params, resultado)
    return resultado


@mcp.tool
async def consultar_carga(identificador: str) -> dict:
    """Situação completa de UMA carga: etapa, navio, previsão de chegada, canal, bloqueio e
    demurrage. Aceita código de referência (ex.: LIN023, JA-ST001), referência do embarque,
    número do BL ou número de contêiner, mesmo sem hífen ou com espaços."""
    return await _rodar("consultar_carga", {"identificador": identificador})


@mcp.tool
async def historico_carga(identificador: str) -> dict:
    """Linha do tempo de UMA carga pelas etapas do processo, com datas de início e conclusão.
    Aceita código, BL ou contêiner."""
    return await _rodar("historico_carga", {"identificador": identificador})


@mcp.tool
async def contar_cargas(situacao: Situacao | None = None, etapa: int | None = None,
                        cliente: str | None = None, bloqueada: bool | None = None) -> dict:
    """Conta cargas em andamento. Sem filtros devolve o total por situação; com filtros, o total
    e a divisão por etapa. situacao: pre_embarque (na China), em_transito (no mar), chegou
    (no porto/desembaraço), liberada (DUIMP desembaraçada, aguardando entrega), entregue, finalizada."""
    return await _rodar("contar_cargas", {"situacao": situacao, "etapa": etapa,
                                          "cliente": cliente, "bloqueada": bloqueada})


@mcp.tool
async def listar_cargas(situacao: Situacao | None = None, etapa: int | None = None,
                        porto: str | None = None, cliente: str | None = None,
                        bloqueada: bool | None = None,
                        eta_de: str | None = None, eta_ate: str | None = None,
                        demurrage_vence_em_ate_dias: int | None = None,
                        em_demurrage: bool | None = None,
                        ordenar_por: Literal["eta", "demurrage", "etapa"] | None = None) -> dict:
    """Lista até 10 cargas com filtros combináveis (datas AAAA-MM-DD). Use para 'cargas que
    chegam esta semana' (eta_de/eta_ate), 'perto de demurrage' (demurrage_vence_em_ate_dias),
    'já em demurrage' (em_demurrage), 'cargas no porto X', cargas bloqueadas etc."""
    return await _rodar("listar_cargas", {
        "situacao": situacao, "etapa": etapa, "porto": porto, "cliente": cliente,
        "bloqueada": bloqueada, "eta_de": eta_de, "eta_ate": eta_ate,
        "demurrage_vence_em_ate_dias": demurrage_vence_em_ate_dias,
        "em_demurrage": em_demurrage, "ordenar_por": ordenar_por})


LIMITE_RELATORIO = 500

SQL_RELATORIO = """
select *, count(*) over () as total from agente.vw_relatorio_operacional
where ($1::date is null or data_chegada_atualizada >= $1)
  and ($2::date is null or data_chegada_atualizada <= $2)
  and ($3::text is null or situacao = $3)
  and ($3::text is not null or $4::bool or situacao <> 'finalizada')
  and ($5::text is null or cliente ilike '%' || $5 || '%')
order by cliente, referencia
limit $6"""


def _json(v):
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


@mcp.tool
async def relatorio_operacional(data_inicio: str | None = None, data_fim: str | None = None,
                                situacao: Situacao | None = None, cliente: str | None = None,
                                incluir_finalizadas: bool = False,
                                limite: int = 200) -> dict:
    """Relatório operacional (template "OPERACIONAL 1"): uma linha por carga com referência, cliente,
    importadora, categoria, BL, navio, órgão anuente, certificados, item pendente, data de chegada
    atualizada, bloqueio/liberação, datas de LI/LPCO, GRU, deferimento, canais DTA/DUIMP, liberação,
    entrega e custo de importação (R$, só para perfil interno).
    data_inicio/data_fim (AAAA-MM-DD) filtram pela data de chegada atualizada (ETA); sem datas,
    traz todas as cargas em andamento. Processos finalizados só entram com incluir_finalizadas=true
    ou situacao='finalizada'."""
    def dia(v):
        try:
            return date.fromisoformat(v) if v else None
        except ValueError:
            raise ValueError(f"Data inválida '{v}': use AAAA-MM-DD")
    ini, fim = dia(data_inicio), dia(data_fim)
    if ini and fim and ini > fim:
        raise ValueError("data_inicio não pode ser posterior a data_fim")
    limite = max(1, min(int(limite), LIMITE_RELATORIO))
    cli = ferramentas._like(cliente)
    args = {"data_inicio": data_inicio, "data_fim": data_fim, "situacao": situacao, "cliente": cliente,
            "incluir_finalizadas": incluir_finalizadas or None, "limite": limite}

    usuario = await _usuario()
    rows = await db.consultar(usuario.wa_id, SQL_RELATORIO, ini, fim, situacao, incluir_finalizadas,
                              cli, limite)
    colunas = [c for c in (rows[0].keys() if rows else []) if c not in ("load_id", "total", "etapa_ordem")]
    out = {"total": rows[0]["total"] if rows else 0, "exibindo": len(rows),
           "linhas": [{c: _json(r[c]) for c in colunas} for r in rows]}
    params = {k: v for k, v in args.items() if v is not None}
    log.info("mcp relatorio_operacional %s", params)
    await _auditar(usuario.wa_id, "relatorio_operacional", params, out)
    return out


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    from starlette.responses import JSONResponse
    return JSONResponse({"ok": True})
