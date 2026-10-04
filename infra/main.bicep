targetScope = 'subscription'

@description('Must match config/demo-profile.json. The deployment script refuses an unowned existing group.')
param resourceGroupName string
param azureRegion string
param foundryRegion string
param deployerPrincipalId string
@allowed(['User', 'ServicePrincipal'])
param deployerPrincipalType string = 'User'
param deploymentOwnerId string

resource demoGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: azureRegion
  tags: {
    application: 'construction3iq'
    deploymentOwnerId: deploymentOwnerId
    dataClassification: 'synthetic'
  }
}

module services './resources.bicep' = {
  name: 'construction3iq-services'
  scope: demoGroup
  params: {
    azureRegion: azureRegion
    foundryRegion: foundryRegion
    deployerPrincipalId: deployerPrincipalId
    deployerPrincipalType: deployerPrincipalType
    deploymentOwnerId: deploymentOwnerId
  }
}

output resourceGroupId string = demoGroup.id
output azure object = services.outputs.azure
