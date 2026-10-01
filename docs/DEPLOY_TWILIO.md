# WhatsApp via Twilio: sandbox, deploy no Render e número definitivo

Duas fases:

| Fase | Para quê | Login no Facebook |
|---|---|---|
| **1. Sandbox** | Piloto interno: o agente responde pelo número compartilhado da Twilio (+1 415 523 8886) | **Não precisa** |
| **2. Número definitivo** | Clientes e equipe usando o número da AGT com o nome "AGT Trading" | **Uma vez**, de quem administra a conta da AGT na Meta (exigência da Meta no cadastro do número) |

O código é o mesmo nas duas fases; muda só `TWILIO_WHATSAPP_FROM` e onde o webhook é cadastrado.

---

## Fase 1: sandbox (sem Facebook)

### 1.1 Conta na Twilio
1. Crie a conta em **twilio.com/try-twilio** (e-mail e telefone; não usa Facebook).
2. No **Console**, em **Account Info**, copie para o `.env`:
   - **Account SID** → `TWILIO_ACCOUNT_SID`
   - **Auth Token** → `TWILIO_AUTH_TOKEN`
3. `TWILIO_WHATSAPP_FROM=+14155238886` (número do sandbox).

### 1.2 Entrar no sandbox pelo celular
1. Console → **Messaging → Try it out → Send a WhatsApp message**.
2. A página mostra um código (ex.: `join palavra-palavra`). Do seu WhatsApp, envie essa mensagem para **+1 415 523 8886**.
3. Cada pessoa que for testar faz o mesmo. **A participação expira 3 dias depois**: para continuar, envie o `join` de novo.
4. Essas pessoas também precisam estar cadastradas em `agente.usuarios` (ver `sql/003_cadastro_exemplo.sql`).

### 1.3 Publicar o código no GitHub
O Render faz deploy a partir de um repositório **privado**. Na pasta do projeto:

```bash
git init -b main
git add .
git status
```

Confira que **`.env`, `Senhas.txt`, `.venv/` e as planilhas não aparecem** (estão no `.gitignore`). Depois:

```bash
git commit -m "Agente de cargas: MCP e WhatsApp via Twilio"
git remote add origin https://github.com/SEU-USUARIO/agente-cargas.git
git push -u origin main
```

### 1.4 Subir o serviço no Render
O `render.yaml` tem dois serviços: `luveo-mcp` (conector do Claude) e **`agente-whatsapp`**.

1. **Primeira vez**: dashboard.render.com → **New → Blueprint** → escolha o repositório.
   **Se o Blueprint já existe** (por causa do `luveo-mcp`): abra o Blueprint → **Manual sync**; o Render cria o `agente-whatsapp`.
2. Preencha as variáveis secretas do `agente-whatsapp`:

   | Variável | Valor |
   |---|---|
   | `AGENTE_DB_URL` | igual ao `.env` (role `agente_app`, porta 6543, `@` da senha como `%40`) |
   | `ANTHROPIC_API_KEY` | |
   | `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | passo 1.1 |
   | `TWILIO_WHATSAPP_FROM` | `+14155238886` |
   | `TWILIO_WEBHOOK_URL` | `https://agente-whatsapp.onrender.com/webhook`: **use a URL exata que o Render mostrar** no topo do serviço (ele acrescenta um sufixo se o nome já existir) |

3. Aguarde o status **Live** e abra `https://.../health` → `{"ok":true}`.
4. Atualize `TWILIO_WEBHOOK_URL` no seu `.env` com a mesma URL e valide do seu computador:

   ```bash
   .venv/Scripts/python -m scripts.simular_webhook https://agente-whatsapp.onrender.com "LIN023"
   ```

   Esperado: `200`, `403`, `200`, e **o cartão da LIN023 chega no seu WhatsApp** pelo número do sandbox.

### 1.5 Ligar o sandbox ao servidor
1. Console → **Messaging → Try it out → Send a WhatsApp message → Sandbox settings**.
2. **When a message comes in**: a mesma URL de `TWILIO_WEBHOOK_URL`, método **POST**. **Save**.
3. Do celular, mande para o sandbox: `oi`, `Quantas cargas estão no mar?`, `LIN023`, `E qual o navio dela?`.

