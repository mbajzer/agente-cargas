"""Webhook da Twilio: assinatura, filtragem e fluxo de processamento (banco, LLM e envio simulados)."""
import os
from urllib.parse import urlencode

import pytest

os.environ.update({
    "TWILIO_ACCOUNT_SID": "AC" + "0" * 32,
    "TWILIO_AUTH_TOKEN": "token-de-teste",
    "TWILIO_WHATSAPP_FROM": "+14155238886",
    "TWILIO_WEBHOOK_URL": "https://agente.exemplo.com/webhook",
    "ANTHROPIC_API_KEY": "teste",
})

from fastapi.testclient import TestClient  # noqa: E402
from twilio.request_validator import RequestValidator  # noqa: E402

from app import main  # noqa: E402
from app.whatsapp import dividir, remetente  # noqa: E402

URL = os.environ["TWILIO_WEBHOOK_URL"]


def form(**extra):
    p = {"AccountSid": os.environ["TWILIO_ACCOUNT_SID"], "MessageSid": "SM" + "1" * 32,
         "From": "whatsapp:+5521987654321", "To": "whatsapp:+14155238886", "WaId": "5521987654321",
         "ProfileName": "Marcos", "Body": "LIN023", "NumMedia": "0"}
    p.update(extra)
    return p


def assinar(p: dict, url: str = URL) -> str:
    return RequestValidator(os.environ["TWILIO_AUTH_TOKEN"]).compute_signature(url, p)


@pytest.fixture
def cenario(monkeypatch):
    """Substitui banco, LLM e envio; devolve o registro das mensagens enviadas."""
    enviados, vistos = [], set()

    async def registrar(msg_id, wa_id):
        novo = msg_id not in vistos
        vistos.add(msg_id)
        return novo

    async def usuario(wa_id):
        return main.agente  # qualquer objeto: o responder abaixo é simulado

    async def responder(u, texto):
        return f"resposta para {texto}"

    async def enviar(wa_id, texto):
        enviados.append((wa_id, texto))

    async def nao(*_):
        return False

    monkeypatch.setattr(main, "registrar_se_nova", registrar)
    monkeypatch.setattr(main, "buscar_usuario", usuario)
    monkeypatch.setattr(main, "excedeu_limite", nao)
    monkeypatch.setattr(main.agente, "responder", responder)
    monkeypatch.setattr(main, "enviar_texto", enviar)
    return enviados


def post(client, p, assinatura):
    return client.post("/webhook", content=urlencode(p),
                       headers={"Content-Type": "application/x-www-form-urlencoded",
                                "X-Twilio-Signature": assinatura})


def test_mensagem_valida_e_respondida(cenario):
    p = form()
    r = post(TestClient(main.app), p, assinar(p))
    assert r.status_code == 200 and "<Response>" in r.text
    assert cenario == [("5521987654321", "resposta para LIN023")]


def test_assinatura_invalida_rejeitada(cenario):
    p = form()
    assert post(TestClient(main.app), p, "assinatura-falsa").status_code == 403
    assert cenario == []


def test_assinatura_de_outra_url_rejeitada(cenario):
    p = form()  # ex.: proxy reescrevendo para http://
    assert post(TestClient(main.app), p, assinar(p, URL.replace("https", "http"))).status_code == 403


def test_conta_twilio_diferente_rejeitada(cenario):
    p = form(AccountSid="AC" + "9" * 32)
    assert post(TestClient(main.app), p, assinar(p)).status_code == 403


def test_mensagem_repetida_processada_uma_vez(cenario):
    p, client = form(), TestClient(main.app)
    post(client, p, assinar(p))
    post(client, p, assinar(p))
    assert len(cenario) == 1


def test_midia_sem_texto_recebe_aviso(cenario):
    p = form(Body="", NumMedia="1", MediaContentType0="audio/ogg")
    post(TestClient(main.app), p, assinar(p))
    assert "apenas mensagens de texto" in cenario[0][1]


def test_sms_no_mesmo_numero_e_ignorado(cenario):
    p = form(From="+5521987654321")
    assert post(TestClient(main.app), p, assinar(p)).status_code == 200
    assert cenario == []


def test_wa_id_sem_campo_waid_vem_do_from(cenario):
    p = form()
    del p["WaId"]
    post(TestClient(main.app), p, assinar(p))
    assert cenario[0][0] == "5521987654321"


def test_dividir_respeita_limite_e_linhas():
    texto = "\n".join(f"linha {i:03d} " + "x" * 50 for i in range(80))  # 80 linhas de 60 caracteres
    partes = dividir(texto)
    assert all(len(p) <= 1600 for p in partes)
    assert [p.count("\n") + 1 for p in partes] == [26, 26, 26, 2]  # 26 linhas cabem em 1.600
    assert "\n".join(partes) == texto  # nada perdido, quebras só entre linhas


def test_dividir_linha_gigante():
    assert [len(p) for p in dividir("a" * 3500)] == [1600, 1600, 300]


def test_remetente_aceita_com_ou_sem_prefixo(monkeypatch):
    assert remetente() == "whatsapp:+14155238886"
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
    assert remetente() == "whatsapp:+14155238886"
