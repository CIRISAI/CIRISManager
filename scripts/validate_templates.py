#!/usr/bin/env python3
"""
Validate templates against the pre-approved manifest.

This script checks that all templates listed in the manifest have correct checksums.
"""

import json
import hashlib
import sys
from pathlib import Path


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA-256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def main():
    """Validate all templates against manifest."""
    # Load manifest
    manifest_path = Path(__file__).parent.parent / "pre-approved-templates.json"
    if not manifest_path.exists():
        print(f"❌ Manifest not found at {manifest_path}")
        return 1

    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    print(f"📋 Validating templates against manifest version {manifest['version']}")
    print(f"   Created: {manifest['created_at']}")
    print()

    # Template directory
    templates_dir = Path(__file__).parent.parent / "agent_templates"

    # Track validation results
    all_valid = True
    validated_count = 0

    # Validate each template in manifest
    for template_name, template_info in manifest["templates"].items():
        template_file = templates_dir / f"{template_name}.yaml"
        expected_checksum = template_info["checksum"].replace("sha256:", "")

        print(f"🔍 Checking {template_name}...")

        if not template_file.exists():
            print(f"   ❌ Template file not found: {template_file}")
            all_valid = False
            continue

        # Calculate actual checksum
        actual_checksum = calculate_checksum(template_file)

        if actual_checksum == expected_checksum:
            print(f"   ✅ Valid - {template_info['description']}")
            validated_count += 1
        else:
            print("   ❌ Invalid checksum!")
            print(f"      Expected: {expected_checksum}")
            print(f"      Actual:   {actual_checksum}")
            all_valid = False

    print()

    # Check for templates not in manifest
    template_files = list(templates_dir.glob("*.yaml"))
    manifest_templates = set(manifest["templates"].keys())

    for template_file in template_files:
        template_name = template_file.stem
        if template_name not in manifest_templates:
            print(f"⚠️  Template not in manifest: {template_name}")
            if template_name.endswith(".backup"):
                print("   (backup file, skipping)")
            else:
                print("   This template is not pre-approved and will require WA signature")

    # Summary
    print()
    print("=" * 50)
    if all_valid:
        print(f"✅ All {validated_count} pre-approved templates are valid!")
        return 0
    else:
        print("❌ Validation failed! Some templates have incorrect checksums.")
        print("   The templates may have been modified since approval.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
