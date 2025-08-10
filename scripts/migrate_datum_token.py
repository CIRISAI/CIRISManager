#!/usr/bin/env python3
"""
Migrate Datum's service token from unencrypted to encrypted format.

This script:
1. Reads the current unencrypted token from metadata
2. Encrypts it using the new encryption system
3. Updates the metadata with the encrypted version
"""

import json
import sys
import os
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ciris_manager.crypto import TokenEncryption
from ciris_manager.agent_registry import AgentRegistry


def migrate_datum_token(metadata_path: str, dry_run: bool = False):
    """
    Migrate Datum's token to encrypted format.
    
    Args:
        metadata_path: Path to metadata.json file
        dry_run: If True, only show what would be done without making changes
    """
    print(f"Loading metadata from: {metadata_path}")
    
    # Load metadata directly (not through registry to avoid issues)
    with open(metadata_path, 'r') as f:
        metadata = json.load(f)
    
    agents = metadata.get('agents', {})
    
    if 'datum' not in agents:
        print("ERROR: Datum not found in metadata")
        return False
    
    datum = agents['datum']
    current_token = datum.get('service_token')
    
    if not current_token:
        print("ERROR: Datum has no service token")
        return False
    
    print(f"Current token (first 20 chars): {current_token[:20]}...")
    print(f"Token length: {len(current_token)}")
    
    # Check if already encrypted (base64 encoded tokens are longer and contain different chars)
    if len(current_token) > 100 and ('=' in current_token or '+' in current_token or '/' in current_token):
        print("Token appears to already be encrypted (base64 format detected)")
        return True
    
    # Token is unencrypted hex, encrypt it
    print("\nEncrypting token...")
    
    try:
        encryption = TokenEncryption()
        encrypted_token = encryption.encrypt_token(current_token)
        
        print(f"Encrypted token (first 20 chars): {encrypted_token[:20]}...")
        print(f"Encrypted token length: {len(encrypted_token)}")
        
        # Verify we can decrypt it
        decrypted = encryption.decrypt_token(encrypted_token)
        if decrypted != current_token:
            print("ERROR: Decryption verification failed!")
            return False
        
        print("✓ Encryption/decryption verified successfully")
        
        if dry_run:
            print("\nDRY RUN - Would update metadata with encrypted token")
            return True
        
        # Update metadata
        datum['service_token'] = encrypted_token
        
        # Write back to file
        print(f"\nWriting updated metadata to: {metadata_path}")
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print("✓ Metadata updated successfully")
        
        # Verify by loading through registry
        print("\nVerifying through AgentRegistry...")
        registry = AgentRegistry(Path(metadata_path))
        agent = registry.get_agent('datum')
        if agent and agent.service_token == encrypted_token:
            print("✓ Registry can read the encrypted token")
            return True
        else:
            print("ERROR: Registry verification failed")
            return False
            
    except Exception as e:
        print(f"ERROR: Encryption failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Migrate Datum's token to encrypted format")
    parser.add_argument(
        '--metadata',
        default='/opt/ciris/agents/metadata.json',
        help='Path to metadata.json file'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    # Check environment variables
    if not os.getenv('MANAGER_JWT_SECRET'):
        print("ERROR: MANAGER_JWT_SECRET environment variable not set")
        sys.exit(1)
    
    if not os.getenv('CIRIS_ENCRYPTION_SALT'):
        print("ERROR: CIRIS_ENCRYPTION_SALT environment variable not set")
        sys.exit(1)
    
    print("=== Datum Token Migration ===")
    print(f"Environment variables set: ✓")
    
    success = migrate_datum_token(args.metadata, args.dry_run)
    
    if success:
        print("\n✅ Migration completed successfully!")
        if not args.dry_run:
            print("\nNOTE: You may need to restart ciris-manager service for changes to take effect")
    else:
        print("\n❌ Migration failed")
        sys.exit(1)


if __name__ == '__main__':
    main()