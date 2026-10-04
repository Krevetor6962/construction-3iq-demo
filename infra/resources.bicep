targetScope = 'resourceGroup'

param azureRegion string
param foundryRegion string
param deployerPrincipalId string
@allowed(['User', 'ServicePrincipal'])
param deployerPrincipalType string
param deploymentOwnerId string

var suffix = take(uniqueString(subscription().subscriptionId, resourceGroup().name), 8)
var prefix = 'construction3iq'
var tags = {
  application: prefix
  deploymentOwnerId: deploymentOwnerId
  dataClassification: 'synthetic'
}
var roles = {
  blobReader: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
  blobContributor: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  openAIUser: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  aiUser: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
  searchContributor: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
  searchDataContributor: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: '${prefix}-ai-${suffix}'
  location: foundryRegion
  kind: 'AIServices'
  sku: { name: 'S0' }
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: '${prefix}-ai-${suffix}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: '${prefix}-project'
  location: foundryRegion
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Construction 3IQ Demo'
    description: 'Isolated synthetic construction demonstration; no live Microsoft 365 data.'
  }
}

resource chat 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  // Cognitive Services serializes writes to a shared parent account.
  dependsOn: [project]
  name: 'gpt-5.4'
  sku: { name: 'GlobalStandard', capacity: 50 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-5.4', version: '2026-03-05' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  dependsOn: [chat]
  name: 'text-embedding-3-large'
  sku: { name: 'Standard', capacity: 10 }
  properties: {
    model: { format: 'OpenAI', name: 'text-embedding-3-large', version: '1' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: '${prefix}-search-${suffix}'
  location: azureRegion
  sku: { name: 'basic' }
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'Default'
    disableLocalAuth: true
    publicNetworkAccess: 'enabled'
    semanticSearch: 'free'
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: '${prefix}${suffix}'
  location: azureRegion
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  tags: tags
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Disabled'
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: { enabled: true, days: 7 }
    containerDeleteRetentionPolicy: { enabled: true, days: 7 }
  }
}

resource policies 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: blobs
  name: 'policies'
  properties: { publicAccess: 'None' }
}

resource searchBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(policies.id, search.id, roles.blobReader)
  scope: policies
  properties: {
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roles.blobReader
  }
}

resource searchOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, search.id, roles.openAIUser)
  scope: foundry
  properties: {
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roles.openAIUser
  }
}

resource deployerSearchRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in [
  roles.searchContributor
  roles.searchDataContributor
]: {
  name: guid(search.id, deployerPrincipalId, role)
  scope: search
  properties: {
    principalId: deployerPrincipalId
    principalType: deployerPrincipalType
    roleDefinitionId: role
  }
}]

resource deployerBlobWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(policies.id, deployerPrincipalId, roles.blobContributor)
  scope: policies
  properties: {
    principalId: deployerPrincipalId
    principalType: deployerPrincipalType
    roleDefinitionId: roles.blobContributor
  }
}

resource deployerOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, deployerPrincipalId, roles.openAIUser)
  scope: foundry
  properties: {
    principalId: deployerPrincipalId
    principalType: deployerPrincipalType
    roleDefinitionId: roles.openAIUser
  }
}

resource deployerProjectUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(project.id, deployerPrincipalId, roles.aiUser)
  scope: project
  properties: {
    principalId: deployerPrincipalId
    principalType: deployerPrincipalType
    roleDefinitionId: roles.aiUser
  }
}

output azure object = {
  foundryAccountName: foundry.name
  foundryEndpoint: 'https://${foundry.name}.services.ai.azure.com'
  projectName: project.name
  projectEndpoint: 'https://${foundry.name}.services.ai.azure.com/api/projects/${project.name}'
  searchName: search.name
  searchEndpoint: 'https://${search.name}.search.windows.net'
  storageAccountName: storage.name
  storageBlobEndpoint: storage.properties.primaryEndpoints.blob
  policyContainer: policies.name
  chatDeployment: chat.name
  embeddingDeployment: embedding.name
}
