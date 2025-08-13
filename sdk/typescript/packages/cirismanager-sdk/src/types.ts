/**
 * Type definitions for CIRIS Manager API
 * 
 * These can be auto-generated from OpenAPI spec using openapi-typescript
 */

// Agent types
export interface Agent {
  agent_id: string;
  agent_name: string;
  status: 'running' | 'stopped' | 'error';
  container_status?: string;
  container_id?: string;
  version: string;
  api_port: number;
  created_at: string;
  cognitive_state?: 'work' | 'dream' | 'play' | 'solitude';
  image?: string;
  memory_limit?: string;
  cpu_limit?: string;
  environment?: Record<string, string>;
}

export interface AgentListResponse {
  agents: Agent[];
}

export interface CreateAgentRequest {
  agent_name: string;
  template: string;
  model?: string;
  memory_limit?: string;
  cpu_limit?: string;
  environment?: Record<string, string>;
}

export interface AgentConfig {
  environment: Record<string, string>;
  memory_limit: string;
  cpu_limit: string;
  volumes?: string[];
}

// Deployment types
export interface DeploymentStatus {
  deployment_id: string;
  status: 'pending' | 'staged' | 'in_progress' | 'rolling_back' | 'completed' | 'failed' | 'cancelled';
  phase?: 'explorers' | 'early_adopters' | 'general' | 'complete';
  agent_image?: string;
  gui_image?: string;
  nginx_image?: string;
  agents_total: number;
  agents_updated: number;
  agents_failed: number;
  agents_deferred?: number;
  created_at: string;
  started_at?: string;
  completed_at?: string;
  message?: string;
  is_rollback?: boolean;
  initiated_by?: string;
}

export interface UpdateNotification {
  agent_image: string;
  gui_image?: string;
  nginx_image?: string;
  strategy?: 'canary' | 'immediate' | 'manual';
  message?: string;
  github_run_id?: string;
  commit_sha?: string;
}

export interface PendingDeployment {
  deployment_id: string;
  agent_image: string;
  gui_image?: string;
  staged_at: string;
  message?: string;
}

export interface RollbackRequest {
  target_version: 'n-1' | 'n-2' | 'specific';
  deployment_id?: string;
  reason?: string;
}

// Telemetry types
export interface SystemSummary {
  timestamp: string;
  agents_total: number;
  agents_healthy: number;
  agents_degraded: number;
  agents_down: number;
  agents_in_work: number;
  agents_in_dream: number;
  agents_in_play: number;
  agents_in_solitude: number;
  total_cpu_percent: number;
  total_memory_mb: number;
  total_messages_24h: number;
  total_incidents_24h: number;
  active_deployments: number;
  pending_deployments: number;
}

export interface TelemetryHealth {
  status: 'healthy' | 'degraded' | 'unhealthy';
  collection_status: string;
  last_collection_time?: string;
  database_connected: boolean;
  collectors_enabled: Record<string, boolean>;
}

export interface TelemetryHistory {
  hours: number;
  interval: string;
  data: Array<{
    timestamp: string;
    total_agents: number;
    healthy_agents: number;
    messages: number;
    incidents: number;
  }>;
}

export interface PublicStatus {
  total_agents: number;
  healthy_percentage: number;
  messages_24h: number;
  incidents_24h: number;
  uptime_percentage: number;
}