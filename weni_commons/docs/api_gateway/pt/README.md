# API Gateway — documentação

O API Gateway dá aos nossos clientes um único endereço e um único esquema de
autenticação para endpoints que vivem em serviços diferentes. Ele é construído
sobre **Kong** (roteamento e bloqueio por padrão) e **DynamoDB** (store
compartilhado dos session tokens), e o código que um serviço usa para entrar no
gateway está neste repositório, em `weni_commons/kong/` e `weni_commons/auth/`.

## Índice

| Arquivo | Conteúdo |
|---|---|
| [01 — Introdução](01-introducao.md) | Que problema o gateway resolve, o papel do Kong e do DynamoDB, e quem depende de quem |
| [02 — Arquitetura](02-arquitetura.md) | O caminho de uma requisição, o modelo de rotas do Kong e a reescrita de path |
| [03 — Autenticação](03-autenticacao.md) | O session token, a validação em Redis e DynamoDB, e a separação entre autenticar e autorizar |
| [04 — Referência do weni-commons](04-referencia-weni-commons.md) | O que cada peça do código faz, os comandos, as flags e as armadilhas |
| [05 — Instalação](05-instalacao.md) | Como colocar um serviço no gateway, variável por variável |
| [06 — Deploy com Argo Workflows](06-deploy-argo-workflows.md) | Como o sync roda automaticamente a cada imagem nova |
| [07 — Troubleshooting](07-troubleshooting.md) | Sintomas reais e onde olhar em cada um |
| [08 — Documentação OpenAPI](08-documentacao-openapi.md) | Como geramos os schemas do Developer Portal a partir do código |

## Por onde começar

Depende do que você quer fazer:

- **Consumir a API como cliente ou integrador**: leia a [introdução](01-introducao.md)
  e a [autenticação](03-autenticacao.md). É o suficiente para obter um token e
  chamar um endpoint.
- **Expor endpoints de um serviço no gateway**: leia a
  [arquitetura](02-arquitetura.md) e depois a [instalação](05-instalacao.md).
  A [referência](04-referencia-weni-commons.md) responde as dúvidas de detalhe.
- **Operar ou depurar o gateway**: a [referência](04-referencia-weni-commons.md),
  o [deploy](06-deploy-argo-workflows.md) e o
  [troubleshooting](07-troubleshooting.md).
- **Documentar endpoints no Developer Portal da VTEX**: a
  [documentação OpenAPI](08-documentacao-openapi.md).
