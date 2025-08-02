# CIRISManager Production Handoff Package

## Current Status
**Service Status**: ✅ Running (was down for ~3 hours due to systemd permission issue)
**Health Check**: ✅ Working - https://agents.ciris.ai/manager/v1/health returns `{"status":"healthy","service":"ciris-manager"}`
**OAuth Auth**: ❌ Failing - Returns `{"detail":"Authentication failed"}`

## What Was Fixed

### 1. Service Startup Permission Error (RESOLVED)
**Issue**: Service failed with `[Errno 13] Permission denied: '/home/ciris/nginx'`

**Root Cause**: SystemD service file had `ProtectHome=true` which blocks ALL access to `/home` directories, even if listed in `ReadWritePaths`

**Solution**: Changed to `ProtectHome=read-only` in `/etc/systemd/system/ciris-manager.service`

**Key Learning**: SystemD security directives can override filesystem permissions. Even with correct ownership and chmod, `ProtectHome=true` will block access.

### 2. OAuth Authentication Failure (CURRENT ISSUE)
**Symptoms**: 
- Manager GUI redirects to Google OAuth successfully
- After OAuth callback, returns `{"detail":"Authentication failed"}`
- This suggests OAuth flow completes but token validation fails

**Previous Fix That Worked**: Changed SQLite database path resolution from `Path.home()` to `os.environ.get("HOME", Path.home())` because system users have `Path.home()` = `/nonexistent`

**Current Issue**: Authentication is still failing despite the database path fix

## Recent Changes Made

1. **Removed ciris-manager-api service** - This was the old API-only service, now integrated into main ciris-manager
2. **Fixed SQLite database path** - Now uses HOME environment variable instead of Path.home()
3. **Improved error logging** - Added detailed logging throughout initialization
4. **Fixed SystemD permissions** - Changed ProtectHome from true to read-only
5. **Code formatting** - Applied ruff formatting to pass CI/CD

## OAuth Configuration Status

### Environment Variables Required
```bash
# In /etc/ciris-manager/environment
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
JWT_SECRET_KEY=your-jwt-secret
HOME=/var/lib/ciris-manager
```

### Google OAuth Console Settings
- Redirect URI should be: `https://agents.ciris.ai/manager/v1/auth/oauth/google/callback`
- Authorized domains should include: `ciris.ai`

## Debugging Steps

### 1. Check OAuth Configuration
```bash
ssh -i ~/.ssh/ciris_deploy root@108.61.119.117

# Check if OAuth env vars are set
grep GOOGLE /etc/ciris-manager/environment

# Check JWT secret
grep JWT_SECRET_KEY /etc/ciris-manager/environment
```

### 2. Check Database Access
```bash
# Check if auth database exists and is accessible
ls -la /var/lib/ciris-manager/.config/ciris-manager/auth.db

# Check database permissions
sudo -u ciris-manager sqlite3 /var/lib/ciris-manager/.config/ciris-manager/auth.db .tables
```

### 3. Check Detailed Logs
```bash
# Get auth-specific logs
journalctl -u ciris-manager --since "10 minutes ago" | grep -i auth

# Check for OAuth callback logs
journalctl -u ciris-manager --since "10 minutes ago" | grep -i "oauth\|google\|callback"
```

### 4. Test OAuth Flow Manually
1. Open browser dev tools Network tab
2. Go to https://agents.ciris.ai/manager/
3. Click login
4. Watch for:
   - Redirect to Google OAuth
   - Callback to `/manager/v1/auth/oauth/google/callback`
   - Any error responses

## Possible Causes of Auth Failure

1. **Missing/Invalid OAuth Credentials** - GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET not set correctly
2. **JWT Secret Mismatch** - JWT_SECRET_KEY might be different or missing
3. **Database Issues** - Auth database might not be initialized or accessible
4. **Domain Mismatch** - OAuth redirect URI might not match exactly
5. **Cookie Issues** - Manager expects token in `managerToken` cookie

## Quick Fixes to Try

### 1. Verify OAuth Environment
```bash
# On server
systemctl show ciris-manager --property=Environment
```

### 2. Restart with Fresh Database
```bash
# Backup existing database
mv /var/lib/ciris-manager/.config/ciris-manager/auth.db /tmp/auth.db.backup

# Restart service (will create new database)
systemctl restart ciris-manager
```

### 3. Check OAuth Callback URL
Make sure Google OAuth console has EXACTLY:
```
https://agents.ciris.ai/manager/v1/auth/oauth/google/callback
```

## Access Information
- **Server**: `ssh -i ~/.ssh/ciris_deploy root@108.61.119.117`
- **Manager API**: https://agents.ciris.ai/manager/v1/health
- **Manager GUI**: https://agents.ciris.ai/manager/
- **Service**: `systemctl status ciris-manager`
- **Logs**: `journalctl -u ciris-manager -f`

## Version Tracking Feature
Once auth is working, version tracking is available at:
- https://agents.ciris.ai/manager/v1/versions/adoption
- Shows which agents are running which versions
- Tracks deployment history

## Summary
The service is running correctly now. The remaining issue is OAuth authentication failing after the callback. This needs investigation into the OAuth configuration and database initialization.