Write-Output [96m Installing PIP[0m
Write-Output [96m----------------[0m
Write-Output -
Write-Output -
$source = 'https://bootstrap.pypa.io/get-pip.py'
$destination = 'Resources\get-pip.py'
Invoke-WebRequest -Uri $source -OutFile $destination
python Resources\get-pip.py

Write-Output [96m Installing required packages[0m
Write-Output [96m-----------------------------[0m
Write-Output -
Write-Output -
python -m pip install -r requirements.txt

$AESKey = New-Object Byte[] 32
[Security.Cryptography.RNGCryptoServiceProvider]::Create().GetBytes($AESKey)
python add_key.py --key=$AESKey

Write-Output [96m Creating python exe[0m
Write-Output [96m-----------------------------[0m
Write-Output -
Write-Output -
pyinstaller --onefile Service.py
pyinstaller --onefile --key "$AESKey" DLPExporter.py

Write-Output [96m Choose modules to be installed[0m
Write-Output [96m--------------------------------[0m
Write-Output .
$azure=Read-Host "Do you want azure configured on y/n?"
$aws=Read-Host "Do you want aws configured on y/n?"

$packageDirectory = ".\fp-dlp-exporter-aws-azure-v2"
$packageZip = ".\fp-dlp-exporter-aws-azure-v2-0-0.zip"

Write-Output [96m Creating required directories[0m
Write-Output [96m-----------------------------[0m
Write-Output -
Write-Output -
New-Item -ItemType Directory -Path $packageDirectory
New-Item -ItemType Directory -Path "$packageDirectory\CloudFormationTemplate"
New-Item -ItemType Directory -Path "$packageDirectory\Remediation_script"
New-Item -ItemType Directory -Path "$packageDirectory\Resources"
xcopy .\Resources "$packageDirectory\Resources" /s /e
Move-Item .\dist\DLPExporter.exe $packageDirectory
Move-Item .\dist\Service.exe $packageDirectory
Move-Item "$packageDirectory\Resources\install.bat" $packageDirectory
New-Item -ItemType Directory -Path "$packageDirectory\ServiceScripts"
Move-Item "$packageDirectory\Resources\restart.bat" "$packageDirectory\ServiceScripts"
Move-Item "$packageDirectory\Resources\stopService.bat" "$packageDirectory\ServiceScripts"
Move-Item "$packageDirectory\Resources\removeService.bat" "$packageDirectory\ServiceScripts"
Move-Item "$packageDirectory\Resources\changePassword.bat" "$packageDirectory\ServiceScripts"
xcopy .\CloudFormationTemplate "$packageDirectory\CloudFormationTemplate" /s /e
xcopy .\Remediation_script "$packageDirectory\Remediation_script" /s /e
Copy-Item .\config.json $packageDirectory
Remove-Item -Path "$packageDirectory\Resources\get-pip.py" -Recurse

$awsInstall=$false

if ($aws -eq 'y' -or $aws -eq "Y") {
    $awsInstall=$true
}
if ($awsInstall -eq $false) {
    Remove-Item -Path "$packageDirectory\Resources\AWSDate.json" -Recurse
    Remove-Item -Path "$packageDirectory\Resources\Insights.json" -Recurse
    Remove-Item -Path "$packageDirectory\Resources\InsightARN.json" -Recurse
    Remove-Item -Path "$packageDirectory\CloudFormationTemplate" -Recurse
    Remove-Item -Path "$packageDirectory\Remediation_script" -Recurse
    $config = Get-Content -Raw "$packageDirectory\config.json" | ConvertFrom-Json
    @('AwsAccountId', 'ProductArn', 'aws_access_key_id', 'aws_secret_access_key', 'region_name') |
        ForEach-Object { $config.PSObject.Properties.Remove($_) }
    $config | ConvertTo-Json -Depth 10 | Set-Content "$packageDirectory\config.json"
}

$azureInstall=$false

if ($azure -eq 'y' -or $azure -eq "Y") {
    $azureInstall=$true
}
if ($azureInstall -eq $false) {
    Remove-Item -Path "$packageDirectory\Resources\azureDate.json" -Recurse
    $config = Get-Content -Raw "$packageDirectory\config.json" | ConvertFrom-Json
    @('AzureIngestionMode', 'AzureWorkspaceID', 'AzurePrimaryKey', 'LogName', 'AzureLogsIngestion') |
        ForEach-Object { $config.PSObject.Properties.Remove($_) }
    $config | ConvertTo-Json -Depth 10 | Set-Content "$packageDirectory\config.json"
}


Write-Output [96m Creating fp-dlp-exporter-aws-azure-v2-0-0.zip[0m
Write-Output [96m-----------------------------[0m
Write-Output -
Write-Output -
Compress-Archive $packageDirectory $packageZip


Write-Output [96m Clean up[0m
Write-Output [96m-----------------------------[0m
Write-Output -
Write-Output -
Remove-Item -Path .\__pycache__ -Recurse
Remove-Item -Path $packageDirectory -Recurse
Remove-Item -Path .\build -Recurse
Remove-Item -Path .\dist -Recurse
Remove-Item -Path .\DLPExporter.spec -Recurse
Remove-Item -Path .\Service.spec -Recurse
Remove-Item -Path .\Resources\get-pip.py -Recurse
python add_key.py --key=None