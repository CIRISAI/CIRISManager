#!/bin/bash
# CIRISManager Localhost Testing Script
# This script performs comprehensive testing on localhost before production deployment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test results
PASSED=0
FAILED=0

# Helper functions
log_test() {
    echo -e "\n${YELLOW}[TEST]${NC} $1"
}

log_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((PASSED++))
}

log_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((FAILED++))
}

# Check prerequisites
check_prerequisites() {
    log_test "Checking prerequisites"
    
    # Python version
    if python3 -c "import sys; exit(0 if sys.version_info >= (3,8) else 1)"; then
        log_pass "Python 3.8+ found"
    else
        log_fail "Python 3.8+ required"
        exit 1
    fi
    
    # Docker
    if command -v docker &> /dev/null; then
        log_pass "Docker installed"
    else
        log_fail "Docker not found"
        exit 1
    fi
    
    # Docker daemon running
    if docker ps &> /dev/null; then
        log_pass "Docker daemon running"
    else
        log_fail "Docker daemon not accessible"
        exit 1
    fi
}

# Setup test environment
setup_test_env() {
    log_test "Setting up test environment"
    
    # Create virtual environment
    if [ ! -d "test-env" ]; then
        python3 -m venv test-env
        log_pass "Virtual environment created"
    else
        log_pass "Virtual environment exists"
    fi
    
    # Activate and install
    source test-env/bin/activate
    pip install -q -e ".[dev]"
    log_pass "Dependencies installed"
    
    # Create test config
    cat > test-config.yml << 'EOF'
manager:
  host: 127.0.0.1
  port: 8888
  agents_directory: ./test-agents
docker:
  compose_file: ./test-compose.yml
watchdog:
  check_interval: 5
  crash_threshold: 3
  crash_window: 60
api:
  enable_cors: true
  cors_origins: ["http://localhost:3000"]
EOF
    log_pass "Test configuration created"
    
    export CIRIS_MANAGER_CONFIG=$(pwd)/test-config.yml
}

# Run unit tests
run_unit_tests() {
    log_test "Running unit tests"
    
    # Run pytest with coverage
    if pytest tests/ -v --tb=short --cov=ciris_manager --cov-report=term-missing > test-results.log 2>&1; then
        log_pass "All unit tests passed"
        
        # Check coverage
        coverage=$(grep "TOTAL" test-results.log | awk '{print $4}' | sed 's/%//')
        if [ "${coverage%.*}" -ge 70 ]; then
            log_pass "Code coverage: $coverage%"
        else
            log_fail "Code coverage below 70%: $coverage%"
        fi
    else
        log_fail "Unit tests failed (see test-results.log)"
    fi
}

# Test API endpoints
test_api_endpoints() {
    log_test "Testing API endpoints"
    
    # Start manager service (includes API) in background
    python -m ciris_manager.cli --config test-config.yml > api.log 2>&1 &
    MANAGER_PID=$!
    sleep 5
    
    # Test health endpoint
    if curl -s http://localhost:8888/manager/v1/system/health | grep -q "healthy"; then
        log_pass "Health endpoint working"
    else
        log_fail "Health endpoint not responding"
    fi
    
    # Test agents endpoint
    if curl -s http://localhost:8888/manager/v1/agents | grep -q "agents"; then
        log_pass "Agents endpoint working"
    else
        log_fail "Agents endpoint not responding"
    fi
    
    # Test OpenAPI docs
    if curl -s http://localhost:8888/docs | grep -q "swagger"; then
        log_pass "OpenAPI documentation available"
    else
        log_fail "OpenAPI documentation not found"
    fi
    
    # Stop manager service
    kill $MANAGER_PID 2>/dev/null || true
    wait $MANAGER_PID 2>/dev/null || true
}

# Test container management
test_container_management() {
    log_test "Testing container management"
    
    # Create a test container
    docker run -d --name test-ciris-agent \
        --label ciris.agent=true \
        --label ciris.name=test-agent \
        alpine sleep 3600
    
    # Test discovery
    python -c "
from ciris_manager.docker_discovery import DockerDiscovery
import asyncio

async def test():
    discovery = DockerDiscovery()
    agents = await discovery.discover_agents()
    return len([a for a in agents if a['name'] == 'test-agent']) > 0

result = asyncio.run(test())
exit(0 if result else 1)
" && log_pass "Container discovery working" || log_fail "Container discovery failed"
    
    # Cleanup
    docker rm -f test-ciris-agent &>/dev/null || true
}

# Test crash loop detection
test_crash_loop_detection() {
    log_test "Testing crash loop detection"
    
    python -c "
from ciris_manager.core.watchdog import CrashLoopWatchdog
import time

watchdog = CrashLoopWatchdog(crash_threshold=3, crash_window=10)

# Simulate crashes
for _ in range(3):
    watchdog.record_crash('test-container')
    
if watchdog.is_crash_looping('test-container'):
    exit(0)
else:
    exit(1)
" && log_pass "Crash loop detection working" || log_fail "Crash loop detection failed"
}

