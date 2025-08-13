/**
 * Type definitions for CIRIS Telemetry SDK
 * 
 * These types match the Python schemas exactly to ensure
 * type safety across the entire telemetry system.
 */

// ============================================================================
// ENUMS - No magic strings
// ============================================================================

export enum ContainerStatus {
  RUNNING = 'running',
  STOPPED = 'stopped',
  RESTARTING = 'restarting',
  PAUSED = 'paused',
  EXITED = 'exited',
  DEAD = 'dead',
  CREATED = 'created',
  REMOVING = 'removing',
  UNKNOWN = 'unknown'
}

export enum HealthStatus {
  HEALTHY = 'healthy',
  UNHEALTHY = 'unhealthy',
  STARTING = 'starting',
  NONE = 'none',
  UNKNOWN = 'unknown'
}

export enum CognitiveState {
  WAKEUP = 'WAKEUP',
  WORK = 'WORK',
  PLAY = 'PLAY',
  SOLITUDE = 'SOLITUDE',
  DREAM = 'DREAM',
  SHUTDOWN = 'SHUTDOWN',
  UNKNOWN = 'unknown'
}

export enum DeploymentStatus {
  PENDING = 'pending',
  IN_PROGRESS = 'in_progress',
  PAUSED = 'paused',
  COMPLETED = 'completed',
  FAILED = 'failed',
  CANCELLED = 'cancelled',
  REJECTED = 'rejected',
  ROLLING_BACK = 'rolling_back',
  ROLLED_BACK = 'rolled_back',
  STAGED = 'staged'
}

export enum DeploymentPhase {
  EXPLORERS = 'explorers',
  EARLY_ADOPTERS = 'early_adopters',
  GENERAL = 'general',
  COMPLETE = 'complete'
}

export enum ComponentType {
  AGENT = 'agent',
  GUI = 'gui',
  NGINX = 'nginx',
  MANAGER = 'manager'
}

// ============================================================================
// CONTAINER METRICS - Docker infrastructure
// ============================================================================

export interface ContainerResources {
  cpu_percent: number;          // 0-10000 (can exceed 100% for multi-core)
  memory_mb: number;             // >= 0
  memory_limit_mb?: number;      // >= 0 if set
  memory_percent: number;        // 0-100
  disk_read_mb: number;          // >= 0
  disk_write_mb: number;         // >= 0
  network_rx_mb: number;         // >= 0
  network_tx_mb: number;         // >= 0
}

export interface ContainerMetrics {
  container_id: string;          // 12-64 chars
  container_name: string;        // 1-255 chars
  image: string;
  image_digest?: string;
  
  status: ContainerStatus;
  health: HealthStatus;
  restart_count: number;         // >= 0
  
  resources: ContainerResources;
  
  created_at: string;            // ISO datetime
  started_at?: string;           // ISO datetime
  finished_at?: string;          // ISO datetime
  
  exit_code?: number;
  error_message?: string;
}

// ============================================================================
// AGENT METRICS - High-level operational state
// ============================================================================

export interface AgentOperationalMetrics {
  agent_id: string;              // 1-255 chars
  agent_name: string;            // 1-255 chars
  
  // Version info for deployment tracking
  version: string;
  
  // Cognitive state for operational awareness
  cognitive_state: CognitiveState;
  
  // Health metrics
  api_healthy: boolean;
  api_response_time_ms?: number;
  uptime_seconds?: number;
  
  // Incident tracking
  incident_count_24h: number;
  last_incident_time?: string;  // ISO datetime
  
  // Usage metrics
  message_count_24h: number;
  cost_cents_24h: number;
  
  // API configuration
  api_port: number;              // 1-65535
  oauth_configured: boolean;
  oauth_providers: string[];
}

// ============================================================================
// DEPLOYMENT METRICS - CD/deployment state
// ============================================================================

export interface DeploymentMetrics {
  deployment_id: string;
  status: DeploymentStatus;
  phase: DeploymentPhase;
  
  // Target versions
  agent_image?: string;
  gui_image?: string;
  
  // Agent counts
  agents_total: number;
  agents_staged: number;
  agents_updated: number;
  agents_failed: number;
  agents_deferred: number;
  
  // Timing
  created_at: string;            // ISO datetime
  started_at?: string;
  completed_at?: string;
  
  // Additional info
  message?: string;
  error?: string;
  initiated_by?: string;
}

// ============================================================================
// VERSION TRACKING - Component versions
// ============================================================================

export interface VersionInfo {
  image: string;
  tag: string;
  digest?: string;
  deployed_at: string;           // ISO datetime
  deployment_id?: string;
}

export interface VersionState {
  component_type: ComponentType;
  current: VersionInfo;
  previous?: VersionInfo;
  rollback_available?: VersionInfo;
  last_updated: string;          // ISO datetime
}

export interface AgentVersionAdoption {
  agent_id: string;
  agent_name: string;
  current_version: string;
  pending_version?: string;
  last_updated: string;          // ISO datetime
  deployment_group: 'explorers' | 'early_adopters' | 'general';
  update_decision?: 'accepted' | 'deferred' | 'rejected';
}

// ============================================================================
// SYSTEM SUMMARY - Aggregated metrics
// ============================================================================

export interface SystemSummary {
  timestamp: string;              // ISO datetime
  
  // Agent counts
  agents_total: number;
  agents_healthy: number;
  agents_degraded: number;
  agents_down: number;
  
