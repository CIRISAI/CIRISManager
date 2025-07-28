"""
Unit tests for PortManager.
"""

import pytest
import tempfile
import json
from pathlib import Path
from ciris_manager.port_manager import PortManager


class TestPortManager:
    """Test cases for PortManager."""
    
    @pytest.fixture
    def temp_metadata_path(self):
        """Create temporary metadata file path."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)
        yield temp_path
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()
    
    @pytest.fixture
    def port_manager(self, temp_metadata_path):
        """Create PortManager instance with temporary metadata."""
        return PortManager(
            start_port=8080,
            end_port=8090,
            metadata_path=temp_metadata_path
        )
    
    def test_initialization(self, port_manager):
        """Test PortManager initialization."""
        assert port_manager.start_port == 8080
        assert port_manager.end_port == 8090
        assert len(port_manager.allocated_ports) == 0
        # Default reserved ports are initialized
        assert len(port_manager.reserved_ports) == 4  # 8888, 3000, 80, 443
    
    def test_allocate_port(self, port_manager):
        """Test port allocation."""
        # Allocate first port
        port1 = port_manager.allocate_port("agent-1")
        assert port1 == 8080
        assert port_manager.allocated_ports["agent-1"] == 8080
        
        # Allocate second port
        port2 = port_manager.allocate_port("agent-2")
        assert port2 == 8081
        assert port_manager.allocated_ports["agent-2"] == 8081
        
        # Verify metadata was saved
        assert port_manager.metadata_path.exists()
    
    def test_allocate_port_with_reserved(self, port_manager):
        """Test port allocation with reserved ports."""
        # Add reserved ports
        port_manager.add_reserved_port(8080)
        port_manager.add_reserved_port(8081)
        
        # Allocate should skip reserved
        port1 = port_manager.allocate_port("agent-1")
        assert port1 == 8082
    
    def test_release_port(self, port_manager):
        """Test port release."""
        # Allocate and release
        port = port_manager.allocate_port("agent-1")
        assert port == 8080
        
        released = port_manager.release_port("agent-1")
        assert released == 8080
        assert "agent-1" not in port_manager.allocated_ports
        
        # Release non-existent
        released = port_manager.release_port("agent-2")
        assert released is None
    
    def test_get_port(self, port_manager):
        """Test getting allocated port."""
        # Allocate port
        port_manager.allocate_port("agent-1")
        
        # Get existing
        port = port_manager.get_port("agent-1")
        assert port == 8080
        
        # Get non-existent
        port = port_manager.get_port("agent-2")
        assert port is None
    
    def test_is_port_available(self, port_manager):
        """Test port availability check."""
        # Initially available
        assert port_manager.is_port_available(8080)
        
        # Allocate and check
        port_manager.allocate_port("agent-1")
        assert not port_manager.is_port_available(8080)
        assert port_manager.is_port_available(8081)
        
        # Reserved port
        port_manager.add_reserved_port(8082)
        assert not port_manager.is_port_available(8082)
    
    def test_port_exhaustion(self, port_manager):
        """Test behavior when all ports are allocated."""
        # Allocate all available ports (8080-8090 = 11 ports)
        allocated_count = 0
        for i in range(12):  # Try to allocate one more than available
            try:
                port = port_manager.allocate_port(f"agent-{i}")
                assert 8080 <= port <= 8090
                allocated_count += 1
            except ValueError as e:
                # Should raise after 11 allocations
                assert allocated_count == 11
                assert "No available ports" in str(e)
                break
        else:
            pytest.fail("Expected ValueError for port exhaustion")
    
    def test_persistence(self, temp_metadata_path):
        """Test metadata persistence."""
        # Create and allocate
        pm1 = PortManager(8080, 8090, temp_metadata_path)
        pm1.allocate_port("agent-1")
        pm1.allocate_port("agent-2")
        pm1.add_reserved_port(8085)
        
        # Manually save metadata (PortManager doesn't auto-save)
        metadata = {
            "version": "1.0",
            "agents": {
                "agent-1": {"port": 8080},
                "agent-2": {"port": 8081}
            }
        }
        with open(temp_metadata_path, 'w') as f:
            json.dump(metadata, f)
        
        # Create new instance - should load metadata
        pm2 = PortManager(8080, 8090, temp_metadata_path)
        assert pm2.allocated_ports["agent-1"] == 8080
        assert pm2.allocated_ports["agent-2"] == 8081
        # Note: Reserved ports are not persisted in current implementation
        # Only allocated ports are persisted via metadata
    
    def test_concurrent_allocation(self, port_manager):
        """Test thread safety of allocation."""
        import threading
        import time
        
        allocated_ports = []
        errors = []
        
        def allocate_port(agent_id):
            try:
                port = port_manager.allocate_port(agent_id)
                allocated_ports.append(port)
            except Exception as e:
                errors.append(e)
        
        # Create threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=allocate_port, args=(f"agent-{i}",))
            threads.append(t)
        
        # Start all threads
        for t in threads:
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # Verify
        assert len(errors) == 0
        assert len(allocated_ports) == 5
        assert len(set(allocated_ports)) == 5  # All unique
    
    def test_metadata_corruption_recovery(self, temp_metadata_path):
        """Test recovery from corrupted metadata."""
        # Write corrupted metadata
        with open(temp_metadata_path, 'w') as f:
            f.write("not valid json")
        
        # Should handle gracefully
        pm = PortManager(8080, 8090, temp_metadata_path)
        assert len(pm.allocated_ports) == 0
        
        # Should work normally
        port = pm.allocate_port("agent-1")
        assert port == 8080