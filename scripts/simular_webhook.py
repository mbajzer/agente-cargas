"""Simula a Twilio chamando o webhook do agente com uma mensagem de WhatsApp assinada.

Uso (na raiz do projeto, com o .env preenchido):
    .venv\\Scripts\\python -m scripts.simular_webhook http://127.0.0.1:8000 "LIN023"
    .venv\\Scripts\\python -m scripts.simular_webhook https://agente-whatsapp.onrender.com "oi"

A assinatura é calculada sobre TWILIO_WEBHOOK_URL (a URL que o servidor valida), mesmo quando
a requisição vai para outro endereço (ex.: servidor local). Use TWILIO_AUTH_TOKEN e
TWILIO_WEBHOOK_URL iguais aos do servidor testado.
O remetente é o primeiro usuário interno ativo (ou WA_ID_TESTE). A resposta do agente é enviada
de verdade pela Twilio: com credenciais reais, ela chega no WhatsApp desse número.
"""
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
from twilio.request_validator import RequestValidator

from scripts.chat_local import carregar_env

carregar_env(Path(__file__).resolve().parent.parent / ".env")


async def wa_id_teste() -> str:
    if os.environ.get("WA_ID_TESTE"):
        return os.environ["WA_ID_TESTE"]
    import asyncpg
    con = await asyncpg.connect(os.environ["AGENTE_DB_URL"], statement_cache_size=0)
    try:
        return await con.fetchval("select wa_id from agente.vw_usuarios_ativos where perfil = 'interno' limit 1")
    finally:
        await con.close()


async def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    texto = sys.argv[2] if len(sys.argv) > 2 else "LIN023"
    wa_id = await wa_id_teste()
    para = os.environ["TWILIO_WHATSAPP_FROM"]
    params = {
        "AccountSid": os.environ["TWILIO_ACCOUNT_SID"],
        "MessageSid": f"SMsimulado{int(time.time() * 1000)}",
        "From": f"whatsapp:+{wa_id}",
        "To": para if para.startswith("whatsapp:") else f"whatsapp:{para}",
        "WaId": wa_id, "ProfileName": "Teste", "Body": texto, "NumMedia": "0",
    }
    validador = RequestValidator(os.environ["TWILIO_AUTH_TOKEN"])
    assinatura = validador.compute_signature(os.environ["TWILIO_WEBHOOK_URL"], params)

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{base}/health")
        print(f"GET  /health                         -> {r.status_code} {r.text}  (esperado 200)")
        r = await c.post(f"{base}/webhook", data=params, headers={"X-Twilio-Signature": "invalida"})
        print(f"POST /webhook (assinatura inválida)  -> {r.status_code}  (esperado 403)")
        r = await c.post(f"{base}/webhook", data=params, headers={"X-Twilio-Signature": assinatura})
        print(f"POST /webhook (mensagem {texto!r})  -> {r.status_code}  (esperado 200; resposta segue em segundo plano)")
    print("Acompanhe o processamento e o envio no log do servidor.")


if __name__ == "__main__":
    asyncio.run(main())
