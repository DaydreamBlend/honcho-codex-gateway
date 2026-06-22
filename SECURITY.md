# Security

Honcho Codex Gateway is intended for trusted local, single-user setups. Do not expose the gateway publicly unless you fully understand the risk.

## Secrets

Treat the following as passwords:

- Codex login/session files, including `~/.codex/auth.json` and OS credential-store entries.
- This repository's `.auth/` directory.
- `.env` files.
- Docker Compose override files or generated gateway/Honcho config files containing API keys.
- Any generated `GATEWAY_API_KEY` value.

Do not commit secrets. Do not paste logs containing tokens, cookies, session files, `.env` contents, or private credentials into public issues, chats, or support requests.

If a token, session file, `.env`, or gateway key is exposed, rotate the affected credentials and recreate the affected containers.

## Network exposure

The documented Docker Compose setup binds the gateway to `127.0.0.1:8787` by default. Keep it bound to localhost unless you have a specific reason and have added appropriate firewall restrictions.

If running on a remote server, prefer explicit firewall restrictions and trusted private networking. This project assumes no untrusted network clients.

## Threat model

This project assumes:

- a trusted local machine;
- a single trusted user;
- no untrusted network clients;
- no public internet exposure;
- no shared credentials;
- no malicious local users.

This project does not defend against:

- public exposure of the gateway;
- a compromised local machine;
- stolen Codex session files;
- leaked `.env` files;
- hostile multi-user environments.

## Reporting security concerns

Do not open public issues containing tokens, cookies, auth files, `.env` contents, or private credentials. If you need to report a security concern, describe the behavior without secrets and redact sensitive values.
