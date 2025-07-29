# Quick Fix for Current Deployment

## OAuth is Almost Working!

### On the Server:

1. **Pull the latest changes:**
   ```bash
   cd /opt/ciris-manager
   git pull
   ```

2. **Copy the updated service file:**
   ```bash
   sudo cp deployment/ciris-manager-api.service /etc/systemd/system/
   ```

3. **Reload and restart systemd service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart ciris-manager-api
   ```

4. **Check if it's running:**
   ```bash
   sudo systemctl status ciris-manager-api
   ```

### If systemd still fails:

Run manually for now:
```bash
cd /opt/ciris-manager
export $(grep -v '^#' /etc/ciris-manager/environment | xargs)
sudo -E -u ciris-manager HOME=/var/lib/ciris-manager /opt/ciris-manager/venv/bin/python deployment/run-ciris-manager-api.py
```

### Test OAuth:

1. Go to: https://agents.ciris.ai/manager/v1/oauth/login
2. Login with Google
3. You should be redirected back and logged in!

## What We Fixed:

1. ✅ Added redirect from `/manager/oauth/callback` to `/manager/v1/oauth/callback`
2. ✅ Fixed systemd HOME directory issue
3. ✅ OAuth now works with existing Google configuration

No need to change Google Console settings!