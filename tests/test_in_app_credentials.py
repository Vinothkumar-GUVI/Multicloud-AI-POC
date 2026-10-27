import os
import unittest
from unittest.mock import Mock, patch

from multicloud_ai.core.auth import (
    AWSCredentials,
    AzureCredentials,
    GCPCredentials,
    CredentialBundle,
    sanitize_exception,
    validate_bundle,
)
from multicloud_ai.core import pricing
from multicloud_ai.cloud_adapters.aws import AWSAdapter


class InAppCredentialTests(unittest.TestCase):
    def test_partial_aws_credentials_are_rejected(self):
        bundle = CredentialBundle(aws=AWSCredentials(access_key_id="only-key"))
        self.assertTrue(any("AWS Access Key ID" in item for item in validate_bundle(bundle)))

    def test_partial_azure_credentials_are_rejected(self):
        bundle = CredentialBundle(azure=AzureCredentials(tenant_id="tenant", client_id="client"))
        self.assertTrue(any("Azure Tenant ID" in item for item in validate_bundle(bundle)))

    def test_gcp_service_account_shape_is_validated(self):
        bundle = CredentialBundle(gcp=GCPCredentials(service_account_info={"type": "service_account"}))
        errors = validate_bundle(bundle)
        self.assertTrue(errors)
        self.assertIn("private_key", errors[0])

    def test_error_redaction_removes_entered_secrets(self):
        bundle = CredentialBundle(
            aws=AWSCredentials("AKIA-EXAMPLE", "aws-secret", "aws-token"),
            azure=AzureCredentials("tenant", "client", "azure-secret"),
            gcp=GCPCredentials(billing_api_key="gcp-key", service_account_info={"private_key": "gcp-private"}),
        )
        text = sanitize_exception(
            RuntimeError("AKIA-EXAMPLE aws-secret aws-token azure-secret gcp-key gcp-private"),
            bundle,
        )
        for secret in ("AKIA-EXAMPLE", "aws-secret", "aws-token", "azure-secret", "gcp-key", "gcp-private"):
            self.assertNotIn(secret, text)

    def test_explicit_aws_pricing_credentials_ignore_machine_profile(self):
        fake_session = Mock()
        with patch.dict(os.environ, {"AWS_PROFILE": "blocked-profile", "AWS_DEFAULT_PROFILE": "blocked-default"}, clear=False):
            with patch.object(pricing.boto3, "Session", return_value=fake_session) as session:
                result = pricing._aws_session("key", "secret", "token")
                self.assertIs(result, fake_session)
                self.assertEqual(os.environ.get("AWS_PROFILE"), "blocked-profile")
                self.assertEqual(os.environ.get("AWS_DEFAULT_PROFILE"), "blocked-default")
                session.assert_called_once_with(
                    aws_access_key_id="key",
                    aws_secret_access_key="secret",
                    aws_session_token="token",
                    region_name="us-east-1",
                )

    def test_explicit_aws_discovery_credentials_ignore_machine_profile(self):
        fake_session = Mock()
        fake_session.get_credentials.return_value = Mock()
        fake_session.client.return_value = Mock()
        with patch.dict(os.environ, {"AWS_PROFILE": "blocked-profile"}, clear=False):
            with patch("multicloud_ai.cloud_adapters.aws.boto3.Session", return_value=fake_session) as session:
                adapter = AWSAdapter(region="us-west-2", access_key_id="key", secret_access_key="secret")
                self.assertIs(adapter.session, fake_session)
                self.assertEqual(os.environ.get("AWS_PROFILE"), "blocked-profile")
                session.assert_called_once_with(
                    region_name="us-west-2",
                    aws_access_key_id="key",
                    aws_secret_access_key="secret",
                )

    def test_gcp_provider_keeps_service_account_in_memory(self):
        info = {
            "type": "service_account",
            "client_email": "svc@example.invalid",
            "private_key": "private",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
        provider = pricing.GCPPriceProvider(service_account_info=info)
        self.assertEqual(provider.service_account_info, info)


if __name__ == "__main__":
    unittest.main()
