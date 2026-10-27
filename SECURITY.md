# Security model

## Credential lifecycle

Cloud credentials entered in **Cloud Access** are held only in the current Streamlit server process/session. The application does not intentionally persist them to disk, `.env`, logs, downloadable reports, Terraform, or migration packages.

The application supports:

- AWS access key + secret key + optional session token.
- Azure service-principal tenant ID + client ID + client secret.
- GCP service-account JSON and optional Cloud Billing Catalog API key.
- Runtime identity fallbacks for managed deployments.

Use short-lived credentials whenever possible and clear the application session when work is complete.

## Redaction

Provider exceptions are passed through application-level credential redaction before display. Secret-like placeholders are also checked by Terraform static validation.

## Least privilege

Use read-only discovery permissions plus the minimum pricing API permissions. Generated Terraform should be reviewed and executed using a separate deployment identity rather than the discovery identity.

## Deployment controls

For shared or internet-accessible deployments:

- terminate TLS before Streamlit;
- require organization authentication/SSO;
- isolate tenants and sessions;
- restrict outbound network destinations to provider APIs and approved FX endpoints;
- centralize application logs without request/session secret capture;
- use a secret manager or workload identity instead of long-lived static keys where platform controls allow it;
- require approval of `terraform plan` before apply.

## AI endpoint and proxy handling

- AI credentials, endpoint settings, and optional proxy URLs are runtime/session inputs and are not written to migration artifacts.
- Agent evidence is explicitly whitelisted and redacted before transmission; raw cloud credentials, tags, and raw provider configuration are not sent to the AI endpoint.
- The application supports OpenAI, Azure OpenAI v1, and approved OpenAI-compatible Responses endpoints.
- On managed Windows systems, the client attempts to use the operating-system certificate trust store and the system HTTP/HTTPS proxy. TLS verification is not disabled.
- Provider error payloads are truncated/redacted before display; request bodies and credentials are never included in connectivity diagnostics.
