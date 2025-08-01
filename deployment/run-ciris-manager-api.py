#!/usr/bin/env python3
"""
Standalone CIRISManager API runner for production.
Runs only the API without container management or watchdog.
"""
import asyncio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
import sys
import os
import logging

# Add parent directory to path to import ciris_manager
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ciris_manager.api.routes import create_routes
from ciris_manager.api.auth import create_auth_routes, load_oauth_config
from ciris_manager.manager import CIRISManager

logger = logging.getLogger(__name__)

# Create a minimal manager instance for the API
# Load config from environment variable if set
config_path = os.environ.get('CIRIS_MANAGER_CONFIG')
if config_path:
    from ciris_manager.config.settings import CIRISManagerConfig
    config = CIRISManagerConfig.from_file(config_path)
    manager = CIRISManager(config)
else:
    from ciris_manager.config.settings import CIRISManagerConfig
    config = CIRISManagerConfig()
    manager = CIRISManager(config)

# Check auth mode and log startup message
if config.auth.mode == "development":
    print("⚠️  WARNING: Development authentication mode is active. Do not use in production.")
    logger.warning("Development authentication mode is active. Do not use in production.")
    os.environ["CIRIS_AUTH_MODE"] = "development"
else:
    print("✅ Production authentication mode is active")
    logger.info("Production authentication mode is active")
    os.environ["CIRIS_AUTH_MODE"] = "production"

app = FastAPI(title="CIRISManager API", version="1.0.0")

# Include main routes
router = create_routes(manager)
app.include_router(router, prefix="/manager/v1")

# Include auth routes and configure OAuth based on mode
if config.auth.mode == "production":
    auth_router = create_auth_routes()
    app.include_router(auth_router, prefix="/manager/v1")
    
    # Load OAuth configuration
    if not load_oauth_config():
        print("WARNING: OAuth not configured. Authentication will not work.")
    else:
        print("OAuth configured successfully")
else:
    # In development mode, skip OAuth setup entirely
    print("Development mode: OAuth authentication disabled")

# Add OAuth callback redirect for Google Console compatibility
@app.get("/manager/oauth/callback")
async def oauth_callback_compat(request: Request):
    """Redirect from Google's registered URL to our actual endpoint"""
    return RedirectResponse(
        url=f"/manager/v1/oauth/callback?{request.url.query}",
        status_code=307  # Temporary redirect, preserves method
    )

# Add Manager callback redirect for OAuth flow
@app.get("/manager/callback")
async def manager_callback_compat(request: Request):
    """Redirect from manager callback to v1 endpoint"""
    return RedirectResponse(
        url=f"/manager/v1/callback?{request.url.query}",
        status_code=307  # Temporary redirect, preserves method
    )

async def startup_event():
    """Run startup tasks including nginx config sync."""
    try:
        # Update nginx config on startup to ensure it's in sync
        logger.info("Updating nginx configuration on startup...")
        await manager.update_nginx_config()
        logger.info("Nginx configuration updated successfully")
    except Exception as e:
        logger.error(f"Failed to update nginx configuration on startup: {e}")
        # Don't fail startup if nginx update fails

app.add_event_handler("startup", startup_event)

if __name__ == "__main__":
    # Run the API server
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8888,
        log_level="info"
    )