[CmdletBinding()]
param([switch]$Offline)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path -Parent $PSScriptRoot
$profile = Get-Content -LiteralPath (Join-Path $root 'config\demo-profile.json') -Raw | ConvertFrom-Json
foreach ($field in @('resourceGroup', 'workspaceName', 'subscriptionId', 'tenantId', 'capacityId', 'azureRegion', 'foundryRegion')) {
    if (-not $profile.PSObject.Properties[$field] -or [string]::IsNullOrWhiteSpace($profile.$field)) {
        throw "Profile is missing $field."
    }
}
foreach ($field in @('subscriptionId', 'tenantId', 'capacityId')) { $null = [Guid]::Parse($profile.$field) }
if (-not $Offline) {
    foreach ($field in @('subscriptionId', 'tenantId', 'capacityId')) {
        if ([Guid]::Parse($profile.$field) -eq [Guid]::Empty) {
            throw "Replace the offline placeholder $field in config/demo-profile.json before cloud preflight."
        }
    }
}
if ($profile.resourceGroup -notmatch '^rg-construction-3iq[-a-z0-9]*$') { throw 'The infrastructure requires a new construction3iq resource group.' }
if ($profile.azureRegion -ne 'westus3' -or $profile.foundryRegion -ne 'eastus2') { throw 'This approved infrastructure is West US 3 with Foundry in East US 2.' }
$manifestPath = Join-Path $root 'config\deployment.json'
$manifest = $null
if (Test-Path -LiteralPath $manifestPath) {
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    if ($manifest.schemaVersion -ne 1) { throw 'Unsupported manifest schemaVersion.' }
    foreach ($field in @('resourceGroup', 'workspaceName', 'subscriptionId', 'tenantId', 'capacityId')) {
        if ($manifest.$field -ne $profile.$field) { throw "Manifest $field differs from the selected profile." }
    }
}
if (-not (Get-Command az -ErrorAction SilentlyContinue)) { throw 'Azure CLI is missing; no installation was attempted.' }

function Invoke-AzJson {
    param([string[]]$Arguments)
    $output = & az @Arguments --only-show-errors --output json
    if ($LASTEXITCODE -ne 0) { throw "Read-only Azure CLI check failed: az $($Arguments -join ' ')" }
    return ($output | ConvertFrom-Json)
}

# Calling version first prevents build from auto-installing a missing Bicep CLI.
& az bicep version --only-show-errors
if ($LASTEXITCODE -ne 0) { throw 'Bicep CLI is unavailable; install separately with approval.' }
& az bicep build --file (Join-Path $root 'infra\main.bicep') --stdout --only-show-errors | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Bicep compile failed.' }
Write-Output 'PASS: static profile/manifest checks and Bicep compile.'
if ($Offline) {
    Write-Output 'Cloud readiness NOT assessed (-Offline). No cloud mutation or dependency installation performed.'
    return
}

