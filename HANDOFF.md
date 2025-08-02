# CIRISManager Production Issue Handoff

## Current Critical Issue
**Status**: Manager service is down (502 errors) due to permission error on startup

### Error
```
Error running CIRISManager: [Errno 13] Permission denied: '/home/ciris/nginx'
```

### What We Know
1. The directory `/home/ciris/nginx` exists with correct permissions:
   ```
   drwxrwxr-x  2 ciris-manager ciris
   ```

2. The ciris-manager user has correct groups:
   ```
   uid=996(ciris-manager) gid=988(ciris-manager) groups=988(ciris-manager),110(docker),1005(ciris)
   ```

3. Manual test shows ciris-manager CAN write to the directory:
   ```bash
   sudo -u ciris-manager touch /home/ciris/nginx/test.txt  # Works!
   ```

4. Service is in a restart loop (160+ restarts)

### What We've Done
1. **Removed ciris-manager-api service** - This was the old API-only service, now integrated into main ciris-manager
2. **Fixed OAuth authentication** - Was failing due to Path.home() returning /nonexistent for system users
3. **Improved error logging** - Just deployed better logging to diagnose the exact failure point

### Next Steps
1. Check the improved logs after CD deploys:
   ```bash
   ssh -i ~/.ssh/ciris_deploy root@108.61.119.117
   journalctl -u ciris-manager -f
   ```

2. The new logging will show:
   - Exact initialization step that fails
   - Current user/uid/gid when permission denied occurs
   - Whether it's the directory check or write test failing
   - Full traceback with line numbers

### Possible Causes
1. **SystemD security restrictions** - The service file has many security restrictions that might block access
2. **SELinux/AppArmor** - Could be blocking access despite filesystem permissions
3. **Different code path** - The main binary might be doing something different than our manual tests

### Quick Fixes to Try
1. **Temporarily disable SystemD security**:
   ```bash
   # Edit /etc/systemd/system/ciris-manager.service
   # Comment out all the security restrictions (ProtectSystem, PrivateTmp, etc)
   systemctl daemon-reload
   systemctl restart ciris-manager
   ```

2. **Check for SELinux denials**:
   ```bash
   ausearch -m avc -ts recent
   getenforce  # Check if SELinux is enforcing
   ```

3. **Run service manually as ciris-manager**:
   ```bash
   sudo -u ciris-manager /opt/ciris-manager/venv/bin/ciris-manager --config /etc/ciris-manager/config.yml
   ```

### Version Tracking Feature
- We manually triggered a deployment to test version tracking
- Can't verify if it worked because manager is down
- Check https://agents.ciris.ai/versions once service is running

### Access Details
- Server: `ssh -i ~/.ssh/ciris_deploy root@108.61.119.117`
- Manager endpoint: https://agents.ciris.ai/manager/v1/health
- Deployment token: In environment variable `$CIRIS_DEPLOY_TOKEN`

### Recent Changes Summary
1. Removed all references to deprecated ciris-manager-api service
2. Fixed SQLite database path to use HOME environment variable
3. Removed mkdir from nginx_manager.py (directory should pre-exist)
4. Added comprehensive error logging throughout initialization

The service SHOULD work - all permissions look correct. The improved logging will reveal what's actually failing.