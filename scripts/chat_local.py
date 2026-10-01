"""Conversa com o agente pelo terminal, sem WhatsApp (mesmo código do webhook, exceto o envio).

Uso (na raiz do projeto, com o .env preenchido):
    .venv\\Scripts\\python -m scripts.chat_local              # primeiro usuário interno ativo
    .venv\\Scripts\\python -m scripts.chat_local 5521999998888 # um número específico
Digite 'sair' para encerrar.
"""
import asyncio
import os
import sys
from pathlib import Path


def carregar_env(caminho: Path):
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            os.environ.setdefault(chave.strip(), valor.strip())


carregar_env(Path(__file__).resolve().parent.parent / ".env")

from app import agente, db  # noqa: E402  (precisa do .env carregado antes)
from app.formatacao import para_whatsapp  # noqa: E402
from app.seguranca import buscar_usuario  # noqa: E402


async def main():
    await db.init()
    try:
        agente.configurar(await db.listar_etapas())
        wa_id = sys.argv[1] if len(sys.argv) > 1 else None
        if wa_id is None:
            async with db.pool.acquire() as con:
                wa_id = await con.fetchval("select wa_id from agente.vw_usuarios_ativos "
                                           "where perfil = 'interno' limit 1")
        usuario = await buscar_usuario(wa_id) if wa_id else None
        if usuario is None:
            print("Número não cadastrado ou inativo em agente.usuarios.")
            return
        print(f"Conversando como {usuario.nome} ({usuario.perfil}). 'sair' para encerrar.\n")
        loop = asyncio.get_running_loop()
        while True:
            texto = (await loop.run_in_executor(None, input, "você> ")).strip()
            if texto.lower() in ("sair", "exit", "quit"):
                break
            if texto:
                print("\nagente>\n" + para_whatsapp(await agente.responder(usuario, texto[:500])) + "\n")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
