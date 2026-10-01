import json
import logging
import os
from pathlib import Path

import anthropic

from app import db
from app.ferramentas import executar_ferramenta, montar_tools, resolver_carga
from app.formatacao import (DIAS_SEMANA, formatar_carga, hoje_br, parece_identificador,
                            resumo_carga, template_candidatos, template_carga)

log = logging.getLogger("agente")
client = anthropic.AsyncAnthropic()
MODEL = os.environ.get("AGENTE_MODEL", "claude-haiku-4-5")
SYSTEM_ESTATICO = (Path(__file__).parent.parent / "prompts" / "system.md").read_text(encoding="utf-8")
SAUDACOES = {"oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "obrigado", "obrigada", "valeu", "ok"}
MSG_INDISPONIVEL = "O assistente está indisponível no momento. Tente novamente em alguns minutos."

TOOLS: list[dict] = []


def configurar(etapas: list):
    """Chamado no startup: as descrições das ferramentas trazem as etapas reais do kanban.
    A lista fica fixa durante a execução, o que mantém o prefixo estável para o prompt caching."""
    global TOOLS
    TOOLS = montar_tools(etapas)


async def responder(usuario, texto: str) -> str:
    hoje = hoje_br()

    # --- Roteador sem LLM (custo zero) ---
    t = texto.lower().strip(" !.?")
    if t in SAUDACOES:
        return (f"Olá, {usuario.nome.split()[0]}! Posso informar etapa, previsão de chegada, canal e "
                "demurrage das cargas. Ex.: *Qual a previsão da LIN023?* ou *Quantas cargas estão no mar?*")
    if parece_identificador(texto):
        rows = await resolver_carga(usuario.wa_id, texto)
        if len(rows) == 1:
            return template_carga(formatar_carga(rows[0], hoje))
        if len(rows) > 1:
            return template_candidatos([resumo_carga(r, hoje) for r in rows])
        # nada encontrado: segue para o LLM, que pode ter entendido outra coisa

    # --- Loop do agente ---
    contexto = (f"Hoje: {hoje:%d/%m/%Y} ({DIAS_SEMANA[hoje.weekday()]}). "
                f"Usuário: {usuario.nome} (perfil: {usuario.perfil}).")
    if usuario.perfil == "cliente":
        contexto += f" Cliente(s) vinculado(s): {', '.join(usuario.clientes)}."
    system = [
        # O marcador de cache só tem efeito quando tools + prompt estático passam do mínimo
        # cacheável do modelo (4096 tokens no Haiku 4.5); abaixo disso é ignorado sem erro.
        {"type": "text", "text": SYSTEM_ESTATICO, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": contexto},
    ]
    messages = await carregar_historico(usuario.wa_id) + [{"role": "user", "content": texto}]

    try:
        for _ in range(4):  # teto de iterações = teto de custo por pergunta
            resp = await client.messages.create(model=MODEL, max_tokens=1024, system=system,
                                                tools=TOOLS, messages=messages)
            if resp.stop_reason != "tool_use":
                final = "".join(b.text for b in resp.content if b.type == "text").strip()
                if not final:
                    return "Não consegui gerar uma resposta. Pode reformular a pergunta?"
                await salvar_turno(usuario.wa_id, texto, final)
                return final

            messages.append({"role": "assistant", "content": resp.content})
            resultados = []
            for b in resp.content:
                if b.type != "tool_use":
                    continue
                try:
                    out = await executar_ferramenta(b.name, b.input, usuario, hoje)
                except Exception:
                    log.exception("ferramenta %s falhou", b.name)
                    resultados.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                                       "content": "Falha ao consultar o sistema operacional."})
                    continue
                await auditar(usuario.wa_id, b.name, b.input, out)
                resultados.append({"type": "tool_result", "tool_use_id": b.id,
                                   "content": json.dumps(out, ensure_ascii=False, default=str)})
            messages.append({"role": "user", "content": resultados})  # todos os resultados juntos
    except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError):
        log.warning("API da Anthropic indisponível", exc_info=True)
        return MSG_INDISPONIVEL

    return "Sua pergunta ficou complexa demais para mim. Pode dividi-la em partes menores?"


# Histórico e auditoria são acessórios: se falharem, registra no log e segue,
# sem perder a resposta que o usuário já vai receber.

async def carregar_historico(wa_id: str, max_msgs: int = 6) -> list[dict]:
    """Só texto (sem tool_results) dos últimos 30 min: contexto para 'e a outra?' a custo baixo."""
    try:
        async with db.pool.acquire() as con:
            rows = await con.fetch("""
                select role, conteudo from agente.historico
                where wa_id = $1 and criado_em > now() - interval '30 minutes'
                order by id desc limit $2""", wa_id, max_msgs)
    except Exception:
        log.exception("falha ao ler histórico")
        return []
    hist = [{"role": r["role"], "content": r["conteudo"]} for r in reversed(rows)]
    while hist and hist[0]["role"] != "user":  # a conversa precisa começar pelo usuário
        hist.pop(0)
    return hist


async def salvar_turno(wa_id: str, pergunta: str, resposta: str):
    try:
        async with db.pool.acquire() as con:
            await con.executemany("insert into agente.historico (wa_id, role, conteudo) values ($1, $2, $3)",
                                  [(wa_id, "user", pergunta), (wa_id, "assistant", resposta)])
    except Exception:
        log.exception("falha ao salvar histórico")


async def auditar(wa_id: str, ferramenta: str, params: dict, out: dict):
    if "carga" in out:
        qtd = 1
    else:
        qtd = out.get("total", out.get("quantidade", out.get("total_em_andamento",
                      len(out.get("candidatas", out.get("etapas", [])))))) or 0
    try:
        async with db.pool.acquire() as con:
            await con.execute("insert into agente.auditoria (wa_id, ferramenta, parametros, qtd_resultados) "
                              "values ($1, $2, $3::jsonb, $4)",
                              wa_id, ferramenta, json.dumps(params, ensure_ascii=False), qtd)
    except Exception:
        log.exception("falha ao gravar auditoria")