  // Cognitive states
  agents_in_work: number;
  agents_in_dream: number;
  agents_in_solitude: number;
  agents_in_play: number;
  
  // Resource totals
  total_cpu_percent: number;
  total_memory_mb: number;
  
  // Cost tracking
  total_cost_cents_24h: number;
  
  // Usage metrics
  total_messages_24h: number;
  total_incidents_24h: number;
  
  // Deployment status
  active_deployments: number;
  staged_deployments: number;
  agents_on_latest: number;
  agents_on_previous: number;
  agents_on_older: number;
}

// ============================================================================
// PUBLIC API - Sanitized for external consumption
// ============================================================================

export interface PublicStatus {
  timestamp: string;
  total_agents: number;
  healthy_percentage: number;
  message_volume_24h: number;
  incident_count_24h: number;
  deployment_active: boolean;
}

export interface PublicHistoryEntry {
  timestamp: string;
  total_agents: number;
  healthy_agents: number;
  total_messages: number;
  total_incidents: number;
}

// ============================================================================
// TELEMETRY QUERIES - Complex data retrieval
// ============================================================================

export interface TelemetryQuery {
  query_type: 'realtime' | 'aggregate' | 'timeseries' | 'distribution';
  metric_name: string;
  filters?: Record<string, any>;
  aggregation?: 'sum' | 'avg' | 'min' | 'max' | 'count';
  group_by?: string[];
  time_range?: {
    start: string;
    end: string;
  };
  interval?: string;
  limit?: number;
}

export interface TelemetryResponse {
  query: TelemetryQuery;
  data: any[];
  metadata: {
    count: number;
    execution_time_ms: number;
    cache_hit: boolean;
  };
}

// ============================================================================
// TELEMETRY SNAPSHOT - Complete system state
// ============================================================================

export interface TelemetrySnapshot {
  snapshot_id: string;
  timestamp: string;
  
  containers: ContainerMetrics[];
  agents: AgentOperationalMetrics[];
  deployments: DeploymentMetrics[];
  versions: VersionState[];
  adoption: AgentVersionAdoption[];
  
  collection_duration_ms: number;
  errors: string[];
}

// ============================================================================
// API RESPONSES
// ============================================================================

export interface HealthResponse {
  status: 'healthy' | 'degraded' | 'down';
  collection_status: 'active' | 'stopped';
  last_collection_time?: string;
  database_connected: boolean;
  collectors_enabled: {
    docker: boolean;
    agents: boolean;
    deployments: boolean;
    versions: boolean;
  };
  collection_interval: number;
  storage_enabled: boolean;
}

export interface HistoryResponse {
  hours: number;
  interval: string;
  data: any[];
}

export interface TriggerResponse {
  status: 'success' | 'error';
  message: string;
  collection_id?: string;
  duration_ms?: number;
}

export interface AgentMetricsResponse {
  agent_name: string;
  hours?: number;
  current?: AgentOperationalMetrics;
  history?: Array<{
    timestamp: string;
    metrics: Partial<AgentOperationalMetrics>;
  }>;
  resource_usage?: {
    cpu: number[];
    memory: number[];
    timestamps: string[];
  };
}

export interface ContainerMetricsResponse {
  container_name: string;
  hours?: number;
  current?: ContainerMetrics;
  history?: Array<{
    timestamp: string;
    metrics: Partial<ContainerMetrics>;
  }>;
  resource_usage?: {
    cpu: number[];
    memory: number[];
    network_rx: number[];
    network_tx: number[];
    timestamps: string[];
  };
}

export interface CleanupResponse {
  status: 'success' | 'error';
  message: string;
  deleted_records?: number;
  freed_space_mb?: number;
}

// ============================================================================
// COLLECTOR STATS - For monitoring the telemetry system itself
// ============================================================================

export interface CollectorStats {
  name: string;
  available: boolean;
  collections: number;
  errors: number;
  error_rate: number;
  last_collection?: string;
  last_error?: string;
  average_duration_ms?: number;
}

export interface OrchestratorStats {
  is_running: boolean;
  collections_total: number;
  errors_total: number;
  last_collection_time?: string;
  last_error?: string;
  collectors: Record<string, CollectorStats>;
}

// ============================================================================
// ERROR TYPES
// ============================================================================

export class TelemetryError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public details?: any
  ) {
    super(message);
    this.name = 'TelemetryError';
  }
}

export class CollectionError extends TelemetryError {
  constructor(message: string, details?: any) {
    super(message, 503, details);
    this.name = 'CollectionError';
  }
}

export class StorageError extends TelemetryError {
  constructor(message: string, details?: any) {
    super(message, 500, details);
    this.name = 'StorageError';
  }
}

// ============================================================================
// REQUEST OPTIONS
// ============================================================================

export interface TelemetryClientOptions {
  baseUrl: string;
  apiKey?: string;
  timeout?: number;
  retryAttempts?: number;
  retryDelay?: number;
  enableCache?: boolean;
  cacheTimeout?: number;
}

export interface RequestOptions {
  signal?: AbortSignal;
  headers?: Record<string, string>;
  timeout?: number;
}

// ============================================================================
// WEBSOCKET TYPES - For real-time telemetry
// ============================================================================

export interface TelemetryWebSocketMessage {
  type: 'snapshot' | 'delta' | 'alert' | 'status';
  timestamp: string;
  data: any;
}

export interface TelemetrySubscription {
  id: string;
  metrics: string[];
  interval: number;
  filters?: Record<string, any>;
}