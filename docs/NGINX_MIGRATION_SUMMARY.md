# Nginx Migration Summary

## What Changed

### Before
- Nginx lived in CIRISAgent repository
- Complex dual-config system (static + dynamic with includes)
- Config written to `/opt/ciris-manager/nginx/agents.conf`
- Default route `/v1/` pointed to arbitrary "default" agent
- Confusion about which repository owned routing

### After  
- Nginx lives in CIRISManager repository (infrastructure ownership)
- Single nginx.conf file with all configuration
- Config written to `/home/ciris/nginx/nginx.conf`
- No default routes - explicit agent specification required
- Clear separation: Manager owns infrastructure, Agent owns applications

## Files Changed

### CIRISManager
1. **nginx_manager.py**
   - Generates complete nginx.conf instead of partial agents.conf
   - Removed default route generation
   - Updated path to `/home/ciris/nginx/nginx.conf`
   - Removed obsolete `_generate_agent_routes` method

2. **CLAUDE.md**
   - Added core development principles section
   - Updated nginx documentation to reflect single-file approach
   - Documented GUI architecture (Manager vs Agent)
   - Updated all paths and removed dual-config references

3. **README.md**
   - Updated nginx management section
   - Removed references to partial configs and default routes

4. **config/settings.py**
   - Updated default nginx directory to `/home/ciris/nginx`

5. **docker-compose-production.yml**
   - Created production compose file with proper nginx setup
   - Single volume mount for nginx.conf

6. **Removed Files**
   - `deployment/nginx-config-migration.sh` (obsolete)
   - References to dual config loading

### CIRISAgent (via other Claude)
1. **Removed nginx from all docker-compose files**
2. **Updated GUI to support dual-mode deployment**
3. **Updated documentation to reflect nginx living in Manager**

## Key Architectural Decisions

### Why Single File?
- Debugging simplicity - one place to look
- No include complexity or load order issues  
- Complete view of routing in one file
- Atomic updates (write new, validate, swap)

### Why No Default Routes?
- Explicit agent specification prevents ambiguity
- Same behavior with 0, 1, or N agents
- Clean OAuth callback URLs
- Portable code and configurations

### Why Manager Owns Nginx?
- Infrastructure (routing) is Manager's responsibility
- Agents shouldn't know about routing
- Clean separation of concerns
- Manager can manage any agent

## Testing Changes

Updated test files to verify:
- No default routes are generated
- All agents get explicit routes
- Empty agent list still produces valid config
- Manager GUI is accessible at root

## Migration Path for Existing Deployments

1. Stop existing nginx
2. Deploy CIRISManager with nginx container
3. Ensure volume mount points to `/home/ciris/nginx/nginx.conf`
4. Start CIRISManager - it will generate complete config
5. Verify routing works for all agents

## Lessons Codified

See `docs/NGINX_ARCHITECTURE_LESSONS.md` for detailed exploration of:
- Why simplicity beats cleverness
- Why explicit beats implicit  
- Why boring solutions last longer
- Why one file beats many with includes

## Result

A simpler, clearer architecture where:
- One process (Manager) writes one file (nginx.conf)
- One container (nginx) reads that file
- Every route is explicit and predictable
- The whole system can be explained in one paragraph