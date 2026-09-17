# 07 — Troubleshooting

Os sintomas abaixo são casos reais, com o diagnóstico que levou à causa em cada um.

## Índice rápido por sintoma

| Sintoma | Causa provável |
|---|---|
| `403` com `"Authentication credentials were not provided."` | token não reconhecido pelo backend que respondeu; comece pelo `KONG_SERVICE_URL` |
| `403` com `"Route not authorized by the gateway"` | o path não está exposto; é a rota de bloqueio respondendo |
| `400 Bad Request` ao criar rota | violação de schema do Kong; leia o corpo da resposta |
| `PruneLimitExceeded` | remoção acima da trava de volume |
| `503` ou falha de resolução de nome | o upstream do service no Kong |
| Erro de escrita na Admin API | Kong em modo sem banco |
| `404` no `get-token` | usuário sem autorização no projeto |
| `200` com HTML em vez de JSON | path do gateway não casou com o endpoint da API |

## `403` com "Authentication credentials were not provided."

Esse é o sintoma mais confuso do gateway, porque a mensagem sugere um problema de
token, e o token pode estar perfeitamente válido.

A raiz da confusão está em como a autenticação trata falhas: o
`SessionTokenAuthentication` devolve `None` em qualquer cenário de falha — token
ausente, inválido, expirado, ou store inacessível. O DRF interpreta isso como "não
autenticado" e responde `403` com essa mensagem. Ou seja, **a mensagem é a mesma
para erro do cliente e para erro de configuração do servidor.**

### Caso real: `KONG_SERVICE_URL` apontando para outro ambiente

Foi o diagnóstico de uma investigação longa. Os sintomas eram:

- o token existia no DynamoDB e o `ValidateSessionTokenUseCase` retornava um
  `SessionContext` normalmente quando executado no shell do serviço em staging;
- a chamada pelo gateway respondia `403`;
- uma chamada direta ao pod do serviço respondia `200`.

A conclusão inicial parecia ser perda do header `Authorization` entre o Kong e o
serviço. Não era. O `KONG_SERVICE_URL` do ambiente de staging estava apontando para
o endereço de **produção**, então o Kong encaminhava a requisição para o backend de
produção, que legitimamente não conhecia um token de staging.

O que confirmou o diagnóstico foi comparar os headers da resposta: os headers de
`content-security-policy` retornados eram os do outro ambiente. A latência de
upstream reportada pelo Kong (`x-kong-upstream-latency` alta, na casa das centenas
de milissegundos) reforçou que o destino não era o serviço local.

### Como investigar, na ordem

1. **Confirme o token no store**, no shell do serviço:

   ```python
   from weni_commons.auth import DynamoDBSessionTokenRepository, ValidateSessionTokenUseCase
   DynamoDBSessionTokenRepository().get("<token>")
   ValidateSessionTokenUseCase().execute("<token>")
   ```

   Se as duas chamadas funcionam, o token e o store estão certos, e o problema não
   está na autenticação em si.

2. **Confirme para onde o Kong está encaminhando:**

   ```python
   from django.conf import settings
   settings.KONG_SERVICE_URL
   ```

   Ele precisa apontar para **este** ambiente. Confirme também no Kong:

   ```bash
   curl -s "${KONG_ADMIN_URL}/services/${KONG_SERVICE}"
   ```

3. **Compare o comportamento por caminho.** Uma chamada direta ao serviço que
   responde `200` e uma chamada pelo gateway que responde `403` indicam que o
   gateway não está entregando no serviço que você está inspecionando.

4. **Olhe os headers de resposta** em busca de pistas de qual ambiente respondeu:
   `content-security-policy`, `x-kong-upstream-latency` e `x-kong-request-id`.

Se o `KONG_SERVICE_URL` estava errado, corrija a secret e rode
`kong_ensure_service` novamente — ele faz o patch da URL do service.

### Outras causas do mesmo `403`

| Causa | Como confirmar |
|---|---|
| Tabela do DynamoDB configurada com ARN em vez de nome | `settings.WENI_SESSION_TOKEN_DYNAMODB_TABLE` deve ser um nome simples |
| Região errada do DynamoDB | o `get()` do repositório retorna `None` para um token que existe |
| Credencial sem permissão de leitura na tabela | o `get()` levanta exceção de acesso, visível no log do serviço |
| Alias de Redis inexistente | o `get()` do repositório funciona, mas o `ValidateSessionTokenUseCase` falha |
| Token expirado | `expire_at` no passado; o item pode até já ter sido apagado pelo TTL |
| Esquema `Token` em vez de `Bearer` | o gateway exige `Bearer`; o esquema `Token` é do fluxo legado |

