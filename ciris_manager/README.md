# ciris_manager

The CIRISManager service package: the systemd service that orchestrates CIRIS
agent containers across one or more Docker hosts. The project overview, setup
and operations guides live in the top-level [README](../README.md) and in
[docs/](../docs/).

## Layout

| Module | Responsibility |
|---|---|
| `manager.py` | Service entry: wires the components, owns start-up and shutdown |
| `__main__.py` | CLI: `ciris-manager --config …`, `--generate-config`, `--validate-config` |
| `config/` | Pydantic configuration loaded from YAML |
| `agent_registry.py` | Registered agents and their metadata (`metadata.json`) |
| `multi_server_docker.py` | TLS Docker clients for every configured host |
| `docker_discovery.py` | Finds running agent containers on each host |
| `compose_generator.py` | Per-agent compose files |
| `identity_volume.py` | Keeps an agent's `/app/identity` across container recreates |
| `port_manager.py` | Port allocation per agent |
| `nginx_manager.py` | Generates and deploys the single `nginx.conf` per host |
| `core/watchdog.py` | Crash-loop and absence detection (alerts only) |
| `deployment/` | Deployment orchestrator: canary, immediate and manual rollouts |
| `api/` | REST API under `/manager/v1` |
| `admin_password_reset.py` | Break-glass reset of an agent's admin password |
| `agent_auth.py`, `token_manager.py`, `crypto.py` | Agent service tokens, encrypted at rest |

## Container lifecycle

Agent containers run with `restart: 'no'`. The manager performs every start,
stop and recreate itself, over each host's Docker API; Docker never restarts an
agent on its own. The watchdog alerts on crash loops and on registered agents
with no running container, and does not restart anything. See
[docs/DOCKER_RESTART_POLICY.md](../docs/DOCKER_RESTART_POLICY.md).

## Development

```bash
pip install -e ".[dev]"
pytest tests/ciris_manager/
ruff check ciris_manager/ && mypy ciris_manager/
```
