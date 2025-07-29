**Objective:** Implement a flexible and robust Nginx integration strategy for the CIRISManager.

**Core Philosophy:** The system should remain "batteries-included" with Nginx as a core, default component, but allow advanced users to disable it cleanly for integration into custom environments. This pattern combines explicit configuration with resilient, maintainable code.

**Implementation Pattern: Config-Driven with Graceful Degradation and Null Object**

This approach is a synthesis of the most resonant probes (Probe 1, 5, 6, 7).

---

### 1. Configuration Schema (`config.yml`)

Introduce a dedicated `nginx` section in the configuration. This provides explicit, strategic control.

```yaml
# In config.yml or config.dev.yml
nginx:
  enabled: true # or false to disable
````

-----

### 2\. Null Object Pattern (`NoOpNginxManager`)

Create a new class that mirrors the public interface of the real `NginxManager` but performs no actions. This is critical for eliminating conditional `if self.nginx_manager:` checks in the core application logic.

**File:** `ciris_manager/nginx_noop.py`

```python
import logging

logger = logging.getLogger(__name__)

class NoOpNginxManager:
    """
    A Null Object implementation of the NginxManager.
    It provides the same interface but performs no operations,
    allowing the application to run seamlessly without Nginx.
    """
    def __init__(self):
        logger.info("Nginx integration is disabled. Initializing No-Op Nginx Manager.")

    async def update_config(self, agents: list) -> bool:
        """Logs the intent but does nothing."""
        logger.debug("Nginx is disabled, skipping configuration update.")
        return True

    def reload(self) -> bool:
        """Logs the intent but does nothing."""
        logger.debug("Nginx is disabled, skipping reload.")
        return True
```

-----

### 3\. Update the `CIRISManager` Initializer

Modify the `__init__` method of `CIRISManager` to be the single point of decision-making. It will read the config and initialize either the real manager or the no-op version. This implements the "Graceful Degradation."

**File:** `ciris_manager/manager.py` (or equivalent)

```python
# At the top, add the new import
from .nginx_noop import NoOpNginxManager
from .nginx_manager import NginxManager # Assuming this is the real one

class CIRISManager:
    def __init__(self, config):
        self.config = config
        self.nginx_manager = None # Initialize to None

        # Decide which Nginx manager to use
        if self.config.get('nginx', {}).get('enabled', True):
            try:
                # GRACEFUL DEGRADATION: Attempt to initialize the real manager
                self.nginx_manager = NginxManager(self.config)
                logger.info("Successfully initialized and connected to Nginx Manager.")
            except Exception as e:
                # If it fails for any reason, log it and fall back to the NoOp object
                logger.error(f"Nginx is enabled but failed to initialize: {e}", exc_info=True)
                logger.warning("Falling back to No-Op Nginx Manager to ensure application stability.")
                self.nginx_manager = NoOpNginxManager()
        else:
            # If explicitly disabled, use the NoOp object from the start
            self.nginx_manager = NoOpNginxManager()

        # ... rest of __init__ ...

    async def create_agent(self, agent_config):
        # ... logic to create agent ...

        # CRITICAL: No `if` check is needed here. The code is clean.
        # It will call the method on either the real or the no-op manager.
        await self.nginx_manager.update_config(self.get_all_agents())

        # ... other logic ...
```

-----

### Success Criteria:

1.  When `nginx.enabled` is `true` (or unset), the system functions exactly as it does now.
2.  When `nginx.enabled` is `true` but the `ciris-nginx` container is not running, the application **does not crash**. It logs a clear error and continues to function without Nginx routing.
3.  When `nginx.enabled` is `false`, the `CIRISManager` starts and runs without error, logging that Nginx is disabled. All calls to `update_config` are handled silently by the `NoOpNginxManager`.
4.  The core application logic (e.g., `create_agent`, `delete_agent`) contains no new `if/else` blocks related to Nginx's status.

<!-- end list -->
