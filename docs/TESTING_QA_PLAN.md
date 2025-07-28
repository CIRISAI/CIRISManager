# CIRISManager Testing & QA Plan

## Overview

This document outlines a comprehensive testing and quality assurance strategy for CIRISManager, covering localhost development through production deployment.

## Testing Phases

### Phase 1: Local Development Testing

#### 1.1 Environment Setup
```bash
# Create isolated test environment
python -m venv test-env
source test-env/bin/activate
pip install -e ".[dev]"

# Set up test configuration
cp deployment/config.example.yml test-config.yml
export CIRIS_MANAGER_CONFIG=$(pwd)/test-config.yml
```

#### 1.2 Unit Test Suite
```bash
# Run full test suite with coverage
pytest tests/ -v --cov=ciris_manager --cov-report=html

# Run specific test categories
pytest tests/ciris_manager/test_manager.py -v
pytest tests/ciris_manager/test_api_routes.py -v
pytest tests/ciris_manager/test_auth_service.py -v
```

#### 1.3 Integration Testing
```bash
# Start Docker daemon (required)
sudo systemctl start docker

# Run integration tests
pytest tests/ -m integration -v

# Test with mock LLM
export MOCK_LLM=true
python deployment/run-ciris-manager-api.py
```

### Phase 2: Component Testing

#### 2.1 Container Management Testing
```bash
# Test container lifecycle
python -m pytest tests/ciris_manager/test_docker_discovery.py::test_container_lifecycle -v

# Test crash loop detection
python -m pytest tests/ciris_manager/test_watchdog_simple.py -v
```

#### 2.2 API Testing
```bash
# Start API server
python deployment/run-ciris-manager-api.py &
API_PID=$!

# Test endpoints
curl http://localhost:8888/manager/v1/health
curl http://localhost:8888/manager/v1/agents

# Stop API server
kill $API_PID
```

#### 2.3 Authentication Testing
```bash
# Test OAuth flow (requires OAuth config)
python -m pytest tests/ciris_manager/test_auth_routes.py -v

# Test JWT validation
python -m pytest tests/ciris_manager/test_auth_service.py::test_jwt_validation -v
```

### Phase 3: System Testing

#### 3.1 End-to-End Agent Creation
```bash
# Start full manager service
python -m ciris_manager.cli --config test-config.yml &
MANAGER_PID=$!

# Create test agent via API
curl -X POST http://localhost:8888/manager/v1/agents \
  -H "Authorization: Bearer $TEST_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"template": "basic", "name": "test-agent"}'

# Verify agent is running
docker ps | grep test-agent

# Clean up
kill $MANAGER_PID
```

#### 3.2 Load Testing
```bash
# Install locust
pip install locust

# Create locustfile.py
cat > locustfile.py << 'EOF'
from locust import HttpUser, task, between

class ManagerUser(HttpUser):
    wait_time = between(1, 3)
    
    @task
    def list_agents(self):
        self.client.get("/manager/v1/agents")
    
    @task
    def check_health(self):
        self.client.get("/manager/v1/system/health")
EOF

# Run load test
locust -f locustfile.py -H http://localhost:8888 --users 50 --spawn-rate 5
```

### Phase 4: QA Checklist

#### 4.1 Functional Testing
- [ ] Agent creation with all templates
- [ ] Agent deletion and cleanup
- [ ] Port allocation and deallocation
- [ ] Nginx configuration generation
- [ ] OAuth login flow
- [ ] JWT token refresh
- [ ] Crash loop detection
- [ ] Agent health monitoring
- [ ] System health endpoint
- [ ] Configuration persistence

#### 4.2 Non-Functional Testing
- [ ] Performance under load (50+ agents)
- [ ] Memory usage over 24 hours
- [ ] Disk space management
- [ ] Network failure recovery
- [ ] Docker daemon restart
- [ ] System reboot persistence
- [ ] Log rotation
- [ ] Concurrent operations
- [ ] Resource limits
- [ ] Security headers

#### 4.3 Edge Cases
- [ ] Port exhaustion (all ports used)
- [ ] Malformed agent configurations
- [ ] Docker API timeouts
- [ ] Invalid OAuth tokens
- [ ] Disk full scenarios
- [ ] Network partition
- [ ] Race conditions
- [ ] Unicode in agent names
- [ ] Large response payloads
- [ ] Clock skew

## Production Deployment Handoff

### Pre-Deployment Checklist

#### Infrastructure Requirements
- [ ] Ubuntu 20.04+ or compatible Linux
- [ ] Docker 20.10+ installed and running
- [ ] Python 3.8+ available
- [ ] 2GB+ RAM available
- [ ] 10GB+ disk space
- [ ] Systemd for service management
- [ ] Nginx for reverse proxy (optional)

