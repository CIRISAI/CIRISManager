# Telemetry System Deployment Guide

## Overview
This guide covers the complete deployment of the CIRISManager telemetry system using CI/CD automation.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   GitHub     │────▶│   CI/CD      │────▶│  Production  │
│   Actions    │     │   Pipeline   │     │   Server     │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │  TimescaleDB │
                     │   Database   │
                     └──────────────┘
```

## Prerequisites

### Local Development
- Docker and Docker Compose
- Python 3.12+
- PostgreSQL client tools
- GitHub CLI (`gh`)

### Production Server
- Ubuntu 22.04 or later
- Docker installed
- systemd for service management
- SSH access with sudo privileges

## Quick Start

### 1. Local Development

```bash
# Clone repository
git clone https://github.com/your-org/CIRISManager.git
cd CIRISManager

# Copy environment template
cp .env.telemetry.example .env.telemetry
# Edit .env.telemetry with your settings

# Start local telemetry stack
docker-compose -f docker-compose.telemetry.yml up -d

# Run migrations
./scripts/deploy-telemetry.sh

# Access services
# - TimescaleDB: localhost:5432
# - Grafana: http://localhost:3000 (admin/admin)
# - Prometheus: http://localhost:9090
```

### 2. CI/CD Setup

```bash
# Configure GitHub secrets
./scripts/setup-ci-secrets.sh

# Verify workflow
gh workflow view deploy-telemetry.yml

# Trigger manual deployment
gh workflow run deploy-telemetry.yml -f environment=production
```

### 3. Production Deployment

The CI/CD pipeline automatically:
1. Runs tests against telemetry code
2. Builds TimescaleDB Docker image
3. Runs database migrations
4. Deploys telemetry service
5. Verifies deployment health
6. Sets up monitoring

## Manual Deployment

If you need to deploy manually:

```bash
# SSH to production server
ssh root@108.61.119.117

# Run deployment script
cd /opt/ciris-manager
./scripts/deploy-telemetry.sh
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TELEMETRY_DB_HOST` | Database host | localhost |
| `TELEMETRY_DB_PORT` | Database port | 5432 |
| `TELEMETRY_DB_NAME` | Database name | telemetry |
| `TELEMETRY_DB_USER` | Database user | ciris |
| `TELEMETRY_DB_PASSWORD` | Database password | (required) |
| `TELEMETRY_COLLECTION_INTERVAL` | Collection interval (seconds) | 60 |
| `TELEMETRY_RETENTION_DAYS` | Data retention period | 30 |
| `TELEMETRY_PUBLIC_API` | Enable public API | true |

### Database Configuration

The system uses TimescaleDB with:
- Automatic partitioning by time
- Continuous aggregates for performance
- Compression for older data
- Retention policies

### Collectors

Enable/disable specific collectors in `/etc/ciris-manager/telemetry.yml`:

```yaml
collectors:
  docker: true      # Container metrics
  agents: true      # Agent operational metrics
  deployments: true # Deployment tracking
  versions: true    # Version adoption
```

## Monitoring

### Health Checks

```bash
# Check telemetry health
curl http://localhost:8888/telemetry/health

# Response:
{
  "status": "healthy",
  "collection_status": "active",
  "last_collection_time": "2025-08-13T10:30:00Z",
  "database_connected": true,
  "collectors_enabled": {
    "docker": true,
    "agents": true,
    "deployments": true,
    "versions": true
  }
}
```

### Grafana Dashboards

Access Grafana at http://localhost:3000:
1. Login with admin/admin
2. Navigate to Dashboards → CIRIS Telemetry
3. View real-time metrics

Available dashboards:
- Container CPU/Memory usage
- Agent health status
- Cognitive state distribution
- Messages and incidents
- Deployment status

### Prometheus Metrics

Access Prometheus at http://localhost:9090 for:
- Collection duration metrics
- Error rates
- Database query performance
- API response times

## API Endpoints

### Internal API

```bash
# Get current status
GET /telemetry/status

# Get historical data
GET /telemetry/history?hours=24&interval=5m

# Query specific metrics
POST /telemetry/query
{
  "start_time": "2025-08-13T00:00:00Z",
  "end_time": "2025-08-13T23:59:59Z",
  "metrics": ["cpu", "memory", "messages"]
}

# Trigger manual collection
POST /telemetry/collect
```

### Public API

```bash
# Public status (sanitized)
GET /telemetry/public/status

