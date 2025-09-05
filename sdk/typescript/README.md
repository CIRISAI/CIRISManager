# CIRIS Manager TypeScript SDK

Type-safe TypeScript SDK for interacting with the CIRIS Manager API.

## Architecture

The SDK is structured in three layers:

1. **API Documentation** (`api-spec/ciris-manager-api.yaml`)
   - OpenAPI 3.1 specification
   - Single source of truth for API contract
   - Auto-generates TypeScript types

2. **SDK Layer** (`@ciris/cirismanager-sdk`)
   - Type-safe client implementation
   - Error handling and retries
   - Real-time updates support
   - Modular API organization

3. **UI Integration**
   - Replace direct fetch calls with SDK
   - Consistent error handling
   - Type safety throughout

## Installation

```bash
cd sdk/typescript/packages/cirismanager-sdk
npm install
npm run generate  # Generate types from OpenAPI spec
npm run build
```

## Usage

### Basic Setup

```typescript
import { CIRISManagerClient } from '@ciris/cirismanager-sdk';

const client = new CIRISManagerClient({
  baseURL: '/manager/v1',
  timeout: 30000,
  retries: 3,
  onAuthFailure: () => {
    window.location.href = '/manager/v1/login';
  }
});
```

### Agent Management

```typescript
// List agents
const agents = await client.agents.list();

// Create agent
const newAgent = await client.agents.create({
  agent_name: 'my-agent',
  template: 'default',
  memory_limit: '1G'
});

// Control agents
await client.agents.start('agent-id');
await client.agents.stop('agent-id');
await client.agents.restart('agent-id');

// Update configuration
await client.agents.updateConfig('agent-id', {
  environment: {
    NEW_VAR: 'value'
  }
});
```

### Deployment Management

```typescript
// Check deployment status
const status = await client.deployments.getStatus();

// Launch deployment
const deployment = await client.deployments.launch('deployment-id');

// Watch deployment progress
const unsubscribe = client.deployments.watchDeployment(
  deployment.deployment_id,
  (status) => {
    console.log(`Progress: ${status.agents_updated}/${status.agents_total}`);
  }
);

// Rollback
await client.deployments.rollback({
  target_version: 'n-1',
  reason: 'Critical issue detected'
});
```

### Telemetry Access

```typescript
// Get current metrics
const metrics = await client.telemetry.getStatus();

// Get historical data
const history = await client.telemetry.getHistory({
  hours: 24,
  interval: '5m'
});

// Stream real-time updates
const unsubscribe = client.telemetry.streamMetrics(
  (metrics) => {
    updateDashboard(metrics);
  },
  5000 // Update every 5 seconds
);
```

## Error Handling

The SDK provides typed error classes:

```typescript
import {
  CIRISError,
  AuthenticationError,
  NotFoundError,
  ConflictError
} from '@ciris/cirismanager-sdk';

try {
  await client.agents.create({ ... });
} catch (error) {
  if (error instanceof ConflictError) {
    // Agent already exists
  } else if (error instanceof AuthenticationError) {
    // Need to re-authenticate
  } else if (error instanceof NetworkError) {
    // Network issue, maybe retry
  }
}
```

## Real-time Updates

The SDK supports real-time updates through WebSocket (future) and polling:

```typescript
// Watch agent status
const unsubscribe = client.agents.watchStatus('agent-id', (status) => {
  updateUI(status);
});

// Clean up when done
unsubscribe();
```

## Type Safety

All API responses are fully typed:

```typescript
import { Agent, DeploymentStatus, SystemSummary } from '@ciris/cirismanager-sdk';

const agent: Agent = await client.agents.get('agent-id');
// TypeScript knows all properties of agent

const status: DeploymentStatus = await client.deployments.getStatus();
// Full intellisense for deployment properties
```

## Migration Guide

### Before (Direct Fetch)

```javascript
// Old approach - no type safety, manual error handling
async function loadAgents() {
  try {
    const response = await fetch('/manager/v1/agents', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const data = await response.json();
    renderAgents(data.agents);
  } catch (error) {
    console.error('Failed to load agents:', error);
  }
}
```

### After (SDK)

```typescript
// New approach - type safe, automatic retries, better errors
async function loadAgents() {
  try {
    const { agents } = await client.agents.list();
    renderAgents(agents); // TypeScript knows agents is Agent[]
  } catch (error) {
    if (error instanceof AuthenticationError) {
      // Handle auth failure
    }
    showError('Failed to load agents', error);
  }
}
```

## Development

### Generate Types from OpenAPI

```bash
npm run generate
```

This regenerates TypeScript types from the OpenAPI specification.

### Run Tests

```bash
npm test
```

### Build

```bash
npm run build
```

## Next Steps

1. **WebSocket Support**: Add real-time WebSocket connections for live updates
2. **Request Caching**: Add intelligent caching for read operations
3. **Offline Support**: Queue operations when offline
4. **Telemetry SDK**: Separate package for advanced telemetry visualization
5. **React Hooks**: Custom hooks for React integration

## License

MIT
