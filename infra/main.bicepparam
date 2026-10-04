using './main.bicep'

// The deploy script supplies profile-derived values; these environment variables are for manual compilation.
param resourceGroupName = readEnvironmentVariable('CONSTRUCTION_RESOURCE_GROUP')
param azureRegion = readEnvironmentVariable('CONSTRUCTION_AZURE_REGION')
param foundryRegion = readEnvironmentVariable('CONSTRUCTION_FOUNDRY_REGION')
param deployerPrincipalId = readEnvironmentVariable('CONSTRUCTION_DEPLOYER_OBJECT_ID')
param deployerPrincipalType = 'User'
param deploymentOwnerId = readEnvironmentVariable('CONSTRUCTION_DEPLOYMENT_OWNER_ID')