# Public history (aggregated only)
GET /telemetry/public/history
```

## Database Management

### Migrations

Migrations are automatically applied during deployment. Manual migration:

```bash
# Apply all migrations
for migration in migrations/telemetry/*.sql; do
  psql -U ciris -d telemetry -f "$migration"
done

# Check migration status
psql -U ciris -d telemetry -c "SELECT * FROM schema_migrations;"
```

### Backup and Restore

```bash
# Backup database
pg_dump -U ciris -d telemetry > telemetry_backup.sql

# Restore database
psql -U ciris -d telemetry < telemetry_backup.sql
```

### Data Retention

Default retention policies:
- Raw metrics: 7 days
- 5-minute aggregates: 30 days
- Hourly aggregates: 90 days
- Daily summaries: 1 year

Modify retention:

```sql
-- Change container metrics retention to 14 days
SELECT alter_job(
  (SELECT job_id FROM timescaledb_information.jobs
   WHERE hypertable_name = 'container_metrics'),
  config => '{"drop_after": "14 days"}'
);
```

## Troubleshooting

### Common Issues

#### Database Connection Failed
```bash
# Check database is running
docker ps | grep timescaledb

# Test connection
psql -h localhost -U ciris -d telemetry -c "SELECT 1;"

# Check logs
docker logs ciris-timescaledb
```

#### No Data Being Collected
```bash
# Check service status
systemctl status ciris-manager

# Check telemetry is enabled
grep "enabled: true" /etc/ciris-manager/telemetry.yml

# Check logs
journalctl -u ciris-manager -n 100
```

#### High Memory Usage
```bash
# Check database connections
psql -U ciris -d telemetry -c "SELECT count(*) FROM pg_stat_activity;"

# Vacuum database
psql -U ciris -d telemetry -c "VACUUM ANALYZE;"

# Check compression status
psql -U ciris -d telemetry -c "SELECT * FROM timescaledb_information.compressed_chunk_stats;"
```

### Debug Mode

Enable debug logging:

```yaml
# /etc/ciris-manager/telemetry.yml
telemetry:
  log_level: DEBUG
```

Then restart service:
```bash
systemctl restart ciris-manager
```

## Security

### Database Security

1. Use strong passwords
2. Enable SSL for connections
3. Restrict network access
4. Regular security updates

### API Security

1. OAuth authentication for internal API
2. Rate limiting on public endpoints
3. CORS configuration
4. Input validation

### Secrets Management

Never commit secrets. Use:
- GitHub Secrets for CI/CD
- Environment variables for local dev
- Encrypted config files for production

## Performance Tuning

### Database Optimization

```sql
-- Update statistics
ANALYZE;

-- Reindex for better performance
REINDEX DATABASE telemetry;

-- Check slow queries
SELECT * FROM pg_stat_statements
ORDER BY total_time DESC
LIMIT 10;
```

### Collection Optimization

Adjust collection interval based on needs:
- Production: 60 seconds
- Staging: 120 seconds
- Development: 300 seconds

## Rollback Procedure

If deployment fails, the CI/CD automatically rolls back. Manual rollback:

```bash
# Disable telemetry
sed -i 's/enabled: true/enabled: false/' /etc/ciris-manager/telemetry.yml

# Restart service
systemctl restart ciris-manager

# Restore previous database if needed
psql -U ciris -d telemetry < telemetry_backup_previous.sql
```

## Support

### Logs

- Service logs: `journalctl -u ciris-manager`
- Database logs: `docker logs ciris-timescaledb`
- Grafana logs: `docker logs ciris-grafana`
- CI/CD logs: GitHub Actions tab

### Monitoring Alerts

Configure alerts in Grafana for:
- Collection failures
- High error rates
- Database connectivity issues
- Disk space warnings

### Contact

- GitHub Issues: [Report bugs](https://github.com/your-org/CIRISManager/issues)
- Slack: #ciris-telemetry channel
- Email: ops@ciris.ai

## Appendix

### A. Complete CI/CD Flow

1. Developer pushes to main branch
2. GitHub Actions triggered
3. Tests run (pytest)
4. Docker image built
5. Migrations applied
6. Service deployed
7. Health checks performed
8. Monitoring verified
9. Notifications sent

### B. Database Schema

See `/migrations/telemetry/` for complete schema.

Key tables:
- `container_metrics` - Container resource usage
- `agent_metrics` - Agent operational data
- `deployments` - Deployment tracking
- `system_summaries` - Pre-aggregated summaries

### C. API Response Examples

```json
// GET /telemetry/health
{
  "status": "healthy",
  "collection_status": "active",
  "last_collection_time": "2025-08-13T10:30:00Z",
  "database_connected": true,
  "collectors_enabled": {
    "docker": true,
    "agents": true,
    "deployments": true,
    "versions": true
  },
  "collection_interval": 60,
  "storage_enabled": true
}

// GET /telemetry/public/status
{
  "timestamp": "2025-08-13T10:30:00Z",
  "total_agents": 5,
  "healthy_percentage": 80.0,
  "total_messages": 5000,
  "total_incidents": 10,
  "deployment_active": false
}
```

---
*Last Updated: 2025-08-13*
*Version: 1.0.0*
