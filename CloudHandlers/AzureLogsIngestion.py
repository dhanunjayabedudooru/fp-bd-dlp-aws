#!/usr/bin/env python3
import json
import re
import time
from urllib.parse import quote

import requests


LOGS_INGESTION_API_VERSION = '2023-01-01'
LOGS_INGESTION_SCOPE = 'https://monitor.azure.com/.default'
TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}

EXPECTED_SOURCE_FIELDS = {
    'AdditionalFields',
    'CreatedAt',
    'Description',
    'DestinationCommonName',
    'DestinationDomain',
    'DestinationEmail',
    'DestinationExtraData',
    'DestinationHostname',
    'DestinationIpV4',
    'DestinationPort',
    'ExternalId',
    'ForcepointDLPSourceIP',
    'GeneratorId',
    'Id',
    'PolicyCategoryId',
    'Protocol',
    'RuleName',
    'Severity',
    'SourceDomain',
    'SourceEmail',
    'SourceExtraData',
    'SourceFullName',
    'SourceHostname',
    'SourceIpV4',
    'SourceLoginName',
    'SourcePort',
    'Text',
    'Title',
    'TransactionSizeInBytes',
    'Type',
    'UpdatedAt',
    'UpdatedBy',
}

NUMBERED_FIELD_PATTERN = re.compile(r'^(?P<name>.+)\.(?P<index>\d+)$')


def normalize_record(record):
    normalized = {}
    additional_fields = dict(record.get('AdditionalFields') or {})

    for key, value in record.items():
        if key == 'AdditionalFields':
            continue

        if key in EXPECTED_SOURCE_FIELDS:
            normalized[key] = value
            continue

        numbered_match = NUMBERED_FIELD_PATTERN.match(key)
        if numbered_match:
            base_name = numbered_match.group('name')
            index = numbered_match.group('index')
            if index == '1' and base_name in EXPECTED_SOURCE_FIELDS and base_name not in normalized:
                normalized[base_name] = value
            else:
                additional_fields[key] = value
            continue

        additional_fields[key] = value

    if additional_fields:
        normalized['AdditionalFields'] = additional_fields

    return normalized


def normalize_records(records):
    return [normalize_record(record) for record in records]


class AzureLogsIngestionClient:
    def __init__(
            self,
            tenant_id,
            client_id,
            client_secret,
            data_collection_endpoint,
            data_collection_rule_immutable_id,
            stream_name,
            session=None,
            sleep=None,
            time_provider=None,
            max_retries=3):
        required_values = {
            'TenantId': tenant_id,
            'ClientId': client_id,
            'ClientSecret': client_secret,
            'DataCollectionEndpoint': data_collection_endpoint,
            'DataCollectionRuleImmutableId': data_collection_rule_immutable_id,
            'StreamName': stream_name,
        }
        missing_values = [name for name, value in required_values.items() if not value]
        if missing_values:
            raise ValueError(
                'Missing required Azure Logs Ingestion configuration: {}'.format(', '.join(missing_values)))

        if not data_collection_endpoint.lower().startswith('https://'):
            raise ValueError('DataCollectionEndpoint must use HTTPS')

        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.data_collection_endpoint = data_collection_endpoint.rstrip('/')
        self.data_collection_rule_immutable_id = data_collection_rule_immutable_id
        self.stream_name = stream_name
        self.session = session or requests.Session()
        self.sleep = sleep or time.sleep
        self.time_provider = time_provider or time.time
        self.max_retries = max_retries
        self.access_token = None
        self.access_token_expires_at = 0

    def health_check(self):
        self._get_access_token()
        return True

    def post_data(self, records, timeout=30.0):
        if not isinstance(records, list):
            raise ValueError('Logs Ingestion payload must be a JSON array')

        normalized_records = normalize_records(records)
        body = json.dumps(normalized_records)

        for attempt in range(self.max_retries + 1):
            response = self.session.post(
                self._build_ingestion_url(),
                data=body,
                headers={
                    'Authorization': 'Bearer {}'.format(self._get_access_token()),
                    'Content-Type': 'application/json',
                    'User-Agent': 'SentinelPartner-Forcepoint-DLP/2.0',
                },
                timeout=timeout)

            if response.status_code in (200, 204):
                return response

            if response.status_code == 401 and attempt < self.max_retries:
                self.access_token = None
                self.access_token_expires_at = 0
                continue

            if response.status_code in TRANSIENT_STATUS_CODES and attempt < self.max_retries:
                self.sleep(self._get_retry_delay(response, attempt))
                continue

            raise RuntimeError(
                'Azure Logs Ingestion API request failed with status {}: {}'.format(
                    response.status_code,
                    response.text))

        raise RuntimeError('Azure Logs Ingestion API request failed after all retry attempts')

    def _build_ingestion_url(self):
        return (
            '{}/dataCollectionRules/{}/streams/{}?api-version={}'.format(
                self.data_collection_endpoint,
                quote(self.data_collection_rule_immutable_id, safe=''),
                quote(self.stream_name, safe=''),
                LOGS_INGESTION_API_VERSION))

    def _get_access_token(self):
        if self.access_token and self.time_provider() < self.access_token_expires_at:
            return self.access_token

        token_url = 'https://login.microsoftonline.com/{}/oauth2/v2.0/token'.format(
            quote(self.tenant_id, safe=''))
        response = None
        for attempt in range(self.max_retries + 1):
            response = self.session.post(
                token_url,
                data={
                    'client_id': self.client_id,
                    'client_secret': self.client_secret,
                    'scope': LOGS_INGESTION_SCOPE,
                    'grant_type': 'client_credentials',
                },
                timeout=30.0)

            if response.status_code == 200:
                break
            if response.status_code in TRANSIENT_STATUS_CODES and attempt < self.max_retries:
                self.sleep(self._get_retry_delay(response, attempt))
                continue
            raise RuntimeError(
                'Microsoft Entra token request failed with status {}: {}'.format(
                    response.status_code,
                    response.text))

        token_response = response.json()
        access_token = token_response.get('access_token')
        if not access_token:
            raise RuntimeError('Microsoft Entra token response did not contain an access_token')

        expires_in = int(token_response.get('expires_in', 3600))
        refresh_buffer = min(300, max(0, expires_in // 2))
        self.access_token = access_token
        self.access_token_expires_at = self.time_provider() + expires_in - refresh_buffer
        return self.access_token

    @staticmethod
    def _get_retry_delay(response, attempt):
        retry_after = response.headers.get('Retry-After')
        if retry_after:
            try:
                return max(0, int(retry_after))
            except ValueError:
                pass
        return min(30, 2 ** attempt)