# Test port allocation
test_port_allocation() {
    log_test "Testing port allocation"
    
    python -c "
from ciris_manager.port_manager import PortManager
import asyncio

async def test():
    pm = PortManager()
    
    # Allocate port
    port1 = await pm.allocate_port('agent1')
    if not (8100 <= port1 <= 8199):
        return False
        
    # Ensure unique allocation
    port2 = await pm.allocate_port('agent2')
    if port1 == port2:
        return False
        
    # Test deallocation
    await pm.release_port('agent1')
    port3 = await pm.allocate_port('agent3')
    
    return port3 == port1  # Should reuse released port

result = asyncio.run(test())
exit(0 if result else 1)
" && log_pass "Port allocation working" || log_fail "Port allocation failed"
}

# Test configuration loading
test_configuration() {
    log_test "Testing configuration loading"
    
    python -c "
from ciris_manager.config.settings import CIRISManagerConfig
import os

os.environ['CIRIS_MANAGER_CONFIG'] = 'test-config.yml'
config = CIRISManagerConfig.from_file('test-config.yml')

if config.manager.port == 8888 and config.watchdog.crash_threshold == 3:
    exit(0)
else:
    exit(1)
" && log_pass "Configuration loading working" || log_fail "Configuration loading failed"
}

# Performance test
test_performance() {
    log_test "Testing performance"
    
    # Start manager service for performance test
    python -m ciris_manager.cli --config test-config.yml > perf.log 2>&1 &
    MANAGER_PID=$!
    sleep 5
    
    # Measure response time
    start_time=$(date +%s%N)
    for i in {1..100}; do
        curl -s http://localhost:8888/manager/v1/system/health > /dev/null
    done
    end_time=$(date +%s%N)
    
    # Calculate average response time
    elapsed=$((($end_time - $start_time) / 1000000))
    avg_time=$(($elapsed / 100))
    
    if [ $avg_time -lt 50 ]; then
        log_pass "Average response time: ${avg_time}ms"
    else
        log_fail "Response time too high: ${avg_time}ms"
    fi
    
    # Stop manager service
    kill $MANAGER_PID 2>/dev/null || true
}

# Integration test
test_integration() {
    log_test "Running integration test"
    
    # Start full manager
    python -m ciris_manager.cli --config test-config.yml > manager.log 2>&1 &
    MANAGER_PID=$!
    sleep 10
    
    # Check if manager started
    if ps -p $MANAGER_PID > /dev/null; then
        log_pass "Manager started successfully"
    else
        log_fail "Manager failed to start (see manager.log)"
    fi
    
    # Test agent creation (mock)
    export MOCK_LLM=true
    python -c "
import asyncio
from ciris_manager.manager import CIRISManager
from ciris_manager.config.settings import CIRISManagerConfig

async def test():
    config = CIRISManagerConfig.from_file('test-config.yml')
    manager = CIRISManager(config)
    
    # Test template verification
    templates = await manager.template_verifier.list_templates()
    return len(templates) > 0

result = asyncio.run(test())
exit(0 if result else 1)
" && log_pass "Template system working" || log_fail "Template system failed"
    
    # Stop manager
    kill $MANAGER_PID 2>/dev/null || true
}

# Generate test report
generate_report() {
    echo -e "\n${YELLOW}========== TEST SUMMARY ==========${NC}"
    echo -e "Total Tests: $((PASSED + FAILED))"
    echo -e "${GREEN}Passed: $PASSED${NC}"
    echo -e "${RED}Failed: $FAILED${NC}"
    
    if [ $FAILED -eq 0 ]; then
        echo -e "\n${GREEN}✓ All tests passed! Ready for production deployment.${NC}"
        
        # Generate handoff report
        cat > localhost-test-report.txt << EOF
CIRISManager Localhost Test Report
Generated: $(date)

TEST RESULTS
============
Total Tests: $((PASSED + FAILED))
Passed: $PASSED
Failed: $FAILED

SYSTEM INFO
===========
Python: $(python3 --version)
Docker: $(docker --version)
OS: $(uname -a)

NEXT STEPS
==========
1. Review test-results.log for detailed unit test results
2. Check api.log and manager.log for any warnings
3. Proceed with production deployment using PRODUCTION_HANDOFF.md
4. Configure OAuth credentials for production
5. Set up monitoring and alerting

HANDOFF NOTES
=============
- All core functionality tested and working
- API endpoints responsive
- Container management operational
- Configuration system validated
- Ready for production deployment
EOF
        echo -e "\nHandoff report generated: localhost-test-report.txt"
    else
        echo -e "\n${RED}✗ Some tests failed. Please fix issues before deployment.${NC}"
        exit 1
    fi
}

# Cleanup function
cleanup() {
    echo -e "\n${YELLOW}Cleaning up...${NC}"
    
    # Stop any running processes
    kill $MANAGER_PID 2>/dev/null || true
    
    # Remove test containers
    docker rm -f test-ciris-agent 2>/dev/null || true
    
    # Deactivate virtual environment
    deactivate 2>/dev/null || true
    
    echo "Cleanup complete"
}

# Set trap for cleanup
trap cleanup EXIT

# Main execution
main() {
    echo -e "${YELLOW}CIRISManager Localhost Testing Suite${NC}"
    echo "====================================="
    
    check_prerequisites
    setup_test_env
    run_unit_tests
    test_api_endpoints
    test_container_management
    test_crash_loop_detection
    test_port_allocation
    test_configuration
    test_performance
    test_integration
    generate_report
}

# Run main
main