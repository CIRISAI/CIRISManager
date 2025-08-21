#!/usr/bin/env python3
"""
CLI for deployment token management.

Usage:
    ciris-manager tokens show        # Show all tokens for GitHub configuration
    ciris-manager tokens regenerate <repo>  # Regenerate token for specific repo
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import click  # noqa: E402
from ciris_manager.deployment_tokens import DeploymentTokenManager  # noqa: E402


@click.group()
def tokens():
    """Manage deployment tokens for CI/CD pipelines."""
    pass


@tokens.command()
def show():
    """Show all deployment tokens for GitHub secrets configuration."""
    manager = DeploymentTokenManager()
    manager.print_github_secrets()


@tokens.command()
@click.argument("repo", type=click.Choice(["agent", "gui", "legacy"]))
def regenerate(repo):
    """Regenerate deployment token for a specific repository."""
    manager = DeploymentTokenManager()
    new_token = manager.regenerate_token(repo)

    click.echo(f"\n✅ Regenerated token for {repo}")
    click.echo(f"\nNew token: {new_token}")
    click.echo("\n⚠️  Remember to update this in GitHub secrets!")

    if repo == "agent":
        click.echo("Repository: CIRISAI/CIRISAgent")
    elif repo == "gui":
        click.echo("Repository: CIRISAI/CIRISGUI")

    click.echo("Secret name: DEPLOY_TOKEN")
    click.echo(f"Secret value: {new_token}\n")


@tokens.command()
def init():
    """Initialize deployment tokens (creates if missing)."""
    manager = DeploymentTokenManager()
    tokens = manager.get_all_tokens()

    click.echo("\n✅ Deployment tokens initialized!")
    click.echo(f"Found {len(tokens)} tokens\n")

    for repo, token in tokens.items():
        click.echo(f"  • {repo}: {'✓' if token else '✗'}")

    click.echo("\nRun 'ciris-manager tokens show' to see GitHub configuration")


if __name__ == "__main__":
    tokens()