---

## Fase 2: número definitivo da AGT

Pré-requisito: alguém com acesso de administrador à conta da AGT na Meta (portfólio empresarial), ou disposto a criá-la, para **um login no Facebook** durante o cadastro. Depois disso ninguém precisa entrar na Meta para o agente funcionar.

1. **Ative o faturamento** da conta Twilio (sai do trial).
2. **Número**:
   - número próprio da AGT que **não esteja ativo** no app WhatsApp/WhatsApp Business (apague a conta no celular antes), capaz de receber SMS ou ligação; ou
   - número comprado na Twilio (números brasileiros exigem cadastro regulatório na Twilio).
3. Console → **Messaging → Senders → WhatsApp senders → Create new sender** (*Self Sign-up*):
   1. Login com o Facebook do administrador;
   2. Selecionar (ou criar) o portfólio empresarial da AGT;
   3. Criar a conta do WhatsApp Business e o **nome de exibição** (ex.: `AGT Trading`), que a Meta revisa;
   4. Confirmar o número por SMS ou ligação;
   5. Aceitar as permissões da Twilio.
4. Se o portfólio for novo: **verificação da empresa** na Meta (documentos da AGT). Sem ela, os limites ficam baixos.
5. No sender criado, cadastre o webhook de mensagens recebidas: a mesma `TWILIO_WEBHOOK_URL` (POST).
6. No Render, troque `TWILIO_WHATSAPP_FROM` pelo novo número (ex.: `+5521...`). O serviço reinicia sozinho.

**Custos**: a Twilio cobra uma taxa por mensagem enviada e recebida, mais as tarifas da Meta. Responder a quem escreveu (janela de 24 h) não paga tarifa da Meta. Valores atuais em twilio.com/whatsapp/pricing. Some o Render (~US$ 7/mês por serviço) e a Anthropic (~US$ 0,008 por pergunta).

---

## Solução de problemas

Os erros da Twilio aparecem em **Console → Monitor → Logs → Errors** e no log do Render.

| Sintoma | Causa provável / correção |
|---|---|
| Deploy falha com `Variáveis de ambiente obrigatórias vazias: ...` | Preencher as variáveis listadas |
| `POST /webhook 403` no Render; erro **11200** na Twilio | `TWILIO_WEBHOOK_URL` diferente da URL cadastrada na Twilio (http × https, barra no final, nome do serviço) ou `TWILIO_AUTH_TOKEN` errado |
| Nenhum `POST /webhook` no Render | URL não salva no *Sandbox settings* (ou no sender, na fase 2); serviço fora do ar (`/health`) |
| Log com **63015** | Destinatário não entrou no sandbox ou a participação expirou: enviar o `join` de novo |
| Log com **20003** | `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN` errados |
| Log com **63016** | Mensagem fora da janela de 24 h (só ocorre se o agente iniciar conversa) |
| Resposta "este número não está autorizado" | Cadastrar o número ou ajustar o formato: `select wa_id, max(recebido_em) from agente.mensagens group by 1 order by 2 desc;` (números brasileiros às vezes chegam sem o 9º dígito) |
| Resposta "O assistente está indisponível" | Falha ou limite na API da Anthropic: conferir chave e créditos |
| Erro de conexão com o banco | `AGENTE_DB_URL` diferente do `.env`; porta 6543; se o Supabase tiver *Network Restrictions*, liberar os IPs de saída do Render |

---

## Checklist de segurança

- [ ] `.env` e `Senhas.txt` fora do Git; repositório **privado**
- [ ] `TWILIO_AUTH_TOKEN` só no Render e no `.env`; se vazar, gere outro em Console → Account → API keys & tokens (*Request a secondary token* → promover) e atualize o Render
- [ ] Senha da `agente_app` forte e diferente da do `postgres`
- [ ] Acessos revisados: `select wa_id, nome, perfil, ativo from agente.usuarios;`
- [ ] Limite de gasto configurado na Anthropic e alertas de uso na Twilio (*Usage triggers*)
