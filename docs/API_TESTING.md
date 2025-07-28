# API Testing Guide

## Quick API Test Commands

With the API server running (`make run-api`), you can test these endpoints:

### Health Check
```bash
curl http://localhost:8888/manager/v1/health | jq
```

### Manager Status
```bash
curl http://localhost:8888/manager/v1/status | jq
```

### List Agents
```bash
curl http://localhost:8888/manager/v1/agents | jq
```

### List Templates
```bash
curl http://localhost:8888/manager/v1/templates | jq
```

### Check Allocated Ports
```bash
curl http://localhost:8888/manager/v1/ports/allocated | jq
```

### Interactive API Documentation
Visit http://localhost:8888/docs in your browser for the interactive OpenAPI documentation.

## Authentication

Some endpoints (POST /agents, DELETE /agents/{id}) require authentication. Set up OAuth as described in the configuration section to test these endpoints.