$account = Invoke-AzJson -Arguments @('account', 'show', '--subscription', $profile.subscriptionId)
if ($account.id -ne $profile.subscriptionId -or $account.tenantId -ne $profile.tenantId -or $account.state -ne 'Enabled') {
    throw 'Azure account context differs from the selected subscription/tenant or is disabled.'
}
foreach ($provider in @('Microsoft.CognitiveServices', 'Microsoft.Search', 'Microsoft.Storage')) {
    $state = Invoke-AzJson -Arguments @('provider', 'show', '--namespace', $provider, '--subscription', $profile.subscriptionId, '--query', 'registrationState')
    if ($state -ne 'Registered') { throw "$provider is not registered. Preflight will not register providers." }
}
$exists = Invoke-AzJson -Arguments @('group', 'exists', '--name', $profile.resourceGroup, '--subscription', $profile.subscriptionId)
if ($exists) {
    if (-not $manifest -or -not $manifest.PSObject.Properties['azureDeployment']) {
        throw 'The configured resource group already exists without an ownership record. Refusing adoption.'
    }
    $group = Invoke-AzJson -Arguments @('group', 'show', '--name', $profile.resourceGroup, '--subscription', $profile.subscriptionId)
    if ($group.id -ne $manifest.azureDeployment.resourceGroupId -or
        -not $group.tags.PSObject.Properties['deploymentOwnerId'] -or
        $group.tags.deploymentOwnerId -ne $manifest.azureDeployment.ownerId) {
        throw 'Existing resource group does not match the manifest ownership ID and resource ID.'
    }
    if ($manifest.azureDeployment.azureRegion -ne $profile.azureRegion -or $manifest.azureDeployment.foundryRegion -ne $profile.foundryRegion) {
        throw 'Recorded deployment regions differ from the approved profile.'
    }
}
$usage = Invoke-AzJson -Arguments @('cognitiveservices', 'usage', 'list', '--location', $profile.foundryRegion, '--subscription', $profile.subscriptionId)
foreach ($model in @(
    @{ Pattern = '^OpenAI\.GlobalStandard\.gpt-5\.4$'; Units = 50 },
    @{ Pattern = '^OpenAI\.Standard\.text-embedding-3-large$'; Units = 10 }
)) {
    $quota = @($usage | Where-Object { $_.name.value -match $model.Pattern })
    if ($quota.Count -ne 1) { throw "Cannot identify exact quota bucket $($model.Pattern); inspect regional quotas before approval." }
    if (-not $exists -and ($quota[0].limit - $quota[0].currentValue) -lt $model.Units) { throw "Insufficient free quota for $($model.Pattern)." }
    Write-Output ("Quota {0}: {1}/{2}, requested {3}. Physical model availability is not guaranteed." -f $quota[0].name.value, $quota[0].currentValue, $quota[0].limit, $model.Units)
}
$models = Invoke-AzJson -Arguments @('cognitiveservices', 'model', 'list', '--location', $profile.foundryRegion, '--subscription', $profile.subscriptionId)
foreach ($required in @(
    @{ Name = 'gpt-5.4'; Version = '2026-03-05'; Sku = 'GlobalStandard' },
    @{ Name = 'text-embedding-3-large'; Version = '1'; Sku = 'Standard' }
)) {
    $match = @($models | Where-Object { $_.kind -eq 'AIServices' -and $_.model.name -eq $required.Name -and $_.model.version -eq $required.Version })
    if ($match.Count -ne 1 -or $required.Sku -notin @($match[0].model.skus.name)) {
        throw "Regional model/SKU unavailable or ambiguous: $($required.Name) $($required.Version) $($required.Sku)."
    }
}

$token = Invoke-AzJson -Arguments @('account', 'get-access-token', '--resource', 'https://api.fabric.microsoft.com', '--subscription', $profile.subscriptionId, '--query', 'accessToken')
function Get-FabricList {
    param([string]$Uri)
    $values = @()
    $seen = @{}
    for ($page = 0; $page -lt 1000; $page++) {
        $parsed = [Uri]$Uri
        if ($parsed.Scheme -ne 'https' -or $parsed.Authority -ne 'api.fabric.microsoft.com' -or $seen.ContainsKey($Uri)) { throw 'Unsafe or repeated Fabric pagination URI.' }
        $seen[$Uri] = $true
        $payload = Invoke-RestMethod -Method Get -Uri $Uri -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 120 -MaximumRedirection 0
        $values += @($payload.value)
        if ($payload.PSObject.Properties['continuationUri'] -and $payload.continuationUri) { $Uri = $payload.continuationUri }
        elseif ($payload.PSObject.Properties['continuationToken'] -and $payload.continuationToken) { throw 'Fabric pagination is incomplete: continuation URI missing.' }
        else { return $values }
    }
    throw 'Fabric pagination exceeded 1000 pages.'
}
$capacities = @(Get-FabricList -Uri 'https://api.fabric.microsoft.com/v1/capacities')
$capacity = @($capacities | Where-Object { $_.id -eq $profile.capacityId })
if ($capacity.Count -ne 1 -or $capacity[0].state -ne 'Active' -or $capacity[0].sku -ne 'F32') { throw 'Selected capacity must be visible, Active, and F32. Preflight never modifies capacity.' }
$workspaces = @(Get-FabricList -Uri 'https://api.fabric.microsoft.com/v1/workspaces')
$sameName = @($workspaces | Where-Object { $_.displayName.Trim() -ieq $profile.workspaceName.Trim() })
if ($manifest -and $manifest.PSObject.Properties['workspaceId'] -and $manifest.workspaceId) {
    $owned = @($workspaces | Where-Object { $_.id -eq $manifest.workspaceId })
    if ($owned.Count -ne 1 -or $owned[0].displayName -cne $profile.workspaceName -or $owned[0].capacityId -ne $profile.capacityId) { throw 'Owned workspace ID/name/capacity mismatch.' }
} elseif ($sameName.Count -gt 0) { throw 'A same-named unowned workspace exists. Refusing adoption.' }
Remove-Variable token
Write-Output 'PASS: read-only account, ownership, providers, quota/model catalog and capacity checks.'
Write-Output 'NOT PROVEN: current prices, globally unique name availability, deployer effective RBAC, tenant preview enablement, physical model capacity, ontology import/query and delegated IQ retrieval. Separate deployment approval remains required.'
