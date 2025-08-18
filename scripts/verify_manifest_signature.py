#!/usr/bin/env python3
"""
Verify the manifest signature to ensure it hasn't been tampered with.
"""

import json
import base64
import sys
from pathlib import Path
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError


def main():
    """Verify manifest signature."""
    manifest_path = Path(__file__).parent.parent / "pre-approved-templates.json"

    if not manifest_path.exists():
        print(f"❌ Manifest not found at {manifest_path}")
        return 1

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    print("🔐 Verifying manifest signature...")
    print(f"   Version: {manifest['version']}")
    print(f"   Created: {manifest['created_at']}")
    print()

    try:
        # Extract and decode public key
        key_bytes = base64.b64decode(manifest["root_public_key"])
        verify_key = VerifyKey(key_bytes)
        print(f"   Public key loaded: {manifest['root_public_key'][:20]}...")

        # Get signature
        signature_b64 = manifest.get("root_signature")
        if not signature_b64:
            print("   ❌ No signature found in manifest")
            return 1

        signature = base64.b64decode(signature_b64)
        print(f"   Signature found: {signature_b64[:20]}...")

        # Recreate signed data (templates object as deterministic JSON)
        templates_json = json.dumps(manifest["templates"], sort_keys=True, separators=(",", ":"))
        templates_bytes = templates_json.encode("utf-8")

        # Verify
        verify_key.verify(templates_bytes, signature)

        print()
        print("✅ Manifest signature is VALID!")
        print("   The manifest has not been tampered with.")
        return 0

    except BadSignatureError:
        print()
        print("❌ INVALID SIGNATURE!")
        print("   The manifest may have been tampered with.")
        return 1
    except Exception as e:
        print()
        print(f"❌ Signature verification error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
