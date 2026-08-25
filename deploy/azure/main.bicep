// Azure infrastructure for the Power BI Platform.
//
// Container Apps rather than App Service: the API image carries the ODBC driver
// and runs as a non-root user, and Container Apps scales the two services
// independently while keeping them on one internal network.
//
// Deploy:
//   az deployment group create -g <rg> -f deploy/azure/main.bicep \
//     -p @deploy/azure/parameters.dev.json

@description('Short environment name; suffixes every resource. Lowercase alphanumeric.')
@minLength(2)
@maxLength(8)
param environmentName string = 'dev'

@description('Azure region for every resource.')
param location string = resourceGroup().location

@description('Administrator login for the SQL logical server.')
param sqlAdminLogin string

@description('Administrator password for the SQL logical server.')
@secure()
param sqlAdminPassword string

@description('Auth.js / JWT signing secret. Must match between the API and the frontend.')
@secure()
param nextAuthSecret string

@description('Fernet key encrypting TOTP secrets and stored client secrets.')
@secure()
param totpEncryptionKey string

@description('Container image for the API, including tag.')
param apiImage string

@description('Container image for the frontend, including tag.')
param applicationImage string

@description('Registry the images are pulled from.')
param containerRegistry string

@description('Deploy a Redis cache. Only needed above one API replica — the poller lock and notification rate limiter degrade gracefully without it.')
param deployRedis bool = false

@description('SKU for both databases. GP_S_Gen5_1 is serverless and pauses when idle.')
param sqlSkuName string = 'GP_S_Gen5_1'

var prefix = 'pbip-${environmentName}'
var tags = { application: 'power-bi-platform', environment: environmentName }

// ── Observability ────────────────────────────────────────────────────────────

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── SQL ──────────────────────────────────────────────────────────────────────

resource sqlServer 'Microsoft.Sql/servers@2023-08-01-preview' = {
  name: '${prefix}-sql'
  location: location
  tags: tags
  properties: {
    administratorLogin: sqlAdminLogin
    administratorLoginPassword: sqlAdminPassword
    // TLS 1.2 is the floor Driver 18 negotiates anyway; pinning it here means a
    // misconfigured client fails at connect rather than silently downgrading.
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
  }
}

// Container Apps egress IPs are not fixed, so the Azure-services rule is what
// lets the API connect. Tighten this to a VNet integration before production.
resource allowAzureServices 'Microsoft.Sql/servers/firewallRules@2023-08-01-preview' = {
  parent: sqlServer
  name: 'AllowAllWindowsAzureIps'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource appDb 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: 'biplatform_app'
  location: location
  tags: tags
  sku: { name: sqlSkuName }
  properties: {
    // The application data is small and mostly metadata; the warehouse is where
    // volume lives, and that is usually a separate system entirely.
    maxSizeBytes: 34359738368
    autoPauseDelay: 60
    minCapacity: json('0.5')
  }
}

resource warehouseDb 'Microsoft.Sql/servers/databases@2023-08-01-preview' = {
  parent: sqlServer
  name: 'biplatform_warehouse'
  location: location
  tags: tags
  sku: { name: sqlSkuName }
  properties: {
    maxSizeBytes: 34359738368
    autoPauseDelay: 60
    minCapacity: json('0.5')
  }
}

// ── Storage (exports, avatars, brand assets) ────────────────────────────────

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: replace('${prefix}stor', '-', '')
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource assetsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'assets'
  properties: { publicAccess: 'None' }
}

// ── Redis (optional) ────────────────────────────────────────────────────────

resource redis 'Microsoft.Cache/redis@2024-03-01' = if (deployRedis) {
  name: '${prefix}-redis'
  location: location
  tags: tags
  properties: {
    sku: { name: 'Basic', family: 'C', capacity: 0 }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
  }
}

// ── Container Apps ──────────────────────────────────────────────────────────

resource containerEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

// Only ever read when deployRedis is true. The `!` asserts the conditional
// resource exists; without it Bicep warns (BCP318/BCP422) that the access could
// evaluate against a null resource, which the ternary already rules out.
var redisUrl = deployRedis
  ? 'rediss://:${redis!.listKeys().primaryKey}@${redis!.properties.hostName}:6380/0'
  : ''

var sqlBase = '${sqlServer.properties.fullyQualifiedDomainName}:1433'
var odbcQuery = 'driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes'
var appDbUrl = 'mssql+aioodbc://${sqlAdminLogin}:${sqlAdminPassword}@${sqlBase}/biplatform_app?${odbcQuery}'
var warehouseDbUrl = 'mssql+aioodbc://${sqlAdminLogin}:${sqlAdminPassword}@${sqlBase}/biplatform_warehouse?${odbcQuery}'

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-api'
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      secrets: concat(
        [
          { name: 'app-database-url', value: appDbUrl }
          { name: 'warehouse-database-url', value: warehouseDbUrl }
          { name: 'nextauth-secret', value: nextAuthSecret }
          { name: 'totp-encryption-key', value: totpEncryptionKey }
          { name: 'storage-connection', value: 'DefaultEndpointsProtocol=https;AccountName=${storage.name};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${az.environment().suffixes.storage}' }
        ],
        deployRedis
          ? [ { name: 'redis-url', value: redisUrl } ]
          : []
      )
      registries: [
        {
          server: containerRegistry
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat(
            [
              { name: 'APP_DATABASE_URL', secretRef: 'app-database-url' }
              { name: 'WAREHOUSE_DATABASE_URL', secretRef: 'warehouse-database-url' }
              { name: 'NEXTAUTH_SECRET', secretRef: 'nextauth-secret' }
              { name: 'TOTP_ENCRYPTION_KEY', secretRef: 'totp-encryption-key' }
              { name: 'AZURE_STORAGE_CONNECTION_STRING', secretRef: 'storage-connection' }
              { name: 'STORAGE_URI', value: 'az://assets' }
              { name: 'ENV', value: 'production' }
              { name: 'CORS_ORIGINS', value: 'https://${prefix}-app.${containerEnv.properties.defaultDomain}' }
            ],
            deployRedis ? [ { name: 'REDIS_URL', secretRef: 'redis-url' } ] : []
          )
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 20
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        // maxReplicas stays at 1 without Redis: a second replica would run the
        // pipeline poller a second time and double-send every alert.
        minReplicas: 1
        maxReplicas: deployRedis ? 3 : 1
      }
    }
  }
  identity: { type: 'SystemAssigned' }
}

resource application 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${prefix}-app'
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: containerEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 3000
        transport: 'auto'
      }
      secrets: [
        { name: 'nextauth-secret', value: nextAuthSecret }
      ]
      registries: [
        {
          server: containerRegistry
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'application'
          image: applicationImage
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'NEXTAUTH_SECRET', secretRef: 'nextauth-secret' }
            { name: 'NEXTAUTH_URL', value: 'https://${prefix}-app.${containerEnv.properties.defaultDomain}' }
            // Also baked into the browser bundle at image build time; set here
            // so the server-side fetches agree with it.
            { name: 'NEXT_PUBLIC_API_URL', value: 'https://${api.properties.configuration.ingress.fqdn}' }
          ]
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 3 }
    }
  }
  identity: { type: 'SystemAssigned' }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output applicationUrl string = 'https://${application.properties.configuration.ingress.fqdn}'
output sqlServerFqdn string = sqlServer.properties.fullyQualifiedDomainName
output storageAccountName string = storage.name