#### Security Configuration
- [ ] OAuth credentials configured
- [ ] Firewall rules for port 8888
- [ ] SSL certificates (if using HTTPS)
- [ ] SELinux/AppArmor policies
- [ ] File permissions set correctly
- [ ] Docker socket access secured

### Deployment Process

#### Step 1: Initial Deployment
```bash
# Run deployment script
curl -sSL https://raw.githubusercontent.com/CIRISAI/ciris-manager/main/deployment/deploy.sh | bash

# Verify installation
systemctl status ciris-manager
systemctl status ciris-manager-api
```

#### Step 2: Configuration
```bash
# Edit configuration
sudo vim /etc/ciris-manager/config.yml

# Update OAuth settings
sudo vim /etc/ciris-manager/oauth_config.json

# Restart services
sudo systemctl restart ciris-manager
```

#### Step 3: Validation
```bash
# Check service health
curl http://localhost:8888/manager/v1/health

# View logs
journalctl -u ciris-manager -f

# Test agent creation
curl -X POST http://localhost:8888/manager/v1/agents \
  -H "Authorization: Bearer $PROD_TOKEN" \
  -d '{"template": "basic", "name": "prod-test"}'
```

### Monitoring & Maintenance

#### Health Checks
```bash
# System health
curl http://localhost:8888/manager/v1/health

# Agent status
curl http://localhost:8888/manager/v1/agents

# Resource usage
docker stats --no-stream
systemctl status ciris-manager
```

#### Log Management
```bash
# Manager logs
journalctl -u ciris-manager --since "1 hour ago"

# API logs
journalctl -u ciris-manager-api --since "1 hour ago"

# Agent logs
docker logs ciris-agent-<id>
```

#### Backup & Recovery
```bash
# Backup agent metadata
sudo cp -r /opt/ciris-agents /backup/ciris-agents-$(date +%Y%m%d)

# Backup configuration
sudo cp /etc/ciris-manager/config.yml /backup/

# Restore procedure
sudo systemctl stop ciris-manager
sudo cp -r /backup/ciris-agents-20250128/* /opt/ciris-agents/
sudo systemctl start ciris-manager
```

### Troubleshooting Guide

#### Common Issues

1. **Service Won't Start**
   ```bash
   # Check logs
   journalctl -xe -u ciris-manager
   
   # Verify Docker access
   docker ps
   
   # Check permissions
   ls -la /var/run/docker.sock
   ```

2. **Authentication Failures**
   ```bash
   # Verify OAuth config
   cat /etc/ciris-manager/oauth_config.json
   
   # Test OAuth endpoint
   curl https://accounts.google.com/.well-known/openid-configuration
   ```

3. **Agent Creation Fails**
   ```bash
   # Check available ports
   netstat -tuln | grep 81
   
   # Verify templates
   ls -la /opt/ciris-agents/templates/
   
   # Check disk space
   df -h /opt/ciris-agents
   ```

### Production Handoff Checklist

#### Documentation
- [ ] System architecture documented
- [ ] API endpoints documented
- [ ] Configuration options explained
- [ ] Troubleshooting guide available
- [ ] Runbook for common operations

#### Access & Credentials
- [ ] SSH access configured
- [ ] OAuth credentials secured
- [ ] Admin users created
- [ ] Backup credentials stored
- [ ] Monitoring access granted

#### Operational Readiness
- [ ] Monitoring alerts configured
- [ ] Backup schedule implemented
- [ ] Update procedure documented
- [ ] Rollback plan tested
- [ ] On-call rotation established

#### Performance Baseline
- [ ] Response time metrics
- [ ] Resource usage baseline
- [ ] Agent capacity limits
- [ ] Network throughput
- [ ] Storage growth rate

## Continuous QA Process

### Automated Testing
```yaml
# .github/workflows/test.yml
name: Test Suite
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Run tests
        run: |
          pip install -e ".[dev]"
          pytest tests/ --cov=ciris_manager
```

### Performance Monitoring
```python
# monitoring/metrics.py
import time
import httpx

def monitor_api_health():
    while True:
        start = time.time()
        response = httpx.get("http://localhost:8888/manager/v1/system/health")
        latency = time.time() - start
        
        if latency > 1.0:
            alert("API response slow", latency)
        
        time.sleep(60)
```

### Security Scanning
```bash
# Run security audit
pip-audit

# Scan for secrets
trufflehog filesystem /opt/ciris-manager

# Check dependencies
safety check
```

## Summary

This testing and QA plan provides comprehensive coverage from local development through production deployment. Key success factors:

1. **Automated Testing**: Comprehensive test suite with 80%+ coverage
2. **Staged Deployment**: Test → Staging → Production pipeline
3. **Monitoring**: Real-time health checks and alerting
4. **Documentation**: Clear runbooks and troubleshooting guides
5. **Security**: OAuth, JWT, and proper access controls

Follow this plan to ensure reliable, secure operation of CIRISManager in production environments.