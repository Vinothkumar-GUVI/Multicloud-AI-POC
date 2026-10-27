import unittest
from unittest.mock import Mock, patch

import requests

from multicloud_ai.core.agents import AgentClient


class AIConnectivityTests(unittest.TestCase):
    def test_azure_base_url_is_normalized_and_uses_api_key_header(self):
        response = Mock(status_code=200)
        response.json.return_value = {'output': []}
        transport = Mock(return_value=response)
        client = AgentClient(
            'secret', 'deployment', provider='Azure OpenAI',
            base_url='https://example.openai.azure.com', transport=transport,
        )
        client.request([], [])
        args, kwargs = transport.call_args
        self.assertEqual(args[0], 'https://example.openai.azure.com/openai/v1/responses')
        self.assertEqual(kwargs['headers']['api-key'], 'secret')
        self.assertNotIn('Authorization', kwargs['headers'])

    def test_openai_uses_bearer_header(self):
        response = Mock(status_code=200)
        response.json.return_value = {'output': []}
        transport = Mock(return_value=response)
        AgentClient('secret', 'model', transport=transport).request([], [])
        self.assertEqual(transport.call_args.kwargs['headers']['Authorization'], 'Bearer secret')

    def test_timeout_diagnostic_does_not_leak_key(self):
        client = AgentClient(
            'do-not-leak', 'model', transport=Mock(side_effect=requests.ConnectTimeout('do-not-leak')),
            max_attempts=1,
        )
        with self.assertRaises(RuntimeError) as ctx:
            client.request([], [])
        message = str(ctx.exception)
        self.assertIn('firewall', message.lower())
        self.assertNotIn('do-not-leak', message)

    def test_http_401_is_actionable_and_redacted(self):
        response = Mock(status_code=401)
        response.json.return_value = {'error': {'code': 'invalid_api_key', 'message': 'bad key'}}
        client = AgentClient('secret', 'model', transport=Mock(return_value=response), max_attempts=1)
        with self.assertRaises(RuntimeError) as ctx:
            client.request([], [])
        message = str(ctx.exception)
        self.assertIn('HTTP 401', message)
        self.assertIn('credential was rejected', message)
        self.assertNotIn('secret', message)

    def test_system_proxy_is_passed_to_requests(self):
        response = Mock(status_code=200)
        response.json.return_value = {'output': []}
        transport = Mock(return_value=response)
        with patch('multicloud_ai.core.agents.getproxies', return_value={'https': 'http://proxy:8080'}):
            AgentClient('secret', 'model', transport=transport).request([], [])
        self.assertEqual(transport.call_args.kwargs['proxies'], {'https': 'http://proxy:8080'})

    def test_connection_probe_returns_safe_metadata(self):
        response = Mock(status_code=200)
        response.json.return_value = {'id': 'resp_123'}
        response.headers = {'x-request-id': 'req_123'}
        client = AgentClient('secret', 'model', transport=Mock(return_value=response))
        result = client.test_connection()
        self.assertEqual(result['status'], 'connected')
        self.assertEqual(result['response_id'], 'resp_123')
        self.assertEqual(result['request_id'], 'req_123')
        self.assertNotIn('secret', str(result))


if __name__ == '__main__':
    unittest.main()
