# 03 — Autenticação

## O session token

O gateway usa um único tipo de credencial: o **session token**, um hash opaco
emitido pelo Connect e vinculado a um projeto.

Ele é gerado com `secrets.token_urlsafe(32)`, então é uma string aleatória de 43
caracteres, sem estrutura interna. Diferente de um JWT, ele não carrega
informação nenhuma: quem quiser saber a que projeto ele pertence precisa
consultar o store. Isso é proposital, porque é o que permite invalidar um token
imediatamente — basta remover o item do store, algo que não se consegue com um
token autocontido e assinado.

### Emissão

```bash
curl -s -G "${CONNECT_BASE_URL}/v2/projects/${PROJECT_UUID}/get-token" \
  -H "Authorization: Bearer ${KEYCLOAK_TOKEN}" \
  --data-urlencode "duration=7600"
```

```json
{ "hash": "xATi0rFElmBXmd7FyXgWB-rx7glo2ejmhNui9eItsB4" }
```

Essa chamada é autenticada com o token do Keycloak da sessão logada, e o Connect
só emite o hash se o usuário tiver autorização no projeto pedido — caso contrário
responde `404`. O parâmetro `duration` é obrigatório, em segundos, e é validado
contra `SESSION_TOKEN_MIN_DURATION` e `SESSION_TOKEN_MAX_DURATION` nas settings do
Connect; fora do intervalo, a resposta é `400`.

Ao emitir, o Connect grava o token no DynamoDB e já aquece o próprio Redis. Vale
notar que esse aquecimento vale só para o Connect: cada serviço tem o seu Redis, e
a primeira chamada de um cliente a um serviço diferente sempre vai buscar no
DynamoDB.

### Uso

```http
GET /contacts?limit=10
Authorization: Bearer xATi0rFElmBXmd7FyXgWB-rx7glo2ejmhNui9eItsB4
```

O esquema é sempre `Bearer`. Um token de API antigo, no esquema `Token`, continua
funcionando nos serviços que já o aceitavam, mas não é o fluxo do gateway.

### Invalidação

```http
POST /v2/projects/{project_uuid}/invalidate-session-token
Authorization: Bearer <session token>

{ "hash": "<token a invalidar>" }
```

Esse endpoint é autenticado com o próprio session token, e o Connect verifica que
o token a invalidar pertence ao mesmo projeto do token que autenticou a chamada —
se não pertencer, responde `403`.

## Como o serviço valida o token

A validação é feita pelo `SessionTokenAuthentication`, em
`weni_commons/auth/authentication.py`, que é uma authentication class do DRF. O
caminho é:

```mermaid
flowchart TD
    Start[Requisição chega] --> Header{"Header Authorization<br/>com esquema Bearer?"}
    Header -->|não| Skip["Retorna None,<br/>e a próxima authentication class assume"]
    Header -->|sim| Cache["Busca a chave auth:session-token:hash no Redis"]
    Cache -->|hit| Ok[Autenticado]
    Cache -->|miss| Dynamo["get_item no DynamoDB pela token_hash"]
    Dynamo -->|não encontrado| Skip
    Dynamo -->|encontrado| Ttl{"Ainda dentro da validade?"}
    Ttl -->|não| Skip
    Ttl -->|sim| Warm[Aquece o Redis] --> Ok
```

Dois comportamentos merecem atenção:

- **Falha na validação retorna `None`, não erro.** Quando o token está ausente,
  inválido, expirado, ou quando a consulta ao store falha, a classe devolve
  `None`, o que faz o DRF seguir para a próxima authentication class configurada.
  Isso é deliberado: uma configuração errada de DynamoDB ou Redis não deve virar
  `500` em toda a API, e serviços com autenticação legada continuam funcionando
  em paralelo. O efeito colateral é que uma falha de infraestrutura aparece para
  o cliente como `403`, não como erro de servidor — é o que torna o
  [troubleshooting](07-troubleshooting.md) desse `403` menos óbvio do que parece.
- **O cache tem teto de tempo.** O TTL usado no Redis é
  `min(tempo restante do token, WENI_SESSION_TOKEN_MAX_REDIS_TTL)`. Um token de 24
  horas não fica 24 horas em cache: ele é recarregado do DynamoDB periodicamente,
  o que limita a janela em que um token invalidado continuaria aceito por um
  serviço que já o tinha em cache.

## O que fica no request

Depois de autenticar com sucesso, a view encontra:

| Atributo | Conteúdo |
|---|---|
| `request.user` | `SessionUser`, com o atributo `email` |
| `request.auth` | `SessionContext(project, user, expire_at)` |
| `request.project_uuid` | o UUID do projeto a que o token pertence |

