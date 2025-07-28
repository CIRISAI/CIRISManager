#!/usr/bin/env python3
"""
Test that CIRISManager can be imported and initialized standalone.
"""
import sys

def test_imports():
    """Test that all main imports work."""
    try:
        from ciris_manager import CIRISManager
        from ciris_manager.config.settings import CIRISManagerConfig
        from ciris_manager.core.container_manager import ContainerManager
        from ciris_manager.core.watchdog import CrashLoopWatchdog
        from ciris_manager.api.routes import create_routes
        print("✓ All imports successful")
        return True
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False

def test_initialization():
    """Test that manager can be initialized."""
    try:
        from ciris_manager import CIRISManager
        manager = CIRISManager()
        print("✓ Manager initialized successfully")
        return True
    except Exception as e:
        print(f"✗ Initialization failed: {e}")
        return False

def test_api_creation():
    """Test that API can be created."""
    try:
        from fastapi import FastAPI
        from ciris_manager.api.routes import create_routes
        from ciris_manager import CIRISManager
        
        app = FastAPI()
        manager = CIRISManager()
        router = create_routes(manager)
        app.include_router(router, prefix="/manager/v1")
        
        print("✓ API created successfully")
        return True
    except Exception as e:
        print(f"✗ API creation failed: {e}")
        return False

def main():
    """Run all tests."""
    print("Testing CIRISManager standalone functionality...\n")
    
    tests = [
        test_imports,
        test_initialization,
        test_api_creation,
    ]
    
    results = []
    for test in tests:
        results.append(test())
        print()
    
    if all(results):
        print("✅ All tests passed! CIRISManager is ready as a standalone repository.")
        sys.exit(0)
    else:
        print("❌ Some tests failed. Please check the errors above.")
        sys.exit(1)

if __name__ == "__main__":
    main()