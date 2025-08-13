#!/bin/bash
# Script to set up GitHub secrets for CI/CD
# Run this locally with GitHub CLI installed

set -e

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "GitHub CLI (gh) is not installed. Please install it first:"
    echo "https://cli.github.com/"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "Please authenticate with GitHub CLI first:"
    echo "gh auth login"
    exit 1
fi

echo "Setting up GitHub secrets for telemetry CI/CD..."

# Function to set secret
set_secret() {
    local name=$1
    local value=$2
    local env=${3:-"production"}
    
    echo -n "Setting $name for $env environment... "
    if [ "$env" == "repository" ]; then
        echo "$value" | gh secret set "$name" --body=-
    else
        echo "$value" | gh secret set "$name" --env="$env" --body=-
    fi
    echo "✓"
}

# Repository-level secrets (used by all environments)
echo "Setting repository-level secrets..."

# Deployment SSH key
echo -n "Enter deployment SSH private key path [~/.ssh/ciris_deploy]: "
read SSH_KEY_PATH
SSH_KEY_PATH=${SSH_KEY_PATH:-~/.ssh/ciris_deploy}
if [ -f "$SSH_KEY_PATH" ]; then
    set_secret "DEPLOY_SSH_KEY" "$(cat $SSH_KEY_PATH)" "repository"
else
    echo "SSH key not found at $SSH_KEY_PATH"
    exit 1
fi

# Slack webhook (optional)
echo -n "Enter Slack webhook URL (optional, press enter to skip): "
read -s SLACK_WEBHOOK
echo
if [ ! -z "$SLACK_WEBHOOK" ]; then
    set_secret "SLACK_WEBHOOK" "$SLACK_WEBHOOK" "repository"
fi

# Production environment secrets
echo ""
echo "Setting production environment secrets..."

# Database credentials
echo -n "Enter production database host [108.61.119.117]: "
read DB_HOST
DB_HOST=${DB_HOST:-108.61.119.117}
set_secret "TELEMETRY_DB_HOST" "$DB_HOST" "production"

echo -n "Enter production database port [5432]: "
read DB_PORT
DB_PORT=${DB_PORT:-5432}
set_secret "TELEMETRY_DB_PORT" "$DB_PORT" "production"

echo -n "Enter production database name [telemetry]: "
read DB_NAME
DB_NAME=${DB_NAME:-telemetry}
set_secret "TELEMETRY_DB_NAME" "$DB_NAME" "production"

echo -n "Enter production database user [ciris]: "
read DB_USER
DB_USER=${DB_USER:-ciris}
set_secret "TELEMETRY_DB_USER" "$DB_USER" "production"

echo -n "Enter production database password: "
read -s DB_PASSWORD
echo
if [ -z "$DB_PASSWORD" ]; then
    echo "Database password is required"
    exit 1
fi
set_secret "TELEMETRY_DB_PASSWORD" "$DB_PASSWORD" "production"

# Deployment credentials
echo -n "Enter deployment host [108.61.119.117]: "
read DEPLOY_HOST
DEPLOY_HOST=${DEPLOY_HOST:-108.61.119.117}
set_secret "DEPLOY_HOST" "$DEPLOY_HOST" "production"

echo -n "Enter deployment user [root]: "
read DEPLOY_USER
DEPLOY_USER=${DEPLOY_USER:-root}
set_secret "DEPLOY_USER" "$DEPLOY_USER" "production"

# Staging environment (optional)
echo ""
echo -n "Do you want to set up staging environment? (y/n): "
read SETUP_STAGING

if [ "$SETUP_STAGING" == "y" ]; then
    echo "Setting staging environment secrets..."
    
    echo -n "Enter staging database host: "
    read STAGING_DB_HOST
    set_secret "TELEMETRY_DB_HOST" "$STAGING_DB_HOST" "staging"
    
    echo -n "Enter staging database password: "
    read -s STAGING_DB_PASSWORD
    echo
    set_secret "TELEMETRY_DB_PASSWORD" "$STAGING_DB_PASSWORD" "staging"
    
    # Use same values for other settings
    set_secret "TELEMETRY_DB_PORT" "$DB_PORT" "staging"
    set_secret "TELEMETRY_DB_NAME" "$DB_NAME" "staging"
    set_secret "TELEMETRY_DB_USER" "$DB_USER" "staging"
    set_secret "DEPLOY_HOST" "$STAGING_DB_HOST" "staging"
    set_secret "DEPLOY_USER" "$DEPLOY_USER" "staging"
fi

echo ""
echo "✅ GitHub secrets configured successfully!"
echo ""
echo "You can verify the secrets at:"
echo "https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/settings/secrets/actions"
echo ""
echo "To trigger deployment, either:"
echo "1. Push changes to main branch"
echo "2. Run manually: gh workflow run deploy-telemetry.yml"