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
| Inventário | `api_gateway_inventory`, um management command do `weni_commons` | Quais endpoints são públicos, em qual URL, com quais métodos, carregando quais campos |
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
`KONG_URL_PREFIX` configurado — as mesmas pré-condições do `kong_sync`. Como o
Django descobre comandos dos apps instalados, nenhum serviço precisa
implementá-lo: atualizar a lib já o faz aparecer, exatamente como o `kong_sync`.

```bash
python manage.py api_gateway_inventory --out .openapi/inventory.json
```

Na prática você não roda isso à mão — a skill roda por você (veja
[O plugin](#o-plugin-weni-api-gateway)). O comando é documentado aqui porque é
útil em CI e na depuração.

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

A geração não roda no repositório que é dono do endpoint. Ela roda no
**connect**, porque é lá que vive o documento publicado: um único
`docs/openapi/VTEX - CX API.json` com todos os endpoints de gateway de todos os
repositórios. O `openapi-schemas` é organizado assim — cada `VTEX - *.json` é uma
API de produto com muitos endpoints, em geral vindos de vários repositórios de
código — e um documento único também é a única forma de ter uma fonte da verdade.

Ela é distribuída como plugin do Cursor para que a skill fique disponível sem que
cada serviço precise versionar uma cópia do procedimento.

O plugin vive neste repositório, em `plugins/weni-api-gateway/`, porque sua
correção está amarrada ao formato do inventário — os dois são versionados juntos.

Para instalar em desenvolvimento, a partir da raiz do `weni-commons`:

```bash
ln -s "$(pwd)/plugins/weni-api-gateway" ~/.cursor/plugins/local/weni-api-gateway
```

Depois recarregue a janela do Cursor. Esse caminho serve para desenvolver a
skill, não para distribuí-la: ele exige que cada pessoa tenha este repositório
clonado. Para o time, o caminho é um **marketplace da organização** (Dashboard →
Plugins → Add Marketplace → Import from Repo) com o plugin em modo **Required**,
que instala para todos sem ninguém fazer nada, e com **Auto Refresh** ligado para
que as correções se propaguem.

Com o plugin instalado, abra o workspace do **connect** e rode no chat do Cursor,
dizendo qual repositório é dono do endpoint e qual alias ele tem no gateway:

```text
/weni-openapi flows whatsapp_flows
```

O primeiro argumento é o repositório em que a skill vai subir o Django; o nome
puro basta, porque o checkout é procurado ao lado do workspace. Sem o segundo,
todos os endpoints expostos daquele repositório são documentados.

O inventário continua cobrindo **todos** os endpoints expostos pelo decorator —
ele é barato e mostra ao desenvolvedor o que mais existe. O que o alias estreita
é apenas o que vira documentação. O inventário em si é gravado no `.openapi/` do
connect, que está no gitignore, de modo que documentar o `flows` não deixa nada
para trás no `flows`.

### Mesclar em vez de escrever

O agente nunca escreve o documento consolidado. Ele escreve um fragmento com o
único path que lhe foi pedido, e o `scripts/merge.py` mescla esse fragmento:

```bash
scripts/merge.py --fragment .openapi/whatsapp_flows.fragment.json \
                 --alias whatsapp_flows --repo flows
```

O script insere ou substitui exatamente um path, junta a tag, aplica o bloco
compartilhado de `security` e `components`, reconstrói a seção `## Index` do
overview a partir do `paths` e registra em
`docs/openapi/.weni-openapi.manifest.json` de qual repositório veio o alias — a
procedência fica num arquivo ao lado, fora do que a VTEX publica.

Todo o resto do documento mantém seus bytes. É essa propriedade que torna a
coisa segura com quarenta endpoints: a prosa que alguém editou à mão no mês
passado não corre risco por causa de uma execução voltada a outro alias, e
rodar de novo com o mesmo fragmento não gera diff nenhum.

Conflito é recusa, nunca sobrescrita. Dois aliases reivindicando o mesmo path,
ou um componente compartilhado editado no lugar, terminam com erro e pedem
decisão de uma pessoa.

Os outros subcomandos: `--extract <alias>` imprime o que o documento já diz
sobre um alias, que é como uma regeração preserva a prosa; `--list` mostra cada
alias documentado com seu repositório; `--remove` tira um que perdeu o
decorator; `--reindex` reconstrói só o índice, depois que summaries ou o slug do
Portal mudam.

### Revalidar um arquivo editado à mão

Depois de gerar, é comum o desenvolvedor ajustar o arquivo — corrigir uma
descrição, acrescentar um campo, trocar um exemplo. Para confirmar que ele
continua publicável, sem regerar nada:

```text
/weni-openapi validate
```

Esse modo só faz duas coisas: roda o Spectral e corrige o que ele reprovar, com
a menor edição que satisfaz cada regra, até zerar. Ele **não** monta o
inventário, **não** regera o documento e **não** desfaz o que você escreveu. Se
a única forma de calar uma regra fosse apagar conteúdo seu, a skill para e
pergunta. E se algo no arquivo parecer divergir do código, ela relata como
observação em vez de mexer.

Sem argumento de arquivo, ele valida o documento consolidado, que é o caso que
importa. Passe um caminho apenas para validar outro arquivo.

Se nenhuma rota tiver aquele alias, a skill para e lista os aliases que existem,
em vez de documentar a rota de nome parecido.

E é só isso. A skill roda o inventário sozinha, através do
`scripts/inventory.sh --repo <repositorio>`, que resolve o que o comando precisa
para subir o Django: acha o checkout, escolhe o Python do virtualenv, aponta as
bibliotecas GDAL e GEOS que projetos PostGIS exigem no macOS e, se o
`weni-commons` instalado for anterior ao comando, cai para um checkout local via
`PYTHONPATH`.

Em seguida ela lê o código de cada rota, monta o fragmento a partir dos
templates, escreve a prosa, mescla e valida. O desenvolvedor não roda dois
comandos — roda a skill.

Os scripts rodam em macOS e Linux. No Windows, use WSL: a detecção de virtualenv
procura `bin/python`, não `Scripts/`.

### Validação com o Spectral de verdade

A skill traz uma cópia da ruleset da VTEX em `assets/spectral/spectral.yml`,
com as duas funções JavaScript próprias. Na primeira execução, se não houver
Node 18+ no PATH, o `validate.sh` baixa um Node LTS para
`~/.cache/weni-openapi` — sem `sudo`, sem instalar no sistema — e então faz
`npm ci` do Spectral CLI em `assets/spectral/node_modules` (gitignored). Nas
execuções seguintes, os dois já estão no disco.

```bash
scripts/validate.sh "docs/openapi/VTEX - CX API.json"
```

O ciclo é: ler as violações, corrigir o conteúdo, rodar de novo, até zerar. A
regra é corrigir o conteúdo, nunca enfraquecê-lo para calar uma regra. A
ruleset é um snapshot: se o Portal mudar as regras, recopie de
[openapi-schemas](https://github.com/vtex/openapi-schemas); não edite a cópia
para silenciar violações.

Vale notar a diferença de abordagem: o fluxo interno da VTEX *simula* o Spectral
por um servidor MCP. Rodar o linter real é mais confiável, e sai de graça.

## Resultado do piloto

O piloto rodou sobre as rotas que o flows expõe hoje: `/contacts`, `/channels` e
`/events`, as três agora dentro do `VTEX - CX API.json`. Os documentos gerados
passaram no Spectral **sem nenhum achado em nenhuma severidade na primeira
execução** — para comparação, schemas já publicados pela VTEX acusam erros nessa
mesma ruleset.

O trabalho manual se concentrou onde a divisão de camadas previa: ler o corpo
dos sete `SerializerMethodField` do `ContactReadSerializer`, cuja forma não é
introspectável, e descobrir dois parâmetros de query (`order_by` e `reverse`)
que a classe de paginação lê diretamente.

O piloto também encontrou um bug: um `DictField` era descrito como array,
porque no DRF ele também tem um atributo `child`. Foi corrigido e coberto por
teste.

## Publicação

O documento é versionado no connect e revisado como código. Publicar é um passo
humano separado: copiar `docs/openapi/VTEX - CX API.json` para um checkout do
[openapi-schemas](https://github.com/vtex/openapi-schemas) com o mesmo nome,
conferir se a entrada dele existe no `config.json` daquele repositório e abrir um
pull request lá. O manifesto fica para trás — ele é nosso, não da VTEX.

## O que continua sendo decisão humana

A automação não decide duas coisas, e elas seguem em aberto:

1. **Se a base pública inclui `/api/v1`.** O server configurado é
   `https://cx.vtex.com/api/v1`, e o Kong registra paths planos como
   `/contacts`. Isso só fecha se a borda mapear `/api/v1/contacts` para o
   `/contacts` do Kong. Precisa de confirmação da infra.
2. **O slug do Portal.** O nome do arquivo está definido — `VTEX - CX API.json` —
   mas o slug que o Portal deriva dele é decisão de quem escreve a documentação,
   e todos os links do índice dependem disso. A skill assume `cx-api`; se mudar,
   um `merge.py --reindex` reescreve todos os links.

Uma terceira questão está resolvida: o Portal publica **uma referência por API**,
então todo endpoint de gateway de todo repositório vai para o mesmo documento.

## Próximos passos

- Para entender como um serviço entra no gateway, e portanto o que vira endpoint
  documentável: [05 — Instalação](05-instalacao.md).
- Para entender o `@api_gateway_expose` e o `alias`, que definem o path público:
  [04 — Referência do weni-commons](04-referencia-weni-commons.md).
