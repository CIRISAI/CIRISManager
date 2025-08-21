"""
Deployment token management for CIRISManager.

Automatically generates and manages deployment tokens for CI/CD pipelines.
Never lose tokens again!
"""

import os
import secrets
import json
from pathlib import Path
from typing import Dict, Optional
import logging

logger = logging.getLogger("ciris_manager.deployment_tokens")


class DeploymentTokenManager:
    """Manages deployment tokens for CI/CD authentication."""

    def __init__(self, config_dir: str = "/etc/ciris-manager"):
        self.config_dir = Path(config_dir)
        self.tokens_file = self.config_dir / "deployment_tokens.json"
        self.env_file = self.config_dir / "environment"
        self.tokens = self._load_tokens()

    def _load_tokens(self) -> Dict[str, str]:
        """Load existing tokens or generate new ones."""
        tokens = {}

        # First, try to load from JSON file (persistent storage)
        if self.tokens_file.exists():
            try:
                with open(self.tokens_file, "r") as f:
                    stored = json.load(f)
                    tokens.update(stored)
                    logger.info(f"Loaded {len(stored)} deployment tokens from {self.tokens_file}")
            except Exception as e:
                logger.warning(f"Could not load tokens from {self.tokens_file}: {e}")

        # Also check environment variables for backwards compatibility
        env_tokens = {
            "legacy": os.getenv("CIRIS_DEPLOY_TOKEN"),
            "agent": os.getenv("CIRIS_AGENT_DEPLOY_TOKEN"),
            "gui": os.getenv("CIRIS_GUI_DEPLOY_TOKEN"),
        }

        for repo, token in env_tokens.items():
            if token and repo not in tokens:
                tokens[repo] = token
                logger.info(f"Loaded {repo} token from environment")

        # Generate any missing tokens
        required_repos = ["agent", "gui", "legacy"]
        for repo in required_repos:
            if repo not in tokens or not tokens[repo]:
                tokens[repo] = self._generate_token()
                logger.info(f"Generated new deployment token for {repo}")

        # Save all tokens
        self._save_tokens(tokens)

        return tokens

    def _generate_token(self) -> str:
        """Generate a secure deployment token."""
        # Use URL-safe base64 encoding for better compatibility
        return secrets.token_urlsafe(32)

    def _save_tokens(self, tokens: Dict[str, str]) -> None:
        """Save tokens to persistent storage and environment file."""
        try:
            # Ensure config directory exists
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Save to JSON file for persistence
            with open(self.tokens_file, "w") as f:
                json.dump(tokens, f, indent=2)
            # Set secure permissions
            self.tokens_file.chmod(0o600)
            logger.info(f"Saved deployment tokens to {self.tokens_file}")

            # Update environment file for systemd service
            self._update_environment_file(tokens)

        except Exception as e:
            logger.error(f"Failed to save deployment tokens: {e}")

    def _update_environment_file(self, tokens: Dict[str, str]) -> None:
        """Update the environment file with deployment tokens."""
        try:
            # Read existing environment
            env_lines = []
            if self.env_file.exists():
                with open(self.env_file, "r") as f:
                    env_lines = [
                        line.strip()
                        for line in f
                        if line.strip()
                        and not line.startswith("CIRIS")
                        or "DEPLOY_TOKEN" not in line
                    ]

            # Add deployment tokens
            env_lines.append(f"CIRIS_DEPLOY_TOKEN={tokens.get('legacy', '')}")
            env_lines.append(f"CIRIS_AGENT_DEPLOY_TOKEN={tokens.get('agent', '')}")
            env_lines.append(f"CIRIS_GUI_DEPLOY_TOKEN={tokens.get('gui', '')}")

            # Write back
            with open(self.env_file, "w") as f:
                f.write("\n".join(env_lines) + "\n")

            # Set secure permissions
            self.env_file.chmod(0o600)
            logger.info(f"Updated environment file: {self.env_file}")

        except Exception as e:
            logger.error(f"Failed to update environment file: {e}")

    def get_token(self, repo: str) -> Optional[str]:
        """Get deployment token for a specific repository."""
        return self.tokens.get(repo)

    def get_all_tokens(self) -> Dict[str, str]:
        """Get all deployment tokens."""
        return self.tokens.copy()

    def regenerate_token(self, repo: str) -> str:
        """Regenerate a deployment token for a specific repository."""
        new_token = self._generate_token()
        self.tokens[repo] = new_token
        self._save_tokens(self.tokens)
        logger.info(f"Regenerated deployment token for {repo}")
        return new_token

    def print_github_secrets(self) -> None:
        """Print tokens formatted for GitHub secrets configuration."""
        print("\n" + "=" * 60)
        print("DEPLOYMENT TOKENS FOR GITHUB SECRETS")
        print("=" * 60)
        print("\nAdd these to your GitHub repository secrets:\n")

        repos_config = {
            "agent": "CIRISAI/CIRISAgent",
            "gui": "CIRISAI/CIRISGUI",
            "legacy": "Legacy repos (if any)",
        }

        for repo, gh_repo in repos_config.items():
            token = self.tokens.get(repo, "")
            if token:
                print(f"\n{gh_repo}:")
                print("  Secret Name: DEPLOY_TOKEN")
                print(f"  Secret Value: {token}")

        print("\n" + "=" * 60)
        print("Keep these tokens secure! They authenticate deployments.")
        print("=" * 60 + "\n")

    def set_github_secrets(self) -> bool:
        """Automatically set tokens in GitHub repositories using gh CLI."""
        import subprocess

        repos_config = {
            "agent": "CIRISAI/CIRISAgent",
            "gui": "CIRISAI/CIRISGUI",
        }

        success = True
        for repo, gh_repo in repos_config.items():
            token = self.tokens.get(repo, "")
            if not token:
                logger.warning(f"No token found for {repo}")
                continue

            try:
                # Use gh CLI to set the secret
                result = subprocess.run(
                    ["gh", "secret", "set", "DEPLOY_TOKEN", "--body", token, "--repo", gh_repo],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                logger.info(f"✅ Set DEPLOY_TOKEN for {gh_repo}")
                print(f"✅ Set DEPLOY_TOKEN for {gh_repo}")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to set token for {gh_repo}: {e.stderr}")
                print(f"❌ Failed to set token for {gh_repo}: {e.stderr}")
                success = False
            except FileNotFoundError:
                logger.error("gh CLI not found. Please install GitHub CLI.")
                print("❌ gh CLI not found. Please install GitHub CLI: https://cli.github.com/")
                return False

        return success


# CLI interface for token management
if __name__ == "__main__":
    import sys

    manager = DeploymentTokenManager()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "show":
            manager.print_github_secrets()
        elif command == "set":
            if manager.set_github_secrets():
                print("\n✅ All GitHub secrets updated successfully!")
            else:
                print("\n⚠️  Some secrets failed to update. Check the errors above.")
        elif command == "regenerate" and len(sys.argv) > 2:
            repo = sys.argv[2]
            if repo in ["agent", "gui", "legacy"]:
                new_token = manager.regenerate_token(repo)
                print(f"New token for {repo}: {new_token}")
            else:
                print(f"Unknown repo: {repo}")
        else:
            print("Usage: python deployment_tokens.py [show|set|regenerate <repo>]")
    else:
        # Default: ensure tokens exist and show them
        manager.print_github_secrets()
