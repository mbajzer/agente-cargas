from dataclasses import dataclass

from app import db


@dataclass(frozen=True)
class Usuario:
    wa_id: str
    nome: str
    perfil: str              # 'interno' | 'cliente'
    clientes: tuple[str, ...]


async def registrar_se_nova(message_id: str, wa_id: str) -> bool:
    async with db.pool.acquire() as con:
        r = await con.execute("insert into agente.mensagens (wa_message_id, wa_id) values ($1, $2) "
                              "on conflict do nothing", message_id, wa_id)
        return r.endswith("1")


async def buscar_usuario(wa_id: str) -> Usuario | None:
    async with db.pool.acquire() as con:
        r = await con.fetchrow("select wa_id, nome, perfil, clientes from agente.vw_usuarios_ativos "
                               "where wa_id = $1", wa_id)
    if not r:
        return None
    return Usuario(r["wa_id"], r["nome"], r["perfil"], tuple(r["clientes"] or ()))


async def excedeu_limite(wa_id: str, por_hora: int) -> bool:
    async with db.pool.acquire() as con:
        n = await con.fetchval("select count(*) from agente.mensagens where wa_id = $1 "
                               "and recebido_em > now() - interval '1 hour'", wa_id)
    return n > por_hora


async def buscar_usuario_por_auth(auth_user_id: str) -> Usuario | None:
    """Usuário do cadastro a partir do id do Supabase Auth (claim `sub` do token OAuth)."""
    async with db.pool.acquire() as con:
        r = await con.fetchrow("select wa_id, nome, perfil, clientes from agente.vw_usuarios_auth "
                               "where auth_user_id::text = $1", auth_user_id)
    if not r:
        return None
    return Usuario(r["wa_id"], r["nome"], r["perfil"], tuple(r["clientes"] or ()))
