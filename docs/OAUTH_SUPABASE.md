# OAuth do conector MCP com Supabase Auth

O Claude (conector personalizado) só aceita servidores MCP com OAuth. O servidor MCP (`app.mcp_main`)
valida os tokens emitidos pelo Supabase Auth do projeto da AGT; quem entra é sempre um usuário já
existente no Supabase e cadastrado em `agente.usuarios`.

```
Claude ──> /mcp (401 + metadata) ──> Supabase Auth (login + consentimento) ──> token
Claude ──> /mcp com Bearer ──> servidor valida o JWT ──> sub -> agente.usuarios -> escopo (interno/cliente)
```

## Estado atual do projeto (verificado em 30/09/2026)
- OAuth server do Supabase: **desativado** (`feature_disabled`).
- Chave de assinatura JWT: **legada HS256** (JWKS vazio). O servidor MCP valida por chave pública,
  então precisa de ES256/RS256.

## Passos no painel do Supabase (projeto `kdxuizmrcormppkhjdyc`)
1. **Authentication > JWT Signing Keys**: criar uma chave **ES256** e torná-la a chave atual
   (rotação). A migração é suportada sem derrubar sessões, mas é o projeto de produção do Luveo:
   avise quem mantém o app do Luveo e faça fora do horário de pico.
2. **Authentication > OAuth Server**: ativar, ligar **Allow dynamic client registration**
   (o Claude se registra sozinho) e definir o **Authorization Path** (ex.: `/oauth/consent`).
3. O Supabase redireciona o usuário para **Site URL + Authorization Path**
   (Authentication > URL Configuration). Se o Site URL for o app do Luveo, **a página de
   consentimento precisa existir no frontend do Luveo**. Ver abaixo.

## Página de consentimento (frontend do Luveo)
Rota `/oauth/consent?authorization_id=...`:
1. Se não houver sessão, enviar para o login preservando `authorization_id`.
2. `supabase.auth.oauth.getAuthorizationDetails(authorization_id)` e mostrar cliente e escopos.
3. Botões Aprovar/Negar: `approveAuthorization(authorization_id)` / `denyAuthorization(authorization_id)`;
   redirecionar para a URL devolvida.
Referência: https://supabase.com/docs/guides/auth/oauth-server/getting-started

## Banco
Rodar `sql/007_usuarios_auth.sql` (view `agente.vw_usuarios_auth`).
Cada pessoa que usar o conector precisa de uma linha **ativa** em `agente.usuarios` com
`profile_id` preenchido (o `profiles.id` dela), `perfil` (`interno` ou `cliente`) e, para cliente, a
lista `clientes`. `wa_id` é obrigatório na tabela: sem WhatsApp, use um identificador único
(ex.: `mcp:email@empresa.com`). Quem autenticar mas não estiver cadastrado recebe
"Seu usuário não tem acesso ao conector".

## Variáveis do servidor (Render)
`AGENTE_DB_URL`, `SUPABASE_URL`, `MCP_PUBLIC_URL` (URL pública do serviço, sem `/mcp`),
`SUPABASE_JWT_ALG` (`ES256` ou `RS256`).

## Conectar no Claude
Configurações > Conectores > Adicionar conector personalizado > `https://<MCP_PUBLIC_URL>/mcp`.
O navegador abre o login/consentimento do Luveo.

## Ressalvas
- O Supabase não suporta audiência por recurso (RFC 8707): um token válido do projeto, inclusive
  de sessão do app do Luveo, passa na verificação de assinatura. O acesso continua limitado a quem
  está em `agente.usuarios` e ao escopo dessa pessoa.
- Dynamic registration permite que qualquer cliente MCP se registre; o usuário aprova cada um na tela
  de consentimento. Revise os clientes registrados periodicamente.
- Teste local sem Supabase: não defina `SUPABASE_URL`; use `MCP_TOKEN` + `MCP_WA_ID`.
