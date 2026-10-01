import os

import asyncpg

pool: asyncpg.Pool | None = None


async def init():
    global pool
    # Pooler do Supabase em modo transação (porta 6543) exige statement_cache_size=0.
    # Usuário no pooler: agente_app.<project_ref>
    pool = await asyncpg.create_pool(os.environ["AGENTE_DB_URL"], min_size=1, max_size=5,
                                     statement_cache_size=0)


async def close():
    if pool:
        await pool.close()


async def consultar(wa_id: str, sql: str, *args, uma: bool = False):
    """Leitura nas views de cargas com o escopo do número de WhatsApp.

    Quem aplica o escopo é a própria view (agente.vw_cargas), a partir de app.wa_id.
    O LLM nunca influencia este valor.
    """
    async with pool.acquire() as con:
        async with con.transaction(readonly=True):
            await con.execute("select set_config('app.wa_id', $1, true),"
                              "       set_config('statement_timeout', '3000', true)", wa_id)
            if uma:
                return await con.fetchrow(sql, *args)
            return await con.fetch(sql, *args)


async def listar_etapas() -> list[asyncpg.Record]:
    async with pool.acquire() as con:
        return await con.fetch("select ordem, nome from agente.vw_etapas order by ordem")
