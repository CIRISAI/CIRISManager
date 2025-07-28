"""
Unit tests for TemplateVerifier.
"""

import pytest
import tempfile
import json
import base64
from pathlib import Path
from nacl.signing import SigningKey
from ciris_manager.template_verifier import TemplateVerifier


class TestTemplateVerifier:
    """Test cases for TemplateVerifier."""
    
    @pytest.fixture
    def temp_manifest_path(self):
        """Create temporary manifest file path."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = Path(f.name)
        yield temp_path
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()
    
    @pytest.fixture
    def temp_template_path(self):
        """Create temporary template file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("""---
name: test-template
purpose: Testing template verification
settings:
  mock_llm: true
""")
            temp_path = Path(f.name)
        yield temp_path
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()
    
    @pytest.fixture
    def valid_manifest(self, temp_template_path):
        """Create a valid signed manifest."""
        # Generate signing key
        signing_key = SigningKey.generate()
        verify_key = signing_key.verify_key
        
        # Calculate template checksum
        import hashlib
        sha256_hash = hashlib.sha256()
        with open(temp_template_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        checksum = sha256_hash.hexdigest()
        
        # Create templates object
        templates = {
            "test": {
                "checksum": f"sha256:{checksum}",
                "description": "Test template"
            },
            "scout": {
                "checksum": "sha256:b637983cea13976203ed831b88b70ae419d0209ea058ec49937fa74f8b1b6c3a",
                "description": "Scout template"
            }
        }
        
        # Sign templates
        templates_json = json.dumps(templates, sort_keys=True, separators=(',', ':'))
        templates_bytes = templates_json.encode('utf-8')
        signed = signing_key.sign(templates_bytes)
        
        # Create manifest
        manifest = {
            "version": "1.0",
            "templates": templates,
            "root_signature": base64.b64encode(signed.signature).decode('ascii'),
            "root_public_key": base64.b64encode(verify_key.encode()).decode('ascii')
        }
        
        return manifest, checksum
    
    def test_initialization_no_manifest(self, temp_manifest_path):
        """Test initialization when manifest doesn't exist."""
        verifier = TemplateVerifier(temp_manifest_path)
        assert verifier.manifest is None
        assert verifier.root_public_key is None
    
    def test_load_valid_manifest(self, temp_manifest_path, valid_manifest):
        """Test loading a valid manifest."""
        manifest, _ = valid_manifest
        
        # Write manifest
        with open(temp_manifest_path, 'w') as f:
            json.dump(manifest, f)
        
        # Load
        verifier = TemplateVerifier(temp_manifest_path)
        assert verifier.manifest is not None
        assert verifier.root_public_key is not None
        assert len(verifier.manifest['templates']) == 2
    
    def test_invalid_signature(self, temp_manifest_path, valid_manifest):
        """Test manifest with invalid signature."""
        manifest, _ = valid_manifest
        
        # Corrupt signature
        manifest['root_signature'] = base64.b64encode(b"invalid").decode('ascii')
        
        # Write manifest
        with open(temp_manifest_path, 'w') as f:
            json.dump(manifest, f)
        
        # Should fail to load
        verifier = TemplateVerifier(temp_manifest_path)
        assert verifier.manifest is None
    
    def test_missing_public_key(self, temp_manifest_path, valid_manifest):
        """Test manifest missing public key."""
        manifest, _ = valid_manifest
        
        # Remove public key
        del manifest['root_public_key']
        
        # Write manifest
        with open(temp_manifest_path, 'w') as f:
            json.dump(manifest, f)
        
        # Should fail to load
        verifier = TemplateVerifier(temp_manifest_path)
        assert verifier.manifest is None
    
    def test_is_pre_approved_valid(self, temp_manifest_path, temp_template_path, valid_manifest):
        """Test checking a valid pre-approved template."""
        manifest, checksum = valid_manifest
        
        # Write manifest
        with open(temp_manifest_path, 'w') as f:
            json.dump(manifest, f)
        
        # Verify
        verifier = TemplateVerifier(temp_manifest_path)
        assert verifier.is_pre_approved("test", temp_template_path)
    
    def test_is_pre_approved_modified(self, temp_manifest_path, temp_template_path, valid_manifest):
        """Test checking a modified template."""
        manifest, _ = valid_manifest
        
        # Write manifest
        with open(temp_manifest_path, 'w') as f:
            json.dump(manifest, f)
        
        # Modify template
        with open(temp_template_path, 'a') as f:
            f.write("\n# Modified!\n")
        
        # Should not be pre-approved
        verifier = TemplateVerifier(temp_manifest_path)
        assert not verifier.is_pre_approved("test", temp_template_path)
    
    def test_is_pre_approved_not_in_list(self, temp_manifest_path, temp_template_path, valid_manifest):
        """Test checking a template not in pre-approved list."""
        manifest, _ = valid_manifest
        
        # Write manifest
        with open(temp_manifest_path, 'w') as f:
            json.dump(manifest, f)
        
        # Check non-existent template
        verifier = TemplateVerifier(temp_manifest_path)
        assert not verifier.is_pre_approved("unknown", temp_template_path)
    
    def test_calculate_checksum(self, temp_template_path):
        """Test checksum calculation."""
        verifier = TemplateVerifier(Path("/nonexistent"))
        
        checksum = verifier.calculate_template_checksum(temp_template_path)
        assert len(checksum) == 64  # SHA-256 hex length
        assert all(c in '0123456789abcdef' for c in checksum)
    
    def test_get_template_description(self, temp_manifest_path, valid_manifest):
        """Test getting template description."""
        manifest, _ = valid_manifest
        
        # Write manifest
        with open(temp_manifest_path, 'w') as f:
            json.dump(manifest, f)
        
        verifier = TemplateVerifier(temp_manifest_path)
        
        # Existing template
        desc = verifier.get_template_description("scout")
        assert desc == "Scout template"
        
        # Non-existent template
        desc = verifier.get_template_description("unknown")
        assert desc is None
    
    def test_list_pre_approved_templates(self, temp_manifest_path, valid_manifest):
        """Test listing pre-approved templates."""
        manifest, _ = valid_manifest
        
        # Write manifest
        with open(temp_manifest_path, 'w') as f:
            json.dump(manifest, f)
        
        verifier = TemplateVerifier(temp_manifest_path)
        templates = verifier.list_pre_approved_templates()
        
        assert len(templates) == 2
        assert templates["test"] == "Test template"
        assert templates["scout"] == "Scout template"
    
    def test_corrupted_manifest(self, temp_manifest_path):
        """Test handling corrupted manifest file."""
        # Write invalid JSON
        with open(temp_manifest_path, 'w') as f:
            f.write("not valid json")
        
        # Should handle gracefully
        verifier = TemplateVerifier(temp_manifest_path)
        assert verifier.manifest is None
        assert not verifier.is_pre_approved("any", Path("/any"))