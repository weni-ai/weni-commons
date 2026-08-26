# API Gateway — documentation

The API Gateway gives our clients a single address and a single authentication
scheme for endpoints that live in different services. It is built on **Kong**
(routing and default-deny) and **DynamoDB** (shared session-token store), and
the code a service uses to join the gateway lives in this repository, under
`weni_commons/kong/` and `weni_commons/auth/`.

## Index

| File | Contents |
|---|---|
| [01 — Introduction](01-introduction.md) | The problem the gateway solves, the role of Kong and DynamoDB, and what depends on what |
| [02 — Architecture](02-architecture.md) | The path of a request, the Kong route model, and path rewriting |
| [03 — Authentication](03-authentication.md) | The session token, validation against Redis and DynamoDB, and the split between authentication and authorization |
| [04 — weni-commons reference](04-weni-commons-reference.md) | What each piece of code does, the commands, the flags, and the pitfalls |
| [05 — Installation](05-installation.md) | How to put a service on the gateway, variable by variable |
| [06 — Deploying with Argo Workflows](06-deploy-argo-workflows.md) | How the sync runs automatically on every new image |
| [07 — Troubleshooting](07-troubleshooting.md) | Real symptoms and where to look for each one |
<<<<<<< HEAD
=======
| [08 — OpenAPI documentation](08-openapi-documentation.md) | How we generate the Developer Portal schemas from the code |
>>>>>>> feat/weni-openapi-plugin

## Where to start

It depends on what you are doing:

- **Consuming the API as a client or integrator**: read the
  [introduction](01-introduction.md) and [authentication](03-authentication.md).
  That is enough to get a token and call an endpoint.
- **Exposing a service's endpoints on the gateway**: read the
  [architecture](02-architecture.md), then the
  [installation guide](05-installation.md). The
  [reference](04-weni-commons-reference.md) answers the detail questions.
- **Operating or debugging the gateway**: the
  [reference](04-weni-commons-reference.md),
  [deployment](06-deploy-argo-workflows.md), and
  [troubleshooting](07-troubleshooting.md).
<<<<<<< HEAD
=======
- **Documenting endpoints on the VTEX Developer Portal**: the
  [OpenAPI documentation guide](08-openapi-documentation.md).
>>>>>>> feat/weni-openapi-plugin
