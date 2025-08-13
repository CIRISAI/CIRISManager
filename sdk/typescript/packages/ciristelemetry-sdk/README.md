# CIRIS Telemetry SDK

Comprehensive TypeScript SDK for the CIRIS Telemetry System. Provides type-safe access to all telemetry endpoints with built-in caching, retry logic, and WebSocket support.

## Installation

```bash
npm install @cirisai/ciristelemetry-sdk
# or
yarn add @cirisai/ciristelemetry-sdk
```

## Quick Start

```typescript
import { quickStart } from '@cirisai/ciristelemetry-sdk';

// Create a client with convenience methods
const telemetry = quickStart('https://agents.ciris.ai', 'your-api-key');

// Get system health
const health = await telemetry.getHealth();

// Get current status
const status = await telemetry.getStatus();

// Detect anomalies
const anomalies = await telemetry.analytics.detectAnomalies();

// Get unhealthy agents
const unhealthy = await telemetry.monitoring.getUnhealthyAgents();
```

## Full Client Usage

```typescript
import { CIRISTelemetryClient } from '@cirisai/ciristelemetry-sdk';

const client = new CIRISTelemetryClient({
  baseUrl: 'https://agents.ciris.ai',
  apiKey: 'your-api-key',
  timeout: 30000,
  retryAttempts: 3,
  retryDelay: 1000,
  enableCache: true,
  cacheTimeout: 60000
});

// Health & Status
const health = await client.getHealth();
const status = await client.getStatus();
const orchestratorStats = await client.getOrchestratorStats();

// Historical Data
const history = await client.getHistory(24, '5m');
const agentMetrics = await client.getAgentMetrics('agent-name', 24);
const containerMetrics = await client.getContainerMetrics('container-name', 24);

// Public API (sanitized data)
const publicStatus = await client.getPublicStatus();
const publicHistory = await client.getPublicHistory(24, 5);

// Complex Queries
const response = await client.query({
  query_type: 'timeseries',
  metric_name: 'cpu_percent',
  time_range: {
    start: '2025-01-01T00:00:00Z',
    end: '2025-01-02T00:00:00Z'
  },
  interval: '1h'
});

// Management
const triggerResult = await client.triggerCollection();
const cleanupResult = await client.cleanupOldData(30);
```

## Monitoring API

```typescript
import { MonitoringAPI } from '@cirisai/ciristelemetry-sdk';

const monitoring = new MonitoringAPI(client.axios);

// Real-time monitoring
const allAgents = await monitoring.getAllAgentsStatus();
const allContainers = await monitoring.getAllContainersStatus();

// Filter by state
const workingAgents = await monitoring.getAgentsByCognitiveState(CognitiveState.WORK);
const unhealthyAgents = await monitoring.getUnhealthyAgents();
const unhealthyContainers = await monitoring.getContainersByHealth(HealthStatus.UNHEALTHY);

// Resource monitoring
const highCpu = await monitoring.getHighResourceContainers(80, 80);
const resourceSummary = await monitoring.getResourceSummary();

// Incidents & Costs
const incidentAgents = await monitoring.getAgentsWithIncidents(24);
const costBreakdown = await monitoring.getCostBreakdown();

// Cognitive state distribution
const distribution = await monitoring.getCognitiveStateDistribution();
```

## Analytics API

```typescript
import { AnalyticsAPI } from '@cirisai/ciristelemetry-sdk';

const analytics = new AnalyticsAPI(client.axios);

// Trend Analysis
const cpuTrend = await analytics.analyzeTrend('cpu_percent', 24);
console.log(`CPU trend: ${cpuTrend.trend}, change: ${cpuTrend.changePercent}%`);

// Anomaly Detection
const anomalies = await analytics.detectAnomalies(1);
anomalies.forEach(anomaly => {
  console.log(`Anomaly detected: ${anomaly.metric} = ${anomaly.value} (severity: ${anomaly.severity})`);
});

// Performance Baselines
const baselines = await analytics.calculateBaselines(
  ['cpu_percent', 'memory_mb', 'response_time_ms'],
  7
);

// Agent Performance Analysis
const performance = await analytics.analyzeAgentPerformance('agent-name', 7);
console.log(`Availability: ${performance.availability}%`);
console.log(`Avg Response Time: ${performance.averageResponseTime}ms`);

// Compare Agents
const comparison = await analytics.compareAgents(
  ['agent1', 'agent2', 'agent3'],
  'response_time',
  24
);

// Resource Usage Prediction
const prediction = await analytics.predictResourceUsage(24);
console.log(`Predicted CPU: ${prediction.predictedCpu}%`);
console.log(`Recommendation: ${prediction.recommendation}`);
```

