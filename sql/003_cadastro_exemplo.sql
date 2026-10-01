-- Exemplos de cadastro de usuários do agente (ajuste antes de rodar).

-- Funcionário: vê todas as cargas não arquivadas. O vínculo com profiles
-- faz o acesso cair automaticamente quando o usuário é desativado no sistema.
insert into agente.usuarios (wa_id, nome, perfil, profile_id)
select '5511999998888', p.nome, 'interno', p.id
from public.profiles p
where p.email = 'funcionario@agt.com.br';

-- Cliente: vê apenas cargas cujo "Cliente Principal" (etapa 2) seja um dos nomes abaixo.
-- Use os nomes exatamente como aparecem na consulta 4 do 002_validacao.sql.
-- Um mesmo cliente pode ter várias contas no campo (ex.: JACK, JACK (CBP), JACK (XQSY)...):
-- liste todas as que ele pode ver.
insert into agente.usuarios (wa_id, nome, perfil, clientes)
values ('5547988887777', 'Jack', 'cliente',
        array['JACK', 'JACK (CBP)', 'JACK (XQSY)', 'JACK (MT)', 'JACK (RYG)', 'JACK (XDU)',
              'JACK (BF)', 'JACK (RBZY)', 'JACK (SHKJ)']);

-- Revogar acesso
-- update agente.usuarios set ativo = false where wa_id = '5547988887777';
