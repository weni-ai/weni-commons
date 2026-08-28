# 05 — Instalação em um serviço

Este guia cobre o que fazer para colocar um serviço novo no gateway. Os valores
concretos de cada ambiente ficam nas secrets do Rancher; aqui está o que cada
variável significa, que formato ela espera e o que quebra quando ela está errada.

## Antes de começar

Três coisas precisam existir do lado da infraestrutura, e nenhuma delas é criada
pelo código deste repositório:

- O **Kong** rodando em modo com banco, com a Admin API alcançável de dentro do
  cluster.
- A **tabela de session tokens no DynamoDB**, e uma credencial que dê ao serviço
  acesso de leitura a ela.
- O **Redis** do serviço, que já costuma existir.

Você também precisa decidir dois nomes, que passam a ser a identidade do serviço
no gateway e não devem mudar depois:

- o **prefixo** do serviço no gateway (`/billing`, por exemplo);
- o **nome do service** no Kong (`billing-service`, por exemplo).

## Passo 1 — Instalar o pacote

```bash
poetry add weni-commons
```

E registrar o app, o que é necessário para o Django encontrar os management
commands:

```python
INSTALLED_APPS = [
    ...
    "weni_commons",
]
```

## Passo 2 — Configurar as settings

O bloco abaixo é a forma recomendada: com tudo em `settings.py`, os comandos rodam
sem nenhuma flag. Cada valor vem de variável de ambiente, que é o que as secrets
do Rancher preenchem.

```python
# Kong API Gateway (weni_commons.kong) — usado por kong_sync e kong_ensure_service
KONG_ADMIN_URL = env.str("KONG_ADMIN_URL")
KONG_URL_PREFIX = env.str("KONG_URL_PREFIX")
KONG_SERVICE = env.str("KONG_SERVICE", default="")  # opcional; /flows → flows-service
KONG_SERVICE_URL = env.str("KONG_SERVICE_URL")

# Session tokens (weni_commons.auth.SessionTokenAuthentication)
WENI_SESSION_TOKEN_DYNAMODB_TABLE = env.str("WENI_SESSION_TOKEN_DYNAMODB_TABLE")
WENI_SESSION_TOKEN_DYNAMODB_REGION = env.str("WENI_SESSION_TOKEN_DYNAMODB_REGION")
WENI_SESSION_TOKEN_MAX_REDIS_TTL = env.int("WENI_SESSION_TOKEN_MAX_REDIS_TTL")
WENI_SESSION_TOKEN_REDIS_ALIAS = env.str("WENI_SESSION_TOKEN_REDIS_ALIAS")

# Autorização por projeto no Connect (weni_commons.auth.ConnectProjectAuthorization)
WENI_CONNECT_API_URL = env.str("WENI_CONNECT_API_URL")
WENI_CONNECT_AUTHORIZATION_TIMEOUT = env.int("WENI_CONNECT_AUTHORIZATION_TIMEOUT")
```

### Variáveis do Kong

| Variável | Formato | Impacto |
|---|---|---|
| `KONG_ADMIN_URL` | URL com esquema, apontando para a Admin API (porta `8001` por convenção). Precisa começar com `http://` ou `https://`, e normalmente é um endereço interno do cluster | É por aqui que os comandos escrevem no Kong. Vazia ou sem esquema, os comandos falham com mensagem explícita. Tem default `http://localhost:8001`, que só serve para desenvolvimento local |
| `KONG_URL_PREFIX` | Caminho começando com `/`, com um único segmento, como `/billing` | Define o prefixo dos paths públicos, o nome da rota de bloqueio (`billing-default-block`) e a tag de propriedade das rotas (`prefix-billing`). Mudar depois de sincronizado deixa as rotas antigas sem a tag correta |
| `KONG_SERVICE` | Nome do service no Kong, como `billing-service`. Opcional | É o alvo do sync e o escopo do prune. Quando vazia, é derivada de `KONG_URL_PREFIX` (`/billing` → `billing-service`). Um valor explícito ganha |
| `KONG_SERVICE_URL` | URL com esquema do serviço, para onde o Kong encaminha as requisições | É o destino real do tráfego. Apontar para o ambiente errado é a falha mais traiçoeira do gateway, porque o Kong responde normalmente, só que vindo do backend errado. Ver [troubleshooting](07-troubleshooting.md) |

### Variáveis do session token

| Variável | Formato | Impacto |
|---|---|---|
| `WENI_SESSION_TOKEN_DYNAMODB_TABLE` | **Nome** da tabela, não o ARN | É a tabela consultada no cache miss. Com ARN no lugar do nome, toda validação falha e o cliente recebe `403` sem explicação. Vazia, o repositório vira no-op e só o Redis é consultado |
| `WENI_SESSION_TOKEN_DYNAMODB_REGION` | Região da AWS, como `sa-east-1` | Precisa ser a região onde a tabela existe. Região errada se comporta como tabela inexistente |
| `WENI_SESSION_TOKEN_MAX_REDIS_TTL` | Inteiro, em segundos | Teto do cache local. Valor alto reduz consultas ao DynamoDB, mas aumenta a janela em que um token invalidado continua aceito; valor baixo faz o oposto |
| `WENI_SESSION_TOKEN_REDIS_ALIAS` | Nome de um alias declarado em `CACHES` | Escolhe qual conexão Redis é usada no cache dos tokens. Alias inexistente faz a validação falhar, e a falha aparece como `403` |

