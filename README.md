# Forcepoint DLP exporter

This Windows service reads incidents from the Forcepoint Security Manager SQL database and exports them to:

- Microsoft Sentinel through either the legacy HTTP Data Collector API or the Azure Monitor Logs Ingestion API.
- Amazon Web Services Security Hub.

## Microsoft Sentinel ingestion modes

Existing installations remain compatible. `AzureIngestionMode` defaults to `Legacy` when the setting is absent.

### Azure Monitor Logs Ingestion API

Use this mode with the Microsoft Sentinel **Forcepoint DLP via AMA** CCF push connector. The connector provisions the custom table, Data Collection Endpoint (DCE), Data Collection Rule (DCR), Microsoft Entra application, and role assignment required by the exporter.

Set these values in `Config.json`:

```json
{
  "AzureIngestionMode": "LogsIngestion",
  "AzureLogsIngestion": {
    "TenantId": "<Microsoft Entra tenant ID>",
    "ClientId": "<application/client ID>",
    "ClientSecret": "<client secret>",
    "DataCollectionEndpoint": "https://<dce-name>.<region>-1.ingest.monitor.azure.com",
    "DataCollectionRuleImmutableId": "dcr-<immutable-id>",
    "StreamName": "Custom-ForcepointDLPEventsV2_CL"
  }
}
```

The exporter:

1. Obtains a bearer token from Microsoft Entra ID by using the OAuth 2.0 client-credentials flow and the `https://monitor.azure.com/.default` scope.
2. Sends JSON arrays to the DCR stream by using Logs Ingestion API version `2023-01-01`.
3. Normalizes the legacy Forcepoint numbered keys. For example, `RuleName.1` becomes `RuleName`; additional numbered values are retained in `AdditionalFields`.
4. Retries throttling and transient service failures.
5. Advances the local Azure database checkpoint only after every batch is accepted.

The client secret grants data-ingestion access. Store `Config.json` with Windows file permissions limited to the service account, never add populated configuration files to source control, and rotate the secret according to your organization's policy.

### Legacy HTTP Data Collector API

For an existing installation, retain:

```json
{
  "AzureIngestionMode": "Legacy",
  "AzureWorkspaceID": "<workspace ID>",
  "AzurePrimaryKey": "<workspace shared key>",
  "LogName": "ForcepointDLPEvents"
}
```

This mode preserves the existing payload and SharedKey authentication behavior. To migrate, deploy the CCF connector first, copy its DCE/DCR and Microsoft Entra values into `Config.json`, and then change `AzureIngestionMode` to `LogsIngestion`.

## Database configuration

```json
{
  "Database_Connection": {
    "Server": "SERVER",
    "Database": "db",
    "Trusted_Connection": "yes",
    "UID": "",
    "PWD": ""
  }
}
```

The exporter uses Microsoft ODBC Driver 17 for SQL Server. Use `Trusted_Connection: "yes"` for Windows authentication. For SQL authentication, set it to `"no"` and configure the username/password through the installer.

## Build the Windows package

Run `makeFile.ps1` in Windows PowerShell. The script installs the pinned Python dependencies, builds `Service.exe` and `DLPExporter.exe` with PyInstaller, and creates:

`fp-dlp-exporter-aws-azure-v2-0-0.zip`

## Tests

Run the standard-library unit tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```
