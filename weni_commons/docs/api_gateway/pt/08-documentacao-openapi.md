# 08 — Documentação OpenAPI

Expor um endpoint no gateway é metade do trabalho. A outra metade é documentá-lo
no [Developer Portal da VTEX](https://developers.vtex.com/docs/api-reference),
que publica schemas **OpenAPI 3.0** versionados no repositório
[openapi-schemas](https://github.com/vtex/openapi-schemas).

Escrever esses schemas à mão é caro e não escala: um único endpoint de listagem
passa de 300 linhas de JSON, com regras de estilo que um linter rejeita ao menor
desvio. E o custo se repete a cada serviço que entra no gateway.

## A ideia: separar o que é verificável do que é redação

A automação é dividida em duas camadas, e essa divisão é o ponto central.

| Camada | Quem produz | Responde |
|---|---|---|
| Inventário | `python manage.py api_gateway_inventory` | Quais endpoints são públicos, em qual URL, com quais métodos, carregando quais campos |
| Documentação | a skill `weni-openapi`, no Cursor | O que cada endpoint significa e como é um payload realista |

O inventário é lido do resolver de URLs do Django e dos serializers do DRF. Ou
seja, as respostas que **não podem estar erradas** — o path público, os métodos
liberados, os nomes e tipos dos campos — não são inferidas por um modelo, são
extraídas do código que o gateway realmente serve.

O que sobra para a camada de redação é justamente o que nenhuma introspecção
produz: o significado de cada campo, o resumo da operação e um exemplo plausível.

Uma consequência prática: a automação não depende de docstrings. As views do
flows têm docstrings ricas, mas isso é uma peculiaridade do flows — os outros
repositórios não têm, e a automação precisa funcionar em todos.

## O comando `api_gateway_inventory`

Vem no `weni_commons`, então basta ter `weni_commons` em `INSTALLED_APPS` e o
`KONG_URL_PREFIX` configurado — as mesmas pré-condições do `kong_sync`.

```bash
python manage.py api_gateway_inventory --out .openapi/inventory.json
```

Não faz nenhuma chamada de rede e não escreve no Kong: percorre o resolver de
URLs, encontra as views decoradas com `@api_gateway_expose` e descreve cada uma.

| Flag | Efeito |
|---|---|
| `--out` | Escreve no arquivo indicado; sem ela, o JSON vai para o stdout |
| `--service` | Restringe a um service do Kong; por padrão traz todos, porque um repositório pode expor views para mais de um |
| `--suffix` | Sufixo de URL usado na descoberta, igual ao do `kong_sync` |
| `--indent` | Indentação do JSON; `0` gera compacto |
| `--fail-on-warnings` | Sai com erro se houver avisos, útil em CI |

Com `--out`, o resumo vai para o stderr e o stdout continua sendo um stream JSON
limpo, o que permite encadear o comando em pipe.

### O que cada rota traz

Além do path público e dos métodos, cada rota carrega o caminho e a linha da
view, os serializers de leitura e de escrita com todos os campos tipados, a
paginação, os filtros, as classes de permissão e de autenticação, e os
parâmetros de path já tipados a partir do converter do Django.

A introspecção é sempre best-effort e nunca derruba o comando. Um serializer que
não pode ser instanciado cai para os campos declarados, e um campo que não pode
ser classificado é marcado como `unresolved` em vez de receber um tipo errado.

### Os avisos são a parte mais útil

O inventário não preenche silenciosamente o que não conseguiu resolver: ele
reporta. Dois avisos valem destaque porque apontam problemas reais.

`missing_alias` diz que a rota só é alcançável sob o prefixo do serviço, isto é,
ela ainda não tem uma URL de cliente. Rotas assim não são documentadas.

`method_mismatch` diz que a view implementa métodos que o gateway bloqueia. É o
caso do `ContactsEndpoint` no flows: implementa `GET`, `POST` e `DELETE`, mas o
decorator libera só `GET`. Documentar `POST` publicaria um `405`.

Os outros são `no_serializer`, `serializer_declared_only`, `unresolved_fields` e
`duplicate_route_name`. O que fazer em cada um está no `reference.md` da skill.

## O plugin `weni-api-gateway`

A geração roda no repositório que é dono dos endpoints, não no `weni-commons`.
Por isso ela é distribuída como plugin do Cursor: instala-se uma vez e a skill
fica disponível em qualquer workspace, sem que cada serviço precise versionar uma
cópia do procedimento.

O plugin vive neste repositório, em `plugins/weni-api-gateway/`, porque sua
correção está amarrada ao formato do inventário — os dois são versionados juntos.

Para instalar em desenvolvimento, a partir da raiz do `weni-commons`:

```bash
ln -s "$(pwd)/plugins/weni-api-gateway" ~/.cursor/plugins/local/weni-api-gateway
```

Depois recarregue a janela do Cursor. Para o time, o caminho é adicionar este
repositório ao marketplace da organização e instalar o plugin em **Customize**.

Com o plugin instalado, no repositório do serviço:

```text
/weni-openapi
```

A skill constrói o inventário, lê o código de cada rota, monta o documento a
partir dos templates, escreve a prosa e valida.

### Validação com o Spectral de verdade

O `openapi-schemas` traz a ruleset da VTEX em `.spectral.yml`, com duas funções
JavaScript próprias. A skill roda o **Spectral CLI de verdade** contra essa
ruleset:

```bash
scripts/validate.sh docs/openapi/flows.openapi.json
```

O script localiza o checkout do `openapi-schemas` — ou aceita o caminho em
`OPENAPI_SCHEMAS_REPO` — e roda o linter de dentro dele, para que as funções
customizadas sejam resolvidas. O ciclo é: ler as violações, corrigir o
conteúdo, rodar de novo, até zerar. A regra é corrigir o conteúdo, nunca
enfraquecê-lo para calar uma regra.

Vale notar a diferença de abordagem: o fluxo interno da VTEX *simula* o Spectral
por um servidor MCP. Rodar o linter real é mais confiável, e sai de graça.

## Resultado do piloto

O piloto rodou sobre as duas rotas que o flows expõe hoje, `/contacts` e
`/channels`. O documento gerado passou no Spectral **sem nenhum achado em
nenhuma severidade na primeira execução** — para comparação, schemas já
publicados pela VTEX acusam erros nessa mesma ruleset.

O trabalho manual se concentrou onde a divisão de camadas previa: ler o corpo
dos sete `SerializerMethodField` do `ContactReadSerializer`, cuja forma não é
introspectável, e descobrir dois parâmetros de query (`order_by` e `reverse`)
que a classe de paginação lê diretamente.

O piloto também encontrou um bug: um `DictField` era descrito como array,
porque no DRF ele também tem um atributo `child`. Foi corrigido e coberto por
teste.

## O que continua sendo decisão humana

A automação não decide três coisas, e elas seguem em aberto:

1. **Se a base pública inclui `/api/v1`.** O server configurado é
   `https://cx.vtex.com/api/v1`, e o Kong registra paths planos como
   `/contacts`. Isso só fecha se a borda mapear `/api/v1/contacts` para o
   `/contacts` do Kong. Precisa de confirmação da infra.
2. **O título e o nome do arquivo publicado.** O Portal deriva o slug da URL a
   partir deles, então a definição é de quem escreve a documentação.
3. **Um schema ou vários.** Se cada serviço publica o seu ou se todos compõem um
   único schema do gateway. Até que se decida, o comando gera um arquivo por
   serviço, o que mantém as duas opções abertas.

## Próximos passos

- Para entender como um serviço entra no gateway, e portanto o que vira endpoint
  documentável: [05 — Instalação](05-instalacao.md).
- Para entender o `@api_gateway_expose` e o `alias`, que definem o path público:
  [04 — Referência do weni-commons](04-referencia-weni-commons.md).
