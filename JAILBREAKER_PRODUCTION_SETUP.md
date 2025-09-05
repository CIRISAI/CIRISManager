# Jailbreaker Production Setup

The jailbreaker service is currently showing "Not Configured" because Discord credentials are missing on the production server.

## Required Environment Variables

The following environment variables need to be set on the production server for the jailbreaker service to initialize:

```bash
# Required Discord OAuth credentials
DISCORD_CLIENT_ID="your_discord_app_client_id"
DISCORD_CLIENT_SECRET="your_discord_app_client_secret"

# Optional (have defaults)
DISCORD_GUILD_ID="1364300186003968060"
JAILBREAK_ROLE_NAME="jailbreak"
JAILBREAK_TARGET_AGENT="echo-nemesis-v2tyey"
JAILBREAK_AGENT_SERVICE_TOKEN="datum_service_token"
```

## Discord Application Setup

1. **Create Discord Application** (if not already done):
   - Go to https://discord.com/developers/applications
   - Create new application or use existing
   - Note the **Application ID** (Client ID)

2. **Get Client Secret**:
   - In your Discord app settings, go to "OAuth2" → "General"
   - Copy the **Client Secret**

3. **Configure OAuth2 Redirect URI**:
   - In OAuth2 settings, add redirect URI:
   - `https://agents.ciris.ai/jailbreaker/result`

4. **Required Scopes**:
   - `identify` - Get user info
   - `guilds.members.read` - Check guild membership

## Production Server Configuration

SSH into the production server and add the environment variables to the CIRISManager service:

```bash
# SSH to production server
ssh root@108.61.119.117

# Edit the environment file
nano /etc/ciris-manager/environment

# Add these lines:
DISCORD_CLIENT_ID=your_actual_client_id
DISCORD_CLIENT_SECRET=your_actual_client_secret
JAILBREAK_AGENT_SERVICE_TOKEN=actual_datum_token

# Restart CIRISManager service
systemctl restart ciris-manager

# Verify service started successfully
systemctl status ciris-manager
```

## Verification

After configuring the environment variables:

1. **Check service logs**:
   ```bash
   journalctl -u ciris-manager -f
   ```
   Look for: "Jailbreaker service initialized successfully"

2. **Test API endpoint**:
   ```bash
   curl https://agents.ciris.ai/manager/v1/jailbreaker/status
   ```
   Should return service status instead of "Not Found"

3. **Visit landing page**:
   - Go to https://agents.ciris.ai/jailbreaker/
   - Service Status should show "Online" instead of "Not Configured"
   - Discord login button should be enabled

## Discord Guild Setup

Ensure the Discord guild has the required role:

1. **Create "jailbreak" role** in the CIRIS Discord server
2. **Assign the role** to authorized users
3. **Test the flow** with a user who has the jailbreak role

## Troubleshooting

- **"Service not configured"**: Discord credentials missing from environment
- **"Authentication failed"**: Invalid Discord credentials or app setup
- **"No permissions"**: User doesn't have jailbreak role in the guild
- **"Rate limited"**: Recent reset performed, wait for cooldown

The jailbreaker service will only initialize and create API endpoints if the Discord credentials are properly configured in the production environment.