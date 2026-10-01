from datetime import date, datetime, timezone

import pytest

from app.formatacao import (formatar_carga, normalizar_identificador, para_whatsapp,
                            parece_identificador, template_carga)

HOJE = date(2026, 9, 24)


def carga(**kw):
    base = {"reference_code": "JA-0987", "situacao": "em_transito", "etapa_ordem": 6,
            "etapa_nome": "Acompanhamento de Carga, Datas e Prazos", "navio": "MSC AURORA",
            "porto": "SANTOS", "data_embarque": date(2026, 9, 1), "eta": date(2026, 10, 14),
            "atualizado_em": datetime(2026, 9, 24, 11, 15, tzinfo=timezone.utc)}
    base.update(kw)
    return base


@pytest.mark.parametrize("entrada", ["JA-0987", "ja 0987", "ja0987", " JA - 0987 "])
def test_normalizar_identificador(entrada):
    assert normalizar_identificador(entrada) == "JA0987"


@pytest.mark.parametrize("texto,esperado", [
    ("JA-0987", True), ("ja 0987", True), ("MSCU1234567", True), ("MEDUXY123456", True),
    # formatos reais da AGT
    ("LIN023", True), ("lin 23", True), ("JA-ST001", True), ("YC-CBP012", True),
    ("UNI26060104", True), ("TGBU6285400/EMCEXV6045", True),
    ("oi", False), ("bom dia", False), ("quantas cargas estão no mar?", False),
    ("qual a previsão da JA-0987?", False), ("ABCDEF", False),
])
def test_parece_identificador(texto, esperado):
    assert parece_identificador(texto) is esperado


def test_em_transito_calcula_dias_para_chegada():
    c = formatar_carga(carga(), HOJE)
    assert c["previsao_chegada"] == "14/10/2026"
    assert c["dias_para_chegada"] == 20
    assert c["dias_em_transito"] == 23
    assert c["dados_atualizados_em"] == "24/09/2026 08:15"  # convertido para America/Sao_Paulo
    assert "prazo_demurrage" not in c


def test_eta_vencida_sem_chegada():
    c = formatar_carga(carga(eta=date(2026, 9, 20)), HOJE)
    assert c["previsao_vencida_ha_dias"] == 4
    assert "dias_para_chegada" not in c


def test_chegou_mostra_demurrage_e_esconde_previsao():
    c = formatar_carga(carga(situacao="chegou", data_chegada=date(2026, 9, 10),
                             data_limite_demurrage=date(2026, 9, 29)), HOJE)
    assert "previsao_chegada" not in c
    assert c["chegou_em"] == "10/09/2026"
    assert c["dias_em_transito"] == 9          # trava na chegada
    assert c["dias_para_demurrage"] == 5


def test_demurrage_vencida_fica_negativa():
    c = formatar_carga(carga(situacao="chegou", data_chegada=date(2026, 9, 1),
                             data_limite_demurrage=date(2026, 9, 20)), HOJE)
    assert c["dias_para_demurrage"] == -4
    assert "em demurrage há 4 dias" in template_carga(c)


def test_demurrage_congela_na_devolucao_do_container():
    c = formatar_carga(carga(situacao="liberada", data_chegada=date(2026, 9, 1),
                             data_limite_demurrage=date(2026, 9, 20),
                             data_entrega_container=date(2026, 9, 23)), HOJE)
    assert c["saldo_dias_demurrage_na_devolucao"] == -3
    assert "dias_para_demurrage" not in c


def test_referencia_embarque_igual_ao_codigo_e_omitida():
    assert "referencia_embarque" not in formatar_carga(carga(referencia_embarque="ja 0987"), HOJE)
    assert formatar_carga(carga(referencia_embarque="EMB-55"), HOJE)["referencia_embarque"] == "EMB-55"


def test_campos_vazios_sao_removidos():
    c = formatar_carga(carga(navio=None, container_numbers=[], regime=None), HOJE)
    assert "navio" not in c and "containers" not in c and "regime" not in c


def test_canal_rotulado():
    c = formatar_carga(carga(situacao="chegou", data_chegada=date(2026, 9, 10), canal_duimp="AMARELO"), HOJE)
    assert c["canal_duimp"] == "Amarelo"                      # dados para o LLM: sem emoji
    assert "*Canal DUIMP:* Amarelo 🟡" in template_carga(c)  # template fixo: com emoji


def test_template_carga_em_transito():
    txt = template_carga(formatar_carga(carga(), HOJE))
    assert txt.startswith("📦 *Carga JA-0987*")
    assert "*Previsão de chegada:* 14/10/2026 (em 20 dias)" in txt


def test_para_whatsapp():
    assert para_whatsapp("## Título\n**negrito**\n- item") == "Título\n*negrito*\n• item"
