#!/usr/bin/env python3
import collections

from Config import Configurations, Persistence
from CloudHandlers.AzureLogsIngestion import AzureLogsIngestionClient
from datacollectorapiMOD import client


LEGACY_MODE = 'legacy'
LOGS_INGESTION_MODE = 'logsingestion'


def is_azure_configured(config):
    mode = get_azure_mode(config)
    if mode == LOGS_INGESTION_MODE:
        logs_config = config.get('AzureLogsIngestion', {})
        return all([
            logs_config.get('TenantId'),
            logs_config.get('ClientId'),
            logs_config.get('ClientSecret'),
            logs_config.get('DataCollectionEndpoint'),
            logs_config.get('DataCollectionRuleImmutableId'),
            logs_config.get('StreamName'),
        ])

    return bool(config.get('AzureWorkspaceID') and config.get('AzurePrimaryKey') and config.get('LogName'))


def get_azure_mode(config):
    return str(config.get('AzureIngestionMode', LEGACY_MODE)).strip().lower()


class AzureDataCollector:
    def __init__(self, logger_obj, config=None):
        self.config = config or Configurations.get_configurations()
        self.logger_obj = logger_obj
        self.mode = get_azure_mode(self.config)

        if self.mode == LOGS_INGESTION_MODE:
            logs_config = self.config.get('AzureLogsIngestion', {})
            self.api = AzureLogsIngestionClient(
                tenant_id=logs_config.get('TenantId'),
                client_id=logs_config.get('ClientId'),
                client_secret=logs_config.get('ClientSecret'),
                data_collection_endpoint=logs_config.get('DataCollectionEndpoint'),
                data_collection_rule_immutable_id=logs_config.get('DataCollectionRuleImmutableId'),
                stream_name=logs_config.get('StreamName'))
        elif self.mode == LEGACY_MODE:
            self.api = client.DataCollectorAPIClient(
                self.config.get('AzureWorkspaceID'),
                self.config.get('AzurePrimaryKey'))
        else:
            raise ValueError(
                "AzureIngestionMode must be '{}' or '{}'".format(LEGACY_MODE, LOGS_INGESTION_MODE))

    def health_check(self):
        if self.mode == LOGS_INGESTION_MODE:
            return self.api.health_check()

        result = self.api.health_check(self.config.get('LogName'))
        return result.status_code != 500

    def send(self, json_records, offset_time):
        numbers_deque = collections.deque(json_records)

        while numbers_deque:
            batch_size = min(49, len(numbers_deque))
            send_list = [numbers_deque.popleft() for _i in range(batch_size)]
            self._send_batch(send_list)

        if offset_time is not None:
            Persistence().set_date(str(offset_time), 'AzureUpdateDate')

    def _send_batch(self, send_list):
        if self.mode == LOGS_INGESTION_MODE:
            result = self.api.post_data(send_list, timeout=30.0)
        else:
            result = self.api.post_data(
                self.config.get('LogName'),
                send_list,
                timeout=30.0)

        if result.status_code not in (200, 204):
            raise RuntimeError('Azure ingestion request failed with status {}'.format(result.status_code))
        else:
            self.logger_obj.info('Successful Azure ingestion response: {}'.format(result.status_code))
