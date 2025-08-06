"""
Cryptographic utilities for CIRISManager.

Provides encryption for sensitive data at rest using Fernet (symmetric encryption).
"""

import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class TokenEncryption:
    """Handles encryption/decryption of service tokens."""

    def __init__(self, key: Optional[str] = None):
        """
        Initialize encryption with a key.

        Args:
            key: Base64 encoded Fernet key. If None, generates from environment.
        """
        if key:
            self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
        else:
            # Derive key from environment secret
            self.cipher = self._get_cipher()

    def _get_cipher(self) -> Fernet:
        """Get or create encryption cipher from environment."""
        # Try to get existing key
        encryption_key = os.getenv("CIRIS_ENCRYPTION_KEY")

        if encryption_key:
            try:
                return Fernet(encryption_key.encode())
            except Exception as e:
                logger.error(f"Invalid encryption key: {e}")

        # Generate key from password if no direct key
        password = os.getenv("MANAGER_JWT_SECRET", "default-dev-secret").encode()
        salt = os.getenv("CIRIS_ENCRYPTION_SALT", "ciris-salt-v1").encode()

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password))

        logger.warning("Using derived encryption key. Set CIRIS_ENCRYPTION_KEY for production.")
        return Fernet(key)

    def encrypt_token(self, token: str) -> str:
        """
        Encrypt a service token.

        Args:
            token: Plain text token

        Returns:
            Base64 encoded encrypted token
        """
        try:
            encrypted = self.cipher.encrypt(token.encode())
            return base64.urlsafe_b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"Failed to encrypt token: {e}")
            raise

    def decrypt_token(self, encrypted_token: str) -> str:
        """
        Decrypt a service token.

        Args:
            encrypted_token: Base64 encoded encrypted token

        Returns:
            Plain text token
        """
        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted_token.encode())
            decrypted = self.cipher.decrypt(encrypted_bytes)
            return str(decrypted.decode())
        except Exception as e:
            logger.error(f"Failed to decrypt token: {e}")
            raise


# Global instance
_token_encryption = None


def get_token_encryption() -> TokenEncryption:
    """Get global token encryption instance."""
    global _token_encryption
    if _token_encryption is None:
        _token_encryption = TokenEncryption()
    return _token_encryption