## `403` com "Route not authorized by the gateway"

Esse `403` é diferente do anterior: ele vem do **Kong**, não do serviço, e significa
que o path não casou com nenhuma rota de liberação e caiu na rota de bloqueio.

Causas comuns:

- o endpoint não tem o decorator `@api_gateway_expose`;
- o endpoint tem o decorator, mas o `kong_sync` ainda não rodou depois do deploy;
- o método HTTP usado não está na lista de `methods` do decorator;
- o path chamado não é um dos três paths registrados (confira com
  `kong_sync --dry-run`).

Para ver o que está registrado:

```bash
curl -s "${KONG_ADMIN_URL}/services/${KONG_SERVICE}/routes"
```

## `400 Bad Request` ao criar ou alterar rota

```text
requests.exceptions.HTTPError: 400 Client Error: Bad Request for url:
http://kong-kong-admin.kong.svc:8001/services/flows-service/routes
```

`400` da Admin API é quase sempre **violação de schema**, e o status por si só não
diz nada. A informação útil está no corpo da resposta, que o comando passou a
incluir na mensagem de erro justamente por causa deste caso.

O caso real: a tag de propriedade das rotas era gerada como `prefix:/flows`, e o
Kong rejeita `:` dentro de tags. O formato foi normalizado para `prefix-flows`. Se
um `400` aparecer hoje, leia o corpo — ele nomeia o campo recusado.

## `PruneLimitExceeded`

```text
prune would delete 7 of 9 managed route(s), above the safety limit of 4:
allow-a, allow-b, ... Re-run with --force-prune to confirm.
```

O comando não apagou nada. Antes de forçar, entenda por que tantas rotas ficaram
órfãs de uma vez, porque a trava existe justamente para pegar descoberta
incompleta:

- a imagem tem um import quebrado que impediu views de serem carregadas;
- o `KONG_URL_PREFIX` está diferente do usado nos syncs anteriores;
- o `KONG_SERVICE` aponta para o service errado;
- o sync rodou com a imagem errada.

Rode `kong_sync --dry-run` e confira a lista. Se as remoções forem legítimas —
vários endpoints realmente foram despublicados na mesma release —, reexecute com
`--force-prune`.

## `503` ou falha de resolução de nome

Erro do Kong ao alcançar o upstream, não do serviço. Verifique se o
`KONG_SERVICE_URL` é resolvível e alcançável de dentro do Kong, e se o serviço está
no ar. Respostas com headers `x-kong-*` mas sem qualquer header do serviço indicam
que o Kong nunca conseguiu falar com o backend.

## Erro de escrita na Admin API

Se a Admin API recusa criar ou apagar recursos de forma consistente, verifique se o
Kong está em **modo com banco**. No modo sem banco a Admin API é somente leitura, e
nem o `kong_ensure_service` nem o `kong_sync` funcionam.

## Avisos do `kong_sync`

### Alias duplicado

```text
WARNING discover_routes: duplicate route name 'allow-contacts' — overwriting
previous registration (was upstream /api/v2/contacts.json)
```

Dois endpoints do mesmo serviço declararam o mesmo alias, e apenas um será exposto
— o último encontrado na varredura das URLs. Escolha aliases distintos.

### Nenhuma rota encontrada

```text
No @api_gateway_expose routes found.
```

A descoberta não achou nada. Confirme que as views decoradas são realmente
alcançadas pelo `ROOT_URLCONF` do serviço, e que o `--suffix` corresponde ao padrão
de URL do projeto (o default é `.json`).

## Problemas na emissão do token

| Status no `get-token` | Significado |
|---|---|
| `401` | token do Keycloak ausente, inválido ou expirado |
| `404` | usuário sem autorização no `project_uuid` informado |
| `400` | `duration` fora do intervalo permitido nas settings do Connect |

## `200` com HTML em vez de JSON

O path chamado não atingiu o endpoint da API, e a resposta é uma página. Confirme o
path público correto no plano do `kong_sync --dry-run` e, quando aplicável, use o
sufixo `.json`, que força a resposta em JSON puro.
