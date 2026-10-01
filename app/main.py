"""Agente de cargas no WhatsApp via Twilio.

    uvicorn app.main:app --port 8000 --env-file .env
Webhook (configurar na Twilio, método POST): /webhook  ·  saúde: /health
"""
import logging
import os
from contextlib import asynccontextmanager
from urllib.parse import parse_qsl

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response
from twilio.request_validator import RequestValidator

from app import agente, db
from app.formatacao import para_whatsapp
from app.seguranca import buscar_usuario, excedeu_limite, registrar_se_nova
from app.whatsapp import enviar_texto

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agente")

LIMITE_POR_HORA = int(os.environ.get("AGENTE_LIMITE_POR_HORA", "30"))

MSG_NAO_CADASTRADO = ("Olá! Este número não está autorizado a consultar cargas da AGT Trading. "
                      "Fale com seu contato comercial para solicitar acesso.")
MSG_ERRO = "Tive um problema técnico ao consultar o sistema. Tente novamente em alguns minutos."
TWIML_VAZIO = "<?xml version='1.0' encoding='UTF-8'?><Response></Response>"

OBRIGATORIAS = ("AGENTE_DB_URL", "ANTHROPIC_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN",
                "TWILIO_WHATSAPP_FROM", "TWILIO_WEBHOOK_URL")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Falha rápido: sem TWILIO_AUTH_TOKEN não há como validar a assinatura das chamadas.
    vazias = [v for v in OBRIGATORIAS if not os.environ.get(v, "").strip()]
    if vazias:
        raise RuntimeError(f"Variáveis de ambiente obrigatórias vazias: {', '.join(vazias)}")
    await db.init()
    agente.configurar(await db.listar_etapas())
    yield
    await db.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/webhook")
async def receber(request: Request, bg: BackgroundTasks):
    corpo = (await request.body()).decode()
    params = dict(parse_qsl(corpo, keep_blank_values=True))  # campos vazios também entram na assinatura

    # A assinatura usa a URL exatamente como configurada na Twilio. Atrás do proxy do Render
    # request.url pode vir como http://, por isso a URL pública vem da variável de ambiente.
    validador = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
    if not validador.validate(os.environ["TWILIO_WEBHOOK_URL"], params,
                              request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(status_code=403)
    if params.get("AccountSid") != os.environ["TWILIO_ACCOUNT_SID"]:
        raise HTTPException(status_code=403)

    if params.get("From", "").startswith("whatsapp:") and params.get("MessageSid"):
        bg.add_task(processar_mensagem, params)
    # Resposta imediata e vazia: o texto do agente segue depois pela API (pode levar ~10 s).
    return Response(content=TWIML_VAZIO, media_type="text/xml")


async def processar_mensagem(p: dict):
    # WaId: só dígitos, no mesmo formato do cadastro (agente.usuarios.wa_id)
    wa_id = p.get("WaId") or p["From"].removeprefix("whatsapp:").lstrip("+")
    try:
        if not await registrar_se_nova(p["MessageSid"], wa_id):
            return  # duplicata (a Twilio reenvia se o webhook falhar)
        usuario = await buscar_usuario(wa_id)
        if usuario is None:
            log.info("número não cadastrado ...%s", wa_id[-4:])
            await enviar_texto(wa_id, MSG_NAO_CADASTRADO)
            return
        texto = (p.get("Body") or "").strip()
        if not texto:  # áudio, imagem, figurinha etc. sem legenda
            await enviar_texto(wa_id, "Por enquanto consigo ler apenas mensagens de texto. 🙂")
            return
        if await excedeu_limite(wa_id, LIMITE_POR_HORA):
            await enviar_texto(wa_id, "Você atingiu o limite de consultas por hora. Tente mais tarde.")
            return

        try:
            resposta = await agente.responder(usuario, texto[:500])
        except Exception:
            log.exception("falha ao responder ...%s", wa_id[-4:])
            resposta = MSG_ERRO
        await enviar_texto(wa_id, para_whatsapp(resposta))
    except Exception:
        log.exception("falha no processamento da mensagem ...%s", wa_id[-4:])
