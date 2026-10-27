import unittest
from multicloud_ai.core.pricing import aws_access_issue

class AccessDiagnosticTests(unittest.TestCase):
    def test_workload_profile_is_not_auth_failure(self):
        for reason in ['Azure CDN/Front Door profile metadata does not supply usage.',
                       'Target instance size is not configured.',
                       'Azure storage usage lookup failed (HTTP 403).']:
            self.assertIsNone(aws_access_issue(reason))

    def test_real_aws_failures_are_classified(self):
        for code, expected in [('ExpiredTokenException','authentication'),
                               ('InvalidClientTokenId','authentication'),
                               ('AccessDeniedException','permission'),
                               ('ThrottlingException',None)]:
            reason=f'AWS Pricing API error: An error occurred ({code}) when calling the GetProducts operation: failed'
            self.assertEqual(aws_access_issue(reason),expected)
