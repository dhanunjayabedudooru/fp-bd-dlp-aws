import unittest
from unittest.mock import Mock, patch

from CloudHandlers.AzureDataCollector import AzureDataCollector, is_azure_configured


class AzureDataCollectorTests(unittest.TestCase):
    def test_legacy_configuration_remains_supported(self):
        self.assertTrue(is_azure_configured({
            'AzureWorkspaceID': 'workspace',
            'AzurePrimaryKey': 'key',
            'LogName': 'ForcepointDLPEvents',
        }))

    def test_logs_ingestion_configuration_is_validated(self):
        self.assertTrue(is_azure_configured({
            'AzureIngestionMode': 'LogsIngestion',
            'AzureLogsIngestion': {
                'TenantId': 'tenant',
                'ClientId': 'client',
                'ClientSecret': 'secret',
                'DataCollectionEndpoint': 'https://example.ingest.monitor.azure.com',
                'DataCollectionRuleImmutableId': 'dcr-123',
                'StreamName': 'Custom-ForcepointDLPEventsV2_CL',
            },
        }))

    @patch('CloudHandlers.AzureDataCollector.Persistence.set_date')
    @patch('CloudHandlers.AzureDataCollector.AzureLogsIngestionClient')
    def test_checkpoint_updates_only_after_all_batches_succeed(
            self,
            client_type,
            set_date):
        api = client_type.return_value
        api.post_data.side_effect = [
            Mock(status_code=204),
            RuntimeError('second batch failed'),
        ]
        collector = AzureDataCollector(
            Mock(),
            config={
                'AzureIngestionMode': 'LogsIngestion',
                'AzureLogsIngestion': {
                    'TenantId': 'tenant',
                    'ClientId': 'client',
                    'ClientSecret': 'secret',
                    'DataCollectionEndpoint': 'https://example.ingest.monitor.azure.com',
                    'DataCollectionRuleImmutableId': 'dcr-123',
                    'StreamName': 'Custom-ForcepointDLPEventsV2_CL',
                },
            })

        with self.assertRaisesRegex(RuntimeError, 'second batch failed'):
            collector.send([{'Id': index} for index in range(50)], '2025-01-01')

        set_date.assert_not_called()

    @patch('CloudHandlers.AzureDataCollector.Persistence.set_date')
    @patch('CloudHandlers.AzureDataCollector.AzureLogsIngestionClient')
    def test_checkpoint_updates_after_success(
            self,
            client_type,
            set_date):
        client_type.return_value.post_data.return_value = Mock(status_code=204)
        collector = AzureDataCollector(
            Mock(),
            config={
                'AzureIngestionMode': 'LogsIngestion',
                'AzureLogsIngestion': {
                    'TenantId': 'tenant',
                    'ClientId': 'client',
                    'ClientSecret': 'secret',
                    'DataCollectionEndpoint': 'https://example.ingest.monitor.azure.com',
                    'DataCollectionRuleImmutableId': 'dcr-123',
                    'StreamName': 'Custom-ForcepointDLPEventsV2_CL',
                },
            })

        collector.send([{'Id': 1}], '2025-01-01')

        set_date.assert_called_once_with('2025-01-01', 'AzureUpdateDate')


if __name__ == '__main__':
    unittest.main()
