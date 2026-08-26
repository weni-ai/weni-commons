# API Gateway

Documentation for the Weni API Gateway: a single public entry point and a single
authentication scheme in front of endpoints that live in different backend
services.

The gateway is built on **Kong** (routing, default-deny) and **DynamoDB**
(shared session-token store). The code that services use to join it lives in
this repository, under `weni_commons/kong/` and `weni_commons/auth/`.

## Languages

The same documentation is available in two languages. Both folders carry the
same files and the same numbering, so a change in one is easy to mirror in the
other.

| Language | Folder |
|---|---|
| Português | [pt/](pt/README.md) |
| English | [en/](en/README.md) |
