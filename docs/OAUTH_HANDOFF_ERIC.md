# OAuth Setup Handoff

**Date**: 2025-08-03
**From**: Tyler
**To**: Eric
**Context**: OAuth modal infrastructure is complete and ready for production verification

## Summary

The OAuth setup modal is implemented and working. Each agent requires manual OAuth configuration in the provider consoles (Google, GitHub, Discord) due to API limitations - there's no programmatic way to register redirect URIs.

## What's Been Built

### Frontend (Manager GUI)
- **Modal UI**: Shows OAuth callback URLs for all three providers
- **Copy buttons**: One-click copy for each callback URL
- **Status tracking**: Agents can be marked as "oauth configured"
- **Verify button**: Checks if OAuth is properly set up

### Backend (Manager API)
- **OAuth status field**: Added to AgentInfo model (pending/configured/verified)
- **API endpoints**:
  - `GET /manager/v1/agents/{agent_id}/oauth/verify` - Verify OAuth setup
  - `POST /manager/v1/agents/{agent_id}/oauth/complete` - Mark as configured
- **Persistence**: OAuth status saved to metadata.json

## Production Verification Steps

### 1. Test the Modal Flow
```bash
# On production server
cd /opt/ciris-manager

# Check that OAuth status is being tracked
cat /opt/ciris/agents/metadata.json | jq '.agents[].oauth_status'
```

### 2. Verify Nginx Routing
Each agent needs these OAuth callback routes in nginx:
```nginx
# Pattern: /api/{agent_id}/v1/auth/oauth/{provider}/callback
location ~ ^/api/([^/]+)/v1/auth/oauth/(google|github|discord)/callback$ {
    proxy_pass http://agent_$1;
}
```

### 3. Test OAuth Flow for One Agent
Pick a test agent (e.g., datum) and verify:
1. Open Manager GUI
2. Click gear icon → "Configure OAuth"
3. Modal shows correct callback URLs
4. Copy each URL and verify format

## Setting Up OAuth Providers

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select or create a project
3. Navigate to "APIs & Services" → "Credentials"
4. Click "Create Credentials" → "OAuth client ID"
5. Application type: "Web application"
6. Add authorized redirect URIs for EACH agent:
   ```
   https://agents.ciris.ai/api/datum/v1/auth/oauth/google/callback
   https://agents.ciris.ai/api/aurora/v1/auth/oauth/google/callback
   https://agents.ciris.ai/api/sage/v1/auth/oauth/google/callback
   # ... etc for each agent
   ```
7. Save Client ID and Client Secret

### GitHub OAuth Setup

1. Go to GitHub Settings → Developer settings → OAuth Apps
2. Click "New OAuth App"
3. Fill in:
   - Application name: "CIRIS Agents"
   - Homepage URL: `https://agents.ciris.ai`
   - Authorization callback URL: You'll need ONE app per agent:
     ```
     https://agents.ciris.ai/api/datum/v1/auth/oauth/github/callback
     ```
4. Save Client ID and Client Secret

**Note**: GitHub only allows one callback URL per app, so you need separate apps for each agent.

### Discord OAuth Setup

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application"
3. Go to OAuth2 → General
4. Add redirect URLs for ALL agents:
   ```
   https://agents.ciris.ai/api/datum/v1/auth/oauth/discord/callback
   https://agents.ciris.ai/api/aurora/v1/auth/oauth/discord/callback
   https://agents.ciris.ai/api/sage/v1/auth/oauth/discord/callback
   ```
5. Save Client ID and Client Secret

## Environment Variables per Agent

Each agent needs these environment variables in their `.env` file:

```env
# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# GitHub OAuth
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret

# Discord OAuth
DISCORD_CLIENT_ID=your-discord-client-id
DISCORD_CLIENT_SECRET=your-discord-client-secret
```

## Why Manual Configuration?

We investigated automating this, but:
- Google OAuth API doesn't support programmatically adding redirect URIs
- GitHub requires one OAuth app per callback URL
- Discord allows multiple URLs but still requires manual setup

The modal makes the manual process as smooth as possible by:
- Showing all URLs in one place
- Providing one-click copy
- Tracking configuration status

## Next Steps

1. **Verify modal on production** - Ensure it opens and shows correct URLs
2. **Test with one agent** - Pick datum or another test agent
3. **Document credentials** - Store OAuth credentials securely
4. **Update agent configs** - Add OAuth env vars to each agent
5. **Mark as configured** - Use the modal to track progress

## Questions or Issues?

The code is clean and straightforward:
- Frontend: `static/manager/index.html` (modal HTML)
- JavaScript: `static/manager/manager.js` (modal logic)
- Backend: `api/routes.py` (OAuth endpoints)

No clever tricks or hidden complexity - just a simple modal that helps track manual OAuth setup.
