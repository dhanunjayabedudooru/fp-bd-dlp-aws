import json
import unittest

from CloudHandlers.AzureLogsIngestion import AzureLogsIngestionClient, normalize_record


class FakeResponse:
    def __init__(self, status_code, json_body=None, text='', headers=None):
        self.status_code = status_code
        self.json_body = json_body
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self.json_body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class AzureLogsIngestionTests(unittest.TestCase):
    def create_client(self, session, **kwargs):
        return AzureLogsIngestionClient(
            tenant_id='tenant',
            client_id='client',
            client_secret='secret',
            data_collection_endpoint='https://example.ingest.monitor.azure.com/',
            data_collection_rule_immutable_id='dcr-123',
            stream_name='Custom-ForcepointDLPEventsV2_CL',
            session=session,
            sleep=kwargs.get('sleep', lambda _seconds: None),
            time_provider=kwargs.get('time_provider', lambda: 1000),
            max_retries=kwargs.get('max_retries', 3))

    def test_normalize_record_maps_first_numbered_field_and_preserves_extras(self):
        record = {
            'RuleName.1': 'Sensitive data',
            'DestinationEmail.1': 'first@example.com',
            'DestinationEmail.2': 'second@example.com',
            'UnexpectedField': 'value',
            'CreatedAt': '2025-01-01T00:00:00Z',
        }

        normalized = normalize_record(record)

        self.assertEqual('Sensitive data', normalized['RuleName'])
        self.assertEqual('first@example.com', normalized['DestinationEmail'])
        self.assertEqual('2025-01-01T00:00:00Z', normalized['CreatedAt'])
        self.assertEqual('second@example.com', normalized['AdditionalFields']['DestinationEmail.2'])
        self.assertEqual('value', normalized['AdditionalFields']['UnexpectedField'])

    def test_post_data_uses_entra_token_and_expected_ingestion_endpoint(self):
        session = FakeSession([
            FakeResponse(200, {'access_token': 'token', 'expires_in': 3600}),
            FakeResponse(204),
        ])
        client = self.create_client(session)

        result = client.post_data([{'RuleName.1': 'Rule'}])

        self.assertEqual(204, result.status_code)
        token_url, token_request = session.calls[0]
        self.assertEqual(
            'https://login.microsoftonline.com/tenant/oauth2/v2.0/token',
            token_url)
        self.assertEqual('https://monitor.azure.com/.default', token_request['data']['scope'])

        ingestion_url, ingestion_request = session.calls[1]
        self.assertEqual(
            'https://example.ingest.monitor.azure.com/dataCollectionRules/dcr-123/'
            'streams/Custom-ForcepointDLPEventsV2_CL?api-version=2023-01-01',
            ingestion_url)
        self.assertEqual('Bearer token', ingestion_request['headers']['Authorization'])
        self.assertEqual([{'RuleName': 'Rule'}], json.loads(ingestion_request['data']))

    def test_access_token_is_cached(self):
        session = FakeSession([
            FakeResponse(200, {'access_token': 'token', 'expires_in': 3600}),
            FakeResponse(204),
            FakeResponse(204),
        ])
        client = self.create_client(session)

        client.post_data([{'Id': 1}])
        client.post_data([{'Id': 2}])

        token_calls = [
            call for call in session.calls
            if 'login.microsoftonline.com' in call[0]
        ]
        self.assertEqual(1, len(token_calls))

    def test_transient_failure_honors_retry_after(self):
        delays = []
        session = FakeSession([
            FakeResponse(200, {'access_token': 'token', 'expires_in': 3600}),
            FakeResponse(429, text='throttled', headers={'Retry-After': '4'}),
            FakeResponse(204),
        ])
        client = self.create_client(session, sleep=delays.append)

        result = client.post_data([{'Id': 1}])

        self.assertEqual(204, result.status_code)
        self.assertEqual([4], delays)

    def test_transient_token_failure_is_retried(self):
        delays = []
        session = FakeSession([
            FakeResponse(503, text='temporarily unavailable'),
            FakeResponse(200, {'access_token': 'token', 'expires_in': 3600}),
            FakeResponse(204),
        ])
        client = self.create_client(session, sleep=delays.append)

        result = client.post_data([{'Id': 1}])

        self.assertEqual(204, result.status_code)
        self.assertEqual([1], delays)

    def test_unauthorized_ingestion_refreshes_token(self):
        session = FakeSession([
            FakeResponse(200, {'access_token': 'old-token', 'expires_in': 3600}),
            FakeResponse(401, text='expired'),
            FakeResponse(200, {'access_token': 'new-token', 'expires_in': 3600}),
            FakeResponse(204),
        ])
        client = self.create_client(session)

        result = client.post_data([{'Id': 1}])

        self.assertEqual(204, result.status_code)
        self.assertEqual(
            'Bearer new-token',
            session.calls[3][1]['headers']['Authorization'])

    def test_non_transient_failure_is_raised(self):
        session = FakeSession([
            FakeResponse(200, {'access_token': 'token', 'expires_in': 3600}),
            FakeResponse(400, text='invalid payload'),
        ])
        client = self.create_client(session)

        with self.assertRaisesRegex(RuntimeError, 'status 400'):
            client.post_data([{'Id': 1}])

    def test_configuration_requires_https_endpoint(self):
        with self.assertRaisesRegex(ValueError, 'must use HTTPS'):
            AzureLogsIngestionClient(
                tenant_id='tenant',
                client_id='client',
                client_secret='secret',
                data_collection_endpoint='http://example.test',
                data_collection_rule_immutable_id='dcr-123',
                stream_name='stream')


if __name__ == '__main__':
    unittest.main()