## WebSocket Support

```typescript
// Connect to real-time telemetry stream
client.connectWebSocket(
  (message) => {
    console.log('Received telemetry:', message);
    
    switch (message.type) {
      case 'snapshot':
        // Handle full snapshot
        break;
      case 'delta':
        // Handle incremental update
        break;
      case 'alert':
        // Handle alert
        break;
      case 'status':
        // Handle status update
        break;
    }
  },
  (error) => {
    console.error('WebSocket error:', error);
  }
);

// Subscribe to specific metrics
client.subscribe({
  id: 'cpu-monitor',
  metrics: ['cpu_percent', 'memory_percent'],
  interval: 5000,
  filters: {
    threshold: 80
  }
});

// Unsubscribe
client.unsubscribe('cpu-monitor');

// Disconnect
client.disconnectWebSocket();
```

## Error Handling

```typescript
import { TelemetryError, CollectionError, StorageError } from '@cirisai/ciristelemetry-sdk';

try {
  const status = await client.getStatus();
} catch (error) {
  if (error instanceof CollectionError) {
    console.error('Telemetry collection unavailable:', error.message);
  } else if (error instanceof StorageError) {
    console.error('Storage error:', error.message);
  } else if (error instanceof TelemetryError) {
    console.error(`Telemetry error (${error.statusCode}):`, error.message);
  } else {
    console.error('Unexpected error:', error);
  }
}
```

## Caching

The SDK includes built-in caching to reduce API calls:

```typescript
// Enable caching in options
const client = new CIRISTelemetryClient({
  baseUrl: 'https://agents.ciris.ai',
  enableCache: true,
  cacheTimeout: 60000 // 1 minute default
});

// Clear cache manually
client.clearCache();

// Cache is automatically cleared after triggering collection
await client.triggerCollection(); // Clears cache
```

## TypeScript Support

The SDK is fully typed with comprehensive TypeScript definitions:

```typescript
import {
  // Main types
  SystemSummary,
  AgentOperationalMetrics,
  ContainerMetrics,
  DeploymentMetrics,
  
  // Enums
  ContainerStatus,
  HealthStatus,
  CognitiveState,
  DeploymentStatus,
  DeploymentPhase,
  
  // Response types
  HealthResponse,
  TriggerResponse,
  PublicStatus,
  
  // Error types
  TelemetryError,
  CollectionError,
  StorageError
} from '@cirisai/ciristelemetry-sdk';
```

## Browser Usage

Include the browser bundle:

```html
<script src="https://unpkg.com/axios/dist/axios.min.js"></script>
<script src="https://unpkg.com/@cirisai/ciristelemetry-sdk/dist/ciristelemetry-sdk.min.js"></script>
<script>
  const client = new CIRISTelemetry({
    baseUrl: 'https://agents.ciris.ai',
    apiKey: 'your-api-key'
  });
  
  client.getStatus().then(status => {
    console.log('System status:', status);
  });
</script>
```

## API Reference

### Client Options

- `baseUrl` (string): Base URL for the telemetry API
- `apiKey` (string, optional): API key for authentication
- `timeout` (number, optional): Request timeout in ms (default: 30000)
- `retryAttempts` (number, optional): Number of retry attempts (default: 3)
- `retryDelay` (number, optional): Delay between retries in ms (default: 1000)
- `enableCache` (boolean, optional): Enable response caching (default: false)
- `cacheTimeout` (number, optional): Cache timeout in ms (default: 60000)

### Methods

See the [API documentation](https://github.com/CIRISAI/CIRISManager/blob/main/docs/telemetry-api.md) for complete method reference.

## License

MIT