O `SessionUser` não é um usuário do Django: ele só expõe `email`,
`is_authenticated` e `is_anonymous`. Isso é suficiente para o DRF considerar a
requisição autenticada, e é intencional que não seja mais do que isso — o
`weni-commons` não pode assumir que o serviço tem um modelo de usuário, e muito
menos qual é.

## Autenticar não é autorizar

Essa separação é a decisão de design mais importante desta parte do sistema.

O `SessionTokenAuthentication` responde apenas duas perguntas: **este token é
válido?** e **a que projeto e usuário ele pertence?** Ele não verifica se o
usuário pode acessar aquele projeto, e não verifica se o projeto do token é o
projeto que a view está manipulando.

O motivo é que essa verificação não tem uma forma única. Alguns serviços têm
modelo de organização, outros não têm nada parecido; alguns precisam de níveis de
papel, outros só de pertencimento. Colocar essa lógica na autenticação obrigaria
o `weni-commons` a assumir um modelo de dados que não existe em todos os serviços.

Então a divisão é: **a autenticação prova identidade, a permissão decide acesso.**
Cada serviço escolhe como implementar a permissão, e há dois caminhos prontos.

### Caminho 1 — perguntar ao Connect

Para serviços que não têm modelo de organização próprio, o `weni-commons` traz o
`ConnectProjectAuthorization`, uma permission class abstrata em
`weni_commons/auth/connect.py`. Ela consulta o Connect e entrega o papel do
usuário no projeto:

```http
GET {WENI_CONNECT_API_URL}/v2/projects/{project_uuid}/authorization
Authorization: <o mesmo header que chegou na requisição>
```

O que a classe base faz: confere que a requisição está autenticada, lê o
`request.project_uuid`, repassa o header `Authorization` para o Connect, guarda o
papel retornado em `request.project_authorization` e delega a decisão final ao
serviço. O que o serviço faz: implementar `has_required_role`.

```python
from weni_commons.auth import ConnectProjectAuthorization


class IsProjectContributor(ConnectProjectAuthorization):
    def has_required_role(self, request, view, role: int) -> bool:
        return role >= CONTRIBUTOR


class MyView(APIView):
    authentication_classes = [SessionTokenAuthentication]
    permission_classes = [IsProjectContributor]
```

`has_required_role` é abstrato de propósito: sem implementação, ele levanta
`NotImplementedError`, porque não existe um nível de acesso padrão que seja seguro
para todos os casos.

Todo caminho de falha nega o acesso: sem `project_uuid`, sem header
`Authorization`, Connect fora do ar, resposta diferente de `200` ou JSON
inesperado, o resultado é sempre negar. Inclusive o caso de
`WENI_CONNECT_API_URL` vazio — uma configuração incompleta bloqueia tudo, em vez
de liberar tudo.

### Caminho 2 — reaproveitar as permissões que o serviço já tem

Serviços com modelo de organização e regras de permissão maduras podem preferir
traduzir o session token para os próprios objetos, e manter as permissões que já
existem. É o que o Flows faz no `_resolve_session_user`, em
`temba/api/v2/views_base.py`: a partir do `request.project_uuid` ele resolve a
`Org`, encontra o usuário Django pelo e-mail do `SessionUser`, confirma que esse
usuário pertence à org e substitui o `request.user`. A partir daí as permission
classes existentes funcionam sem alteração.

A vantagem é não duplicar regras de permissão; o custo é uma consulta ao banco por
requisição, e o serviço precisa ter os usuários e projetos espelhados localmente.

## O DynamoDB

A tabela é compartilhada entre os serviços e tem uma estrutura simples:

| Atributo | Tipo | Conteúdo |
|---|---|---|
| `token_hash` | string | chave de partição; o hash do token |
| `project` | string | UUID do projeto |
| `user` | string | e-mail do usuário que gerou o token |
| `expire_at` | string | data e hora de expiração, em ISO 8601 |
| `ttl` | número | o mesmo `expire_at` em epoch, para o TTL nativo do DynamoDB |

O `ttl` é o que faz o DynamoDB apagar itens vencidos sozinho. Ele existe em
paralelo ao `expire_at` porque o TTL nativo exige um atributo numérico em epoch,
enquanto a validação no código compara a data em ISO.

O repositório (`DynamoDBSessionTokenRepository`) é tolerante a tabela não
configurada: se o nome da tabela estiver vazio, todas as operações se tornam
no-op, e a validação passa a depender só do Redis. Isso permite subir o código
antes da tabela existir, mas em produção é uma configuração que não funciona para
clientes reais, porque cada serviço tem um Redis diferente do que o Connect
aqueceu.

Um detalhe que já causou problema: a configuração espera o **nome** da tabela, não
o ARN. Ver [troubleshooting](07-troubleshooting.md).

## Próximos passos

- Detalhes do código e dos comandos:
  [04 — Referência](04-referencia-weni-commons.md).
- Como configurar tudo isso num serviço:
  [05 — Instalação](05-instalacao.md).
