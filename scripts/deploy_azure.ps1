[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][Guid]$DeployerPrincipalId,
    [ValidateSet('User', 'ServicePrincipal')][string]$DeployerPrincipalType = 'User',
    [string]$PythonExecutable,
    [switch]$ApproveProvisioning
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $ApproveProvisioning) { throw 'Separate cloud deployment approval is required. Pass -ApproveProvisioning only after that approval.' }
$root = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) { $PythonExecutable = Join-Path $root '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $PythonExecutable)) { throw 'Python interpreter not found. Specify -PythonExecutable; no dependency installation is automatic.' }
$profile = Get-Content -LiteralPath (Join-Path $root 'config\demo-profile.json') -Raw | ConvertFrom-Json
& (Join-Path $PSScriptRoot 'preflight.ps1')

function Invoke-AzJson {
    param([string[]]$Arguments)
    $output = & az @Arguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) { throw "Azure CLI failed: az $($Arguments -join ' ')" }
    return ($output | ConvertFrom-Json)
}
function Merge-Manifest {
    param([object]$Updates)
    $temporary = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($temporary, ($Updates | ConvertTo-Json -Depth 40), (New-Object Text.UTF8Encoding $false))
        & $PythonExecutable -m construction_iq.fabric_api --merge $temporary
        if ($LASTEXITCODE -ne 0) { throw 'Atomic manifest merge failed. No other workstream fields were intentionally replaced.' }
    } finally {
        Remove-Item -LiteralPath $temporary -Force
    }
}

$savedPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $root 'src'
$parametersPath = [IO.Path]::GetTempFileName()
try {
    $manifestPath = Join-Path $root 'config\deployment.json'
    $manifest = $null
    if (Test-Path -LiteralPath $manifestPath) { $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json }
    if ($manifest -and $manifest.PSObject.Properties['azureDeployment']) {
        $ownership = $manifest.azureDeployment
    } else {
        $ownership = @{
            ownerId = [Guid]::NewGuid().ToString()
            resourceGroupId = "/subscriptions/$($profile.subscriptionId)/resourceGroups/$($profile.resourceGroup)"
            azureRegion = $profile.azureRegion
            foundryRegion = $profile.foundryRegion
            deploymentName = 'construction3iq-infrastructure'
            state = 'pending'
        }
        Merge-Manifest -Updates @{ azureDeployment = $ownership }
    }
    $parameters = @{
        '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters = @{
            resourceGroupName = @{ value = $profile.resourceGroup }
            azureRegion = @{ value = $profile.azureRegion }
            foundryRegion = @{ value = $profile.foundryRegion }
            deployerPrincipalId = @{ value = $DeployerPrincipalId.ToString() }
            deployerPrincipalType = @{ value = $DeployerPrincipalType }
            deploymentOwnerId = @{ value = $ownership.ownerId }
        }
    }
    [IO.File]::WriteAllText($parametersPath, ($parameters | ConvertTo-Json -Depth 10), (New-Object Text.UTF8Encoding $false))
    $deployment = Invoke-AzJson -Arguments @(
        'deployment', 'sub', 'create', '--subscription', $profile.subscriptionId,
        '--name', $ownership.deploymentName, '--location', $profile.azureRegion,
        '--template-file', (Join-Path $root 'infra\main.bicep'), '--parameters', "@$parametersPath"
    )
    if ($deployment.properties.provisioningState -ne 'Succeeded') { throw 'ARM did not report a successful deployment.' }
    $outputs = $deployment.properties.outputs
    if ($outputs.resourceGroupId.value -ne $ownership.resourceGroupId) { throw 'ARM output group ID differs from the recorded new target.' }
    foreach ($key in @('foundryAccountName', 'foundryEndpoint', 'projectName', 'projectEndpoint', 'searchName', 'searchEndpoint', 'storageAccountName', 'storageBlobEndpoint', 'policyContainer', 'chatDeployment', 'embeddingDeployment')) {
        if (-not $outputs.azure.value.PSObject.Properties[$key] -or [string]::IsNullOrWhiteSpace($outputs.azure.value.$key)) { throw "ARM omitted azure.$key; manifest was not marked complete." }
    }
    Merge-Manifest -Updates @{ azure = $outputs.azure.value; azureDeployment = @{ state = 'succeeded'; deploymentId = $deployment.id } }
    Write-Output "Azure outputs saved atomically to $manifestPath. Fabric and IQ validation are separate requirements."
} finally {
    $env:PYTHONPATH = $savedPythonPath
    Remove-Item -LiteralPath $parametersPath -Force
}
