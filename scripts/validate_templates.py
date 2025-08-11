#!/usr/bin/env python3
"""
Validate agent templates against the pre-approved manifest.

This script:
1. Loads the pre-approved-templates.json manifest
2. Checks each template file against its expected checksum
3. Reports any mismatches or missing templates
"""

import json
import hashlib
import sys
from pathlib import Path


def calculate_checksum(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return f"sha256:{sha256_hash.hexdigest()}"


def validate_templates(templates_dir: Path, manifest_path: Path) -> bool:
    """
    Validate templates against the manifest.

    Returns True if all templates are valid, False otherwise.
    """
    # Load manifest
    with open(manifest_path, "r") as f:
        manifest = json.load(f)

    print(f"Manifest version: {manifest['version']}")
    print(f"Created at: {manifest['created_at']}")
    print(f"Root signature present: {'root_signature' in manifest}")
    print()

    all_valid = True
    templates = manifest.get("templates", {})

    # Check each template in manifest
    for template_name, template_info in templates.items():
        template_file = templates_dir / f"{template_name}.yaml"
        expected_checksum = template_info["checksum"]
        description = template_info["description"]

        print(f"Checking {template_name}:")
        print(f"  Description: {description}")

        if not template_file.exists():
            print(f"  ❌ MISSING: {template_file}")
            all_valid = False
            continue

        actual_checksum = calculate_checksum(template_file)

        if actual_checksum == expected_checksum:
            print("  ✅ Valid checksum")
        else:
            print("  ❌ INVALID checksum!")
            print(f"     Expected: {expected_checksum}")
            print(f"     Actual:   {actual_checksum}")
            all_valid = False
        print()

    # Check for extra templates not in manifest
    template_files = list(templates_dir.glob("*.yaml"))
    manifest_templates = {f"{name}.yaml" for name in templates.keys()}

    for template_file in template_files:
        if template_file.name not in manifest_templates and not template_file.name.endswith(
            ".backup"
        ):
            print(f"⚠️  Extra template not in manifest: {template_file.name}")
            actual_checksum = calculate_checksum(template_file)
            print(f"   Checksum: {actual_checksum}")
            print()

    return all_valid


def main():
    """Main entry point."""
    # Determine paths
    script_dir = Path(__file__).parent.parent
    templates_dir = script_dir / "agent_templates"
    manifest_path = script_dir / "pre-approved-templates.json"

    print("Template Validation Tool")
    print("=" * 50)
    print(f"Templates directory: {templates_dir}")
    print(f"Manifest path: {manifest_path}")
    print()

    # Validate
    if not templates_dir.exists():
        print(f"❌ Templates directory not found: {templates_dir}")
        sys.exit(1)

    if not manifest_path.exists():
        print(f"❌ Manifest not found: {manifest_path}")
        sys.exit(1)

    all_valid = validate_templates(templates_dir, manifest_path)

    print("=" * 50)
    if all_valid:
        print("✅ All templates are valid!")
        sys.exit(0)
    else:
        print("❌ Some templates are invalid or missing!")
        print("\nTo regenerate the manifest, run:")
        print("  cd /home/emoore/CIRISAgent")
        print("  ./scripts/generate-template-manifest.sh")
        print("\nThen copy the updated files:")
        print("  cp ciris_templates/* ../CIRISManager/agent_templates/")
        print("  cp pre-approved-templates.json ../CIRISManager/")
        sys.exit(1)


if __name__ == "__main__":
    main()
