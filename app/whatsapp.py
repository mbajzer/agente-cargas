"""Envio de mensagens de WhatsApp pela Twilio (Programmable Messaging)."""
import asyncio
import os

from twilio.rest import Client

LIMITE_TWILIO = 1600  # caracteres por mensagem; respostas maiores são divididas

_client: Client | None = None


def remetente() -> str:
    """TWILIO_WHATSAPP_FROM aceita '+14155238886' ou 'whatsapp:+14155238886'."""
    numero = os.environ["TWILIO_WHATSAPP_FROM"].strip()
    return numero if numero.startswith("whatsapp:") else f"whatsapp:{numero}"


def _cliente() -> Client:
    global _client
    if _client is None:
        _client = Client(os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"])
    return _client


def dividir(texto: str, limite: int = LIMITE_TWILIO) -> list[str]:
    """Quebra em partes de até `limite` caracteres, preferindo o fim das linhas."""
    partes, atual = [], ""
    for linha in texto.split("\n"):
        while len(linha) > limite:  # linha sozinha maior que o limite
            if atual:
                partes.append(atual)
                atual = ""
            partes.append(linha[:limite])
            linha = linha[limite:]
        candidato = f"{atual}\n{linha}" if atual else linha
        if len(candidato) > limite:
            partes.append(atual)
            atual = linha
        else:
            atual = candidato
    if atual.strip():
        partes.append(atual)
    return partes or [""]


async def enviar_texto(para_wa_id: str, texto: str):
    """Envia para o WaId (só dígitos, ex.: 5521987654321). Erros da Twilio sobem como
    TwilioRestException, com o código no texto (ex.: 63015 = destinatário fora do sandbox)."""
    destino = f"whatsapp:+{para_wa_id.lstrip('+')}"
    for parte in dividir(texto):
        # o SDK é síncrono: roda em thread para não travar o servidor
        await asyncio.to_thread(_cliente().messages.create, from_=remetente(), to=destino, body=parte)
