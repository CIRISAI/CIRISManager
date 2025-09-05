# Jailbreaker Configuration Guide

The jailbreaker functionality allows authorized Discord users to reset the `datum` agent through a secure OAuth flow.

## Required Environment Variables

### Discord OAuth Configuration
```bash
# Required: Discord application credentials
DISCORD_CLIENT_ID="your_discord_app_client_id"
DISCORD_CLIENT_SECRET="your_discord_app_client_secret"

# Optional: Override defaults
DISCORD_GUILD_ID="1364300186003968060"  # CIRIS Discord guild ID
JAILBREAK_ROLE_NAME="jailbreak"          # Required Discord role name
JAILBREAK_TARGET_AGENT="echo-nemesis-v2tyey"  # Agent to reset (default: echo-nemesis-v2tyey)
```

### Agent Service Token (Optional)
For enhanced functionality including health checks:
```bash
# Service token for API calls to the target agent
JAILBREAK_AGENT_SERVICE_TOKEN="your_agent_service_token"
```

To extract datum's service token from production (used for Discord authentication only):
```python
import json
from cryptography.fernet import Fernet

# Production encryption key
key = '_AFlp77JRC55GooNp4BxfS7jIuDWlbhzJcRxPzjE00E='

# Read production metadata
with open('/opt/ciris/agents/metadata.json', 'r') as f:
    metadata = json.load(f)

# Find datum's encrypted token
for agent_data in metadata['agents']:
    if agent_data['agent_id'] == 'datum':
        if 'service_token' in agent_data:
            cipher = Fernet(key.encode())
            token = cipher.decrypt(agent_data['service_token'].encode()).decode()
            print(f"JAILBREAK_AGENT_SERVICE_TOKEN=\"{token}\"")
            break
```

## Discord Application Setup

1. **Create Discord Application**:
   - Go to https://discord.com/developers/applications
   - Create a new application
   - Note the Client ID and Client Secret

2. **Configure OAuth2**:
   - In your Discord app settings, go to OAuth2
   - Add redirect URI: `https://agents.ciris.ai/manager/v1/jailbreaker/callback`
   - Required scopes: `identify`, `guilds.members.read`

3. **Guild Role Setup**:
   - Create a role named `jailbreak` in your Discord guild
   - Assign this role to authorized users

## API Endpoints

Once configured, the following endpoints will be available:

- `GET /manager/v1/jailbreaker/oauth/init` - Initialize OAuth flow
- `POST /manager/v1/jailbreaker/oauth/callback` - Handle OAuth callback
- `POST /manager/v1/jailbreaker/reset` - Reset datum agent
- `GET /manager/v1/jailbreaker/status` - Get service status

## Rate Limits

- **Global**: Once per 5 minutes (all users)
- **Per-User**: Once per hour (per Discord user)

## Security Features

- Discord OAuth authentication required
- Guild membership verification
- Role-based authorization (`jailbreak` role required)
- Comprehensive audit logging
- Rate limiting to prevent abuse
- Secure token handling

## Agent Reset Process

When a reset is triggered:

1. **Authentication**: Verify Discord OAuth and jailbreak role
2. **Rate Limiting**: Check global and per-user limits
3. **Container Stop**: Gracefully stop the echo-nemesis-v2tyey container
4. **Data Wipe**: Remove all data from `/data/` directory
5. **Container Start**: Restart the echo-nemesis-v2tyey container
6. **Health Check**: Optional verification that agent restarted correctly
7. **Audit Log**: Record the reset with user attribution

## Troubleshooting

- Check CIRISManager logs for detailed operation traces
- Verify Discord credentials and callback URL configuration
- Ensure user has the `jailbreak` role in the specified guild
- Rate limits are enforced - check `/status` endpoint for timing
- Agent service token is optional but enables health monitoring

## Production Deployment

Add the environment variables to your production environment and restart CIRISManager. The jailbreaker service will auto-initialize if Discord credentials are available.