### Variáveis do Connect

Estas duas só são necessárias para quem vai usar o `ConnectProjectAuthorization`.
Um serviço que resolva permissão pelos próprios modelos pode deixá-las de fora.

| Variável | Formato | Impacto |
|---|---|---|
| `WENI_CONNECT_API_URL` | URL base do Connect, com esquema e sem barra final | É onde o papel do usuário é consultado. **Vazia, a permissão nega todas as requisições** — a falha é fechada, não aberta |
| `WENI_CONNECT_AUTHORIZATION_TIMEOUT` | Inteiro, em segundos (default 5) | Tempo limite da consulta ao Connect. Como o timeout ocorre no caminho da requisição, valor alto propaga lentidão do Connect para o serviço; ao estourar, a requisição é negada |

## Passo 3 — Registrar a autenticação

```python
from weni_commons.auth import SessionTokenAuthentication


class MyView(APIView):
    authentication_classes = [SessionTokenAuthentication]
    permission_classes = [IsProjectContributor]
```

Ou globalmente, se o serviço quiser aceitar session token em toda a API:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "weni_commons.auth.SessionTokenAuthentication",
    ],
}
```

Em serviços com autenticação legada, coloque o `SessionTokenAuthentication` na
lista junto com as classes existentes. Ele devolve `None` quando o header não é um
`Bearer` válido, então as outras classes continuam sendo avaliadas normalmente.

A permissão é escolha do serviço, e as duas opções estão em
[03 — Autenticação](03-autenticacao.md#autenticar-não-é-autorizar). Vale reforçar
que sem permission class nenhuma o endpoint aceita qualquer token válido de
qualquer projeto — a autenticação não verifica acesso.

## Passo 4 — Declarar os endpoints públicos

```python
from weni_commons.kong import api_gateway_expose


@api_gateway_expose(alias="invoices", methods=["GET"])
class InvoicesEndpoint(APIView):
    ...
```

Duas recomendações:

- Omita `service=` a menos que a view precise ir para outro service no Kong. O
  default é `None`, preenchido no sync com o nome deste serviço (de
  `KONG_SERVICE`, ou derivado de `KONG_URL_PREFIX`: `/billing` →
  `billing-service`).
- Escolha o `alias` com cuidado, porque ele é global: dois serviços com o mesmo
  alias colidem, e o último a sincronizar fica com a rota.

## Passo 5 — Criar o service no Kong

Uma vez, no onboarding:

```bash
python manage.py kong_ensure_service
```

Isso cria o service apontando para `KONG_SERVICE_URL` e a rota de bloqueio, que é
o que faz tudo que não foi exposto responder `403`. O comando é idempotente, então
reexecutar é seguro — inclusive é como se corrige um `KONG_SERVICE_URL` que estava
errado.

## Passo 6 — Sincronizar as rotas

Comece com o plano, para ver o que aconteceria:

```bash
python manage.py kong_sync --dry-run
```

Depois aplique:

```bash
python manage.py kong_sync
```

Em regime, esse comando roda automaticamente a cada deploy, via Argo Workflows —
ver [06 — Deploy](06-deploy-argo-workflows.md).

## Checklist de verificação

Depois de configurar, confirme nesta ordem. A ordem importa: cada item elimina uma
camada, então uma falha aponta direto para o culpado.

1. **A configuração chegou na aplicação.** No shell do serviço:

   ```python
   from django.conf import settings
   settings.KONG_ADMIN_URL, settings.KONG_SERVICE, settings.KONG_URL_PREFIX
   settings.KONG_SERVICE_URL
   settings.WENI_SESSION_TOKEN_DYNAMODB_TABLE
   ```

   Confirme especialmente que `KONG_SERVICE_URL` aponta para **este** ambiente e
   que a tabela é um nome, não um ARN.

2. **O serviço lê a tabela do DynamoDB.** Com um token válido em mãos:

   ```python
   from weni_commons.auth import DynamoDBSessionTokenRepository
   DynamoDBSessionTokenRepository().get("<token>")
   ```

   O retorno deve ser um dicionário com `project`, `user` e `expire_at`. `None`
   significa token inexistente, tabela errada, região errada ou credencial sem
   permissão.

3. **A validação completa funciona.**

   ```python
   from weni_commons.auth import ValidateSessionTokenUseCase
   ValidateSessionTokenUseCase().execute("<token>")
   ```

   Deve retornar um `SessionContext`. Se o passo 2 funcionou e este não, o
   problema está no Redis (alias errado ou conexão indisponível).

4. **O plano do sync está correto.** `python manage.py kong_sync --dry-run` deve
   listar os endpoints esperados e nenhuma remoção surpresa.

5. **A chamada ponta a ponta responde.** Pelo endereço do gateway, com o token no
   header `Authorization: Bearer`. Se este passo falhar depois que os quatro
   primeiros passaram, o problema está entre o Kong e o serviço — comece pelo
   [troubleshooting](07-troubleshooting.md).

6. **O bloqueio por padrão está ativo.** Chame um path que **não** foi exposto e
   confirme que a resposta é `403` com `"Route not authorized by the gateway"`. Se
   vier uma resposta normal da API, a rota de bloqueio não existe ou não cobre o
   prefixo.
