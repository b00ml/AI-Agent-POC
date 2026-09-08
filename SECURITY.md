# Security Policy

## Scope

This repository is an educational proof of concept for an agent-assisted
expense audit workflow. It is not a production-ready financial system.

The current POC intentionally does not provide production-grade identity,
RBAC, SSO, multi-tenancy, key management, or network isolation. In the
existing ERP integration path, the browser can retain connection settings and
the proxy API accepts connection parameters from the client. Do not use real
credentials or sensitive production data with the public demo.

The demo mode must run without an ERP API key, external LLM key, or private
ERP image. Use synthetic fixtures only.

## Reporting a vulnerability

Do not open a public issue containing credentials, personal data, invoice
images, bank details, or exploit details. Report privately through the GitHub
repository's security contact, or contact the repository owner before public
disclosure.

Please include the affected file or endpoint, reproduction steps using
synthetic data, impact, and a proposed mitigation when available.

## Credential handling

- Never commit `.env`, API keys, access tokens, passwords, model provider keys,
  or private ERP URLs.
- Rotate any credential that has appeared in a local file or Git history before
  publishing a repository.
- Do not paste secret-scan matches into issues, commits, logs, or screenshots.
