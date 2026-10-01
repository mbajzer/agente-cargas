"""Funções puras: normalização de identificadores e formatação de cargas para o WhatsApp.

O código faz aqui o que o LLM faz mal (datas, contas com dias, rótulos). O LLM só redige.
"""
import re
from collections.abc import Mapping
from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Sao_Paulo")
DIAS_SEMANA = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
               "sexta-feira", "sábado", "domingo"]

# Situação derivada das datas do processo (coluna `situacao` de agente.vw_cargas).
# Sem emojis nos dados enviados ao LLM: ele os repete em cada linha das listas, e as
# cores do canal acabam parecendo escala de gravidade. Emojis só nos templates fixos.
SITUACOES = {
    "pre_embarque": "Pré-embarque (ainda não embarcou na origem)",
    "em_transito": "Em trânsito marítimo",
    "chegou": "Chegou ao Brasil, em desembaraço",
    "liberada": "Desembaraçada, aguardando entrega",
    "entregue": "Entregue ao cliente",
    "finalizada": "Processo finalizado",
}
CANAIS = {"verde": "Verde", "amarelo": "Amarelo", "vermelho": "Vermelho", "cinza": "Cinza"}
EMOJI_CANAL = {"Verde": " 🟢", "Amarelo": " 🟡", "Vermelho": " 🔴", "Cinza": " ⚪"}


def hoje_br() -> date:
    return datetime.now(TZ).date()


def normalizar_identificador(txt: str | None) -> str:
    """'ja-0987' / 'JA 0987' / 'JA0987' -> 'JA0987' (mesma regra de agente.norm no banco)."""
    return re.sub(r"[^A-Z0-9]", "", (txt or "").upper())


_RE_ID = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9\-/.]{2,29}|[A-Za-z]{1,6}\s+\d{2,12})$")


def parece_identificador(texto: str) -> bool:
    """Mensagem que é só um código (ex.: 'JA-0987', 'ja 0987', BL ou contêiner): dispensa o LLM."""
    t = texto.strip()
    return bool(_RE_ID.match(t)) and any(ch.isdigit() for ch in t)


def br(valor) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.astimezone(TZ).strftime("%d/%m/%Y %H:%M")
    return valor.strftime("%d/%m/%Y")


def _canal(valor: str | None) -> str | None:
    if not valor:
        return None
    return CANAIS.get(valor.strip().lower(), valor)


def formatar_carga(r: Mapping, hoje: date) -> dict:
    """Linha de agente.vw_cargas -> dicionário enxuto em PT-BR (sem campos vazios)."""
    situacao = r.get("situacao")
    eta, chegada, embarque = r.get("eta"), r.get("data_chegada"), r.get("data_embarque")
    containers = r.get("container_numbers") or []
    ref = r.get("referencia_embarque")

    d = {
        "codigo": r.get("reference_code"),
        "referencia_embarque": ref if normalizar_identificador(ref) != normalizar_identificador(r.get("reference_code")) else None,
        "cliente": r.get("cliente"),
        "situacao": SITUACOES.get(situacao, situacao),
        "etapa_atual": f'{r["etapa_ordem"]}. {r["etapa_nome"]}' if r.get("etapa_ordem") else None,
        "na_etapa_desde": br(r.get("etapa_desde")),
        "importadora": r.get("importadora"),
        "exportadora": r.get("exportadora"),
        "agente_cargas": r.get("agente_cargas"),
        "categoria": r.get("categoria"),
        "navio": r.get("navio"),
        "porto": r.get("porto"),
        "bl": r.get("bl_number"),
        "containers": ", ".join(containers) if containers else None,
        "data_embarque": br(embarque),
        "dias_em_transito": ((chegada or hoje) - embarque).days if embarque else None,
        "chegou_em": br(chegada),
        "regime": r.get("regime"),
        "canal_duimp": _canal(r.get("canal_duimp")),
        "canal_dta": _canal(r.get("canal_dta")),
        "numero_duimp": r.get("numero_duimp"),
        "numero_dta": r.get("numero_dta"),
        "local_dta": r.get("local_dta"),
        "desembaracada_em": br(r.get("data_liberacao_duimp")),
        "bloqueio": {"bloqueada": "Bloqueada", "liberada": "Liberada"}.get(r.get("bloqueio")),
        "transportadora": r.get("transportadora"),
        "entregue_em": br(r.get("data_entrega")),
        "dados_atualizados_em": br(r.get("atualizado_em")),
    }

    if eta and not chegada and situacao in ("pre_embarque", "em_transito"):
        d["previsao_chegada"] = br(eta)
        dias = (eta - hoje).days
        if dias >= 0:
            d["dias_para_chegada"] = dias
        else:
            d["previsao_vencida_ha_dias"] = -dias  # ETA passou e a chegada não foi registrada

    # Demurrage: mesma regra do campo calculado contagem_demurrage (etapa 6)
    limite = r.get("data_limite_demurrage")
    if limite and situacao in ("chegou", "liberada", "entregue"):
        devolucao = r.get("data_entrega_container")
        d["prazo_demurrage"] = br(limite)
        if devolucao:
            d["container_devolvido_em"] = br(devolucao)
            d["saldo_dias_demurrage_na_devolucao"] = (limite - devolucao).days  # negativo = dias cobrados
        elif situacao != "entregue":
            d["dias_para_demurrage"] = (limite - hoje).days  # negativo = já em demurrage

    return {k: v for k, v in d.items() if v not in (None, "")}


