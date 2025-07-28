#!/usr/bin/env python3
"""
CIRISManager CLI entry point.
"""
import argparse
import asyncio
import sys
import yaml
from pathlib import Path

from ciris_manager.manager import CIRISManager
from ciris_manager.config.settings import CIRISManagerConfig


def generate_default_config(config_path: str):
    """Generate a default configuration file."""
    default_config = {
        'docker': {
            'compose_file': '/home/ciris/CIRISAgent/deployment/docker-compose.yml'
        },
        'watchdog': {
            'check_interval': 30,
            'crash_threshold': 3,
            'crash_window': 300
        },
        'container_management': {
            'interval': 300,
            'pull_images': True
        },
        'api': {
            'host': '127.0.0.1',
            'port': 8888
        }
    }
    
    Path(config_path).parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, 'w') as f:
        yaml.dump(default_config, f, default_flow_style=False)
    
    print(f"Generated default configuration at: {config_path}")


async def run_manager(config_path: str):
    """Run the CIRISManager."""
    try:
        config = CIRISManagerConfig.from_file(config_path)
        manager = CIRISManager(config)
        
        print(f"Starting CIRISManager...")
        print(f"Compose file: {config.docker.compose_file}")
        print(f"Container check interval: {config.container_management.interval}s")
        print(f"Watchdog interval: {config.watchdog.check_interval}s")
        
        await manager.start()
        
        # Keep running until interrupted
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down CIRISManager...")
            await manager.stop()
            
    except Exception as e:
        print(f"Error running CIRISManager: {e}")
        sys.exit(1)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="CIRIS Container Manager")
    parser.add_argument(
        '--config',
        default='/etc/ciris-manager/config.yml',
        help='Path to configuration file (default: /etc/ciris-manager/config.yml)'
    )
    parser.add_argument(
        '--generate-config',
        action='store_true',
        help='Generate a default configuration file and exit'
    )
    
    args = parser.parse_args()
    
    if args.generate_config:
        generate_default_config(args.config)
        sys.exit(0)
    
    # Check if config exists
    if not Path(args.config).exists():
        print(f"Configuration file not found: {args.config}")
        print(f"Generate one with: ciris-manager --generate-config --config {args.config}")
        sys.exit(1)
    
    # Run the manager
    try:
        asyncio.run(run_manager(args.config))
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)


if __name__ == "__main__":
    main()