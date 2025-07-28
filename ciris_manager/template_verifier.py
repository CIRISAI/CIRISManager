"""
Template verification for pre-approved CIRIS templates.

Verifies templates against the root-signed manifest to determine
if they require WA approval for creation.
"""

import json
import hashlib
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import base64
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

logger = logging.getLogger(__name__)


class TemplateVerifier:
    """Verifies templates against pre-approved manifest."""
    
    def __init__(self, manifest_path: Path):
        """
        Initialize template verifier.
        
        Args:
            manifest_path: Path to pre-approved-templates.json
        """
        self.manifest_path = manifest_path
        self.manifest: Optional[Dict[str, Any]] = None
        self.root_public_key: Optional[VerifyKey] = None
        
        # Load and verify manifest
        self._load_manifest()
    
    def _load_manifest(self) -> None:
        """Load and verify the pre-approved templates manifest."""
        if not self.manifest_path.exists():
            logger.warning(f"Pre-approved manifest not found at {self.manifest_path}")
            return
        
        try:
            with open(self.manifest_path, 'r') as f:
                self.manifest = json.load(f)
            
            # Extract root public key
            if 'root_public_key' not in self.manifest:
                logger.error("Manifest missing root_public_key")
                self.manifest = None
                return
            
            # Decode public key
            key_bytes = base64.b64decode(self.manifest['root_public_key'])
            self.root_public_key = VerifyKey(key_bytes)
            
            # Verify signature
            if not self._verify_manifest_signature():
                logger.error("Manifest signature verification failed")
                self.manifest = None
                return
            
            logger.info(f"Loaded pre-approved manifest with {len(self.manifest.get('templates', {}))} templates")
            
        except Exception as e:
            logger.error(f"Failed to load manifest: {e}")
            self.manifest = None
    
    def _verify_manifest_signature(self) -> bool:
        """Verify the manifest signature."""
        if not self.manifest or not self.root_public_key:
            return False
        
        try:
            # Get signature
            signature_b64 = self.manifest.get('root_signature')
            if not signature_b64:
                return False
            
            signature = base64.b64decode(signature_b64)
            
            # Recreate signed data (templates object as deterministic JSON)
            templates_json = json.dumps(
                self.manifest['templates'], 
                sort_keys=True, 
                separators=(',', ':')
            )
            templates_bytes = templates_json.encode('utf-8')
            
            # Verify
            self.root_public_key.verify(templates_bytes, signature)
            return True
            
        except BadSignatureError:
            logger.error("Manifest signature is invalid")
            return False
        except Exception as e:
            logger.error(f"Signature verification error: {e}")
            return False
    
    def calculate_template_checksum(self, template_path: Path) -> str:
        """Calculate SHA-256 checksum of a template file."""
        sha256_hash = hashlib.sha256()
        with open(template_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def is_pre_approved(self, template_name: str, template_path: Path) -> bool:
        """
        Check if a template is pre-approved.
        
        Args:
            template_name: Name of the template (e.g., 'scout')
            template_path: Path to the template file
            
        Returns:
            True if template is pre-approved and unmodified
        """
        if not self.manifest:
            logger.warning("No manifest loaded, treating all templates as custom")
            return False
        
        # Check if template is in manifest
        templates = self.manifest.get('templates', {})
        if template_name not in templates:
            logger.info(f"Template '{template_name}' not in pre-approved list")
            return False
        
        # Calculate actual checksum
        try:
            actual_checksum = self.calculate_template_checksum(template_path)
        except Exception as e:
            logger.error(f"Failed to calculate checksum for {template_path}: {e}")
            return False
        
        # Compare with expected checksum
        expected_checksum = templates[template_name].get('checksum', '').replace('sha256:', '')
        
        if actual_checksum != expected_checksum:
            logger.warning(
                f"Template '{template_name}' has been modified! "
                f"Expected: {expected_checksum}, Got: {actual_checksum}"
            )
            return False
        
        logger.info(f"Template '{template_name}' is pre-approved and unmodified")
        return True
    
    def get_template_description(self, template_name: str) -> Optional[str]:
        """Get description of a pre-approved template."""
        if not self.manifest:
            return None
        
        templates = self.manifest.get('templates', {})
        template_data = templates.get(template_name, {})
        return template_data.get('description')
    
    def list_pre_approved_templates(self) -> Dict[str, str]:
        """Get list of all pre-approved templates with descriptions."""
        if not self.manifest:
            return {}
        
        templates = self.manifest.get('templates', {})
        return {
            name: data.get('description', '')
            for name, data in templates.items()
        }