def resumo_carga(r: Mapping, hoje: date) -> dict:
    """Versão curta para listas (economiza tokens)."""
    c = formatar_carga(r, hoje)
    chaves = ("codigo", "cliente", "situacao", "etapa_atual", "navio", "previsao_chegada",
              "dias_para_chegada", "previsao_vencida_ha_dias", "chegou_em", "canal_duimp",
              "dias_para_demurrage")
    return {k: c[k] for k in chaves if k in c}


def template_carga(c: dict) -> str:
    """Resposta determinística (sem LLM) para consulta direta por código."""
    linhas = [f"📦 *Carga {c['codigo']}*"]
    if c.get("cliente"):
        linhas.append(f"*Cliente:* {c['cliente']}")
    linhas.append(f"*Situação:* {c['situacao']}")
    if c.get("etapa_atual"):
        desde = f" (desde {c['na_etapa_desde'][:10]})" if c.get("na_etapa_desde") else ""
        linhas.append(f"*Etapa:* {c['etapa_atual']}{desde}")
    if c.get("navio") or c.get("porto"):
        linhas.append(f"*Navio/Porto:* {c.get('navio', '—')} / {c.get('porto', '—')}")
    if c.get("previsao_chegada"):
        if "dias_para_chegada" in c:
            extra = f" (em {c['dias_para_chegada']} dias)" if c["dias_para_chegada"] else " (hoje)"
        else:
            extra = " (vencida, aguardando atualização)"
        linhas.append(f"*Previsão de chegada:* {c['previsao_chegada']}{extra}")
    if c.get("chegou_em"):
        linhas.append(f"*Chegou em:* {c['chegou_em']}")
    if c.get("canal_duimp"):
        linhas.append(f"*Canal DUIMP:* {c['canal_duimp']}{EMOJI_CANAL.get(c['canal_duimp'], '')}")
    elif c.get("canal_dta"):
        linhas.append(f"*Canal DTA:* {c['canal_dta']}{EMOJI_CANAL.get(c['canal_dta'], '')}")
    if c.get("bloqueio") == "Bloqueada":
        linhas.append("*Atenção:* carga bloqueada ⚠️")
    if "dias_para_demurrage" in c:
        n = c["dias_para_demurrage"]
        txt = f"{n} dias" if n >= 0 else f"em demurrage há {-n} dias ⚠️"
        linhas.append(f"*Demurrage:* {c['prazo_demurrage']} ({txt})")
    if c.get("entregue_em"):
        linhas.append(f"*Entregue em:* {c['entregue_em']}")
    if c.get("dados_atualizados_em"):
        linhas.append(f"_Atualizado em {c['dados_atualizados_em']}_")
    return "\n".join(linhas)


def template_candidatos(candidatos: list[dict]) -> str:
    linhas = ["Encontrei mais de uma carga parecida. Qual delas?"]
    linhas += [f"• *{c['codigo']}*: {c['situacao']}" for c in candidatos]
    return "\n".join(linhas)


def para_whatsapp(texto: str) -> str:
    """Converte markdown residual do LLM para a sintaxe do WhatsApp."""
    texto = re.sub(r"\*\*(.+?)\*\*", r"*\1*", texto)        # **negrito** -> *negrito*
    texto = re.sub(r"^#{1,6}\s*", "", texto, flags=re.M)     # remove títulos
    texto = re.sub(r"^\s*[-•]\s+", "• ", texto, flags=re.M)  # padroniza bullets
    return texto.strip()[:4096]
