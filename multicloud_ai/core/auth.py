"""Ephemeral cloud credential models used by the Streamlit application.

Credentials are intentionally kept in process/session memory only. This module
never writes secrets to disk, environment variables, logs, reports, or generated
Terraform packages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable


@dataclass(frozen=True)
class AWSCredentials:
    access_key_id: str = ""
    secret_access_key: str = ""
    session_token: str = ""
    region: str = ""

    @property
    def explicit(self) -> bool:
        return bool(self.access_key_id and self.secret_access_key)

    @property
    def partial(self) -> bool:
        return bool(self.access_key_id or self.secret_access_key or self.session_token) and not self.explicit


@dataclass(frozen=True)
class AzureCredentials:
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    subscription_id: str = ""

    @property
    def explicit(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret)

    @property
    def partial(self) -> bool:
        provided = (self.tenant_id, self.client_id, self.client_secret)
        return any(provided) and not all(provided)


@dataclass(frozen=True)
class GCPCredentials:
    project_id: str = ""
    service_account_info: Dict[str, Any] = field(default_factory=dict)
    billing_api_key: str = ""

    @property
    def explicit(self) -> bool:
        return bool(self.service_account_info)


@dataclass(frozen=True)
class CredentialBundle:
    aws: AWSCredentials = field(default_factory=AWSCredentials)
    azure: AzureCredentials = field(default_factory=AzureCredentials)
    gcp: GCPCredentials = field(default_factory=GCPCredentials)

    def secret_values(self) -> Iterable[str]:
        values = [
            self.aws.access_key_id,
            self.aws.secret_access_key,
            self.aws.session_token,
            self.azure.client_secret,
            self.gcp.billing_api_key,
        ]
        private_key = str((self.gcp.service_account_info or {}).get("private_key") or "")
        private_key_id = str((self.gcp.service_account_info or {}).get("private_key_id") or "")
        client_email = str((self.gcp.service_account_info or {}).get("client_email") or "")
        values.extend([private_key, private_key_id, client_email])
        return [v for v in values if v]


def sanitize_exception(exc: Exception, credentials: CredentialBundle) -> str:
    """Return an error string with entered credential material redacted."""
    text = str(exc)
    for secret in sorted(set(credentials.secret_values()), key=len, reverse=True):
        if secret:
            text = text.replace(secret, "***")
    return text


def validate_bundle(credentials: CredentialBundle) -> list[str]:
    """Return input-validation errors without making provider API calls."""
    errors: list[str] = []
    if credentials.aws.partial:
        errors.append("AWS Access Key ID and Secret Access Key must be supplied together.")
    if credentials.azure.partial:
        errors.append("Azure Tenant ID, Client ID, and Client Secret must be supplied together.")
    info = credentials.gcp.service_account_info or {}
    if info:
        required = ("type", "client_email", "private_key", "token_uri")
        missing = [key for key in required if not str(info.get(key) or "").strip()]
        if missing:
            errors.append("GCP service account JSON is missing required field(s): " + ", ".join(missing) + ".")
    return errors
