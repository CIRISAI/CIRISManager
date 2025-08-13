/**
 * CIRIS Telemetry SDK Client
 * 
 * Comprehensive client for interacting with the CIRIS telemetry system.
 * Provides type-safe access to all telemetry endpoints.
 */

import axios, { AxiosInstance, AxiosError } from 'axios';
import {
  // Response types
  HealthResponse,
  SystemSummary,
  HistoryResponse,
  TriggerResponse,
  AgentMetricsResponse,
  ContainerMetricsResponse,
  CleanupResponse,
  PublicStatus,
  PublicHistoryEntry,
  TelemetryResponse,
  TelemetrySnapshot,
  OrchestratorStats,
  
  // Query types
  TelemetryQuery,
  
  // Error types
  TelemetryError,
  CollectionError,
  StorageError,
  
  // Options
  TelemetryClientOptions,
  RequestOptions,
  
  // WebSocket types
  TelemetryWebSocketMessage,
  TelemetrySubscription
} from './types';

/**
 * Main telemetry client class
 */
export class CIRISTelemetryClient {
  private axios: AxiosInstance;
  private wsConnection?: WebSocket;
  private wsSubscriptions: Map<string, TelemetrySubscription> = new Map();
  private wsReconnectAttempts = 0;
  private wsMaxReconnectAttempts = 5;
  private wsReconnectDelay = 1000;
  private cache: Map<string, { data: any; expiry: number }> = new Map();
  
  constructor(private options: TelemetryClientOptions) {
    this.axios = axios.create({
      baseURL: options.baseUrl,
      timeout: options.timeout || 30000,
      headers: {
        'Content-Type': 'application/json',
        ...(options.apiKey && { 'Authorization': `Bearer ${options.apiKey}` })
      }
    });
    
    // Add request interceptor for retry logic
    this.axios.interceptors.response.use(
      response => response,
      this.handleAxiosError.bind(this)
    );
    
    // Start cache cleanup interval if enabled
    if (options.enableCache) {
      setInterval(() => this.cleanupCache(), 60000); // Clean every minute
    }
  }
  
  // ============================================================================
  // HEALTH & STATUS
  // ============================================================================
  
  /**
   * Get telemetry system health status
   */
  async getHealth(options?: RequestOptions): Promise<HealthResponse> {
    const response = await this.request<HealthResponse>(
      'GET',
      '/telemetry/health',
      undefined,
      options
    );
    return response;
  }
  
  /**
   * Get current system status summary
   */
  async getStatus(options?: RequestOptions): Promise<SystemSummary> {
    const cacheKey = 'status';
    const cached = this.getCached(cacheKey);
    if (cached) return cached;
    
    const response = await this.request<SystemSummary>(
      'GET',
      '/telemetry/status',
      undefined,
      options
    );
    
    this.setCache(cacheKey, response, 5000); // Cache for 5 seconds
    return response;
  }
  
  /**
   * Get orchestrator statistics
   */
  async getOrchestratorStats(options?: RequestOptions): Promise<OrchestratorStats> {
    const response = await this.request<OrchestratorStats>(
      'GET',
      '/telemetry/orchestrator/stats',
      undefined,
      options
    );
    return response;
  }
  
  // ============================================================================
  // HISTORICAL DATA
  // ============================================================================
  
  /**
   * Get historical telemetry data
   */
  async getHistory(
    hours: number = 24,
    interval: '1m' | '5m' | '1h' | '1d' = '5m',
    options?: RequestOptions
  ): Promise<HistoryResponse> {
    const params = { hours, interval };
    const cacheKey = `history_${hours}_${interval}`;
    const cached = this.getCached(cacheKey);
    if (cached) return cached;
    
    const response = await this.request<HistoryResponse>(
      'GET',
      '/telemetry/history',
      { params },
      options
    );
    
    this.setCache(cacheKey, response, 60000); // Cache for 1 minute
    return response;
  }
  
  /**
   * Get agent-specific metrics
   */
  async getAgentMetrics(
    agentName: string,
    hours?: number,
    options?: RequestOptions
  ): Promise<AgentMetricsResponse> {
    const params = hours ? { hours } : undefined;
    const response = await this.request<AgentMetricsResponse>(
      'GET',
      `/telemetry/agent/${agentName}`,
      { params },
      options
    );
    return response;
  }
  
  /**
   * Get container-specific metrics
   */
  async getContainerMetrics(
    containerName: string,
    hours?: number,
    options?: RequestOptions
  ): Promise<ContainerMetricsResponse> {
    const params = hours ? { hours } : undefined;
    const response = await this.request<ContainerMetricsResponse>(
      'GET',
      `/telemetry/container/${containerName}`,
      { params },
      options
    );
    return response;
  }
  
  // ============================================================================
  // PUBLIC API
  // ============================================================================
  
  /**
   * Get public status (sanitized data)
   */
  async getPublicStatus(options?: RequestOptions): Promise<PublicStatus> {
    const cacheKey = 'public_status';
    const cached = this.getCached(cacheKey);
    if (cached) return cached;
    
    const response = await this.request<PublicStatus>(
      'GET',
      '/telemetry/public/status',
      undefined,
      options
    );
    
    this.setCache(cacheKey, response, 30000); // Cache for 30 seconds
    return response;
  }
  
  /**
   * Get public history (sanitized data)
   */
  async getPublicHistory(
    hours: number = 24,
    interval: number = 5,
    options?: RequestOptions
  ): Promise<PublicHistoryEntry[]> {
    const params = { hours, interval };
    const cacheKey = `public_history_${hours}_${interval}`;
    const cached = this.getCached(cacheKey);
    if (cached) return cached;
    
    const response = await this.request<PublicHistoryEntry[]>(
      'GET',
      '/telemetry/public/history',
      { params },
      options
    );
    
    this.setCache(cacheKey, response, 60000); // Cache for 1 minute
    return response;
  }
  
  // ============================================================================
  // QUERIES
  // ============================================================================
  
  /**
   * Execute a complex telemetry query
   */
  async query(
    query: TelemetryQuery,
    options?: RequestOptions
  ): Promise<TelemetryResponse> {
    const response = await this.request<TelemetryResponse>(
      'POST',
      '/telemetry/query',
      { data: query },
      options
    );
    return response;
  }
  
  /**
   * Get a complete telemetry snapshot
   */
  async getSnapshot(options?: RequestOptions): Promise<TelemetrySnapshot> {
    const response = await this.request<TelemetrySnapshot>(
      'GET',
      '/telemetry/snapshot',
      undefined,
      options
    );
    return response;
  }
  
  // ============================================================================
  // MANAGEMENT
  // ============================================================================
  
  /**
   * Trigger immediate telemetry collection
   */
  async triggerCollection(options?: RequestOptions): Promise<TriggerResponse> {
    const response = await this.request<TriggerResponse>(
      'POST',
      '/telemetry/collect',
      undefined,
      options
    );
    
    // Clear cache after triggering collection
    this.clearCache();
    
    return response;
  }
  
  /**
   * Clean up old telemetry data
   */
  async cleanupOldData(
    daysToKeep: number = 30,
    options?: RequestOptions
  ): Promise<CleanupResponse> {
    const response = await this.request<CleanupResponse>(
      'POST',
      '/telemetry/cleanup',
      { data: { days_to_keep: daysToKeep } },
      options
    );
    return response;
  }
  
  // ============================================================================
  // WEBSOCKET SUPPORT
  // ============================================================================
  
  /**
   * Connect to telemetry WebSocket for real-time updates
   */
  connectWebSocket(
    onMessage: (message: TelemetryWebSocketMessage) => void,
    onError?: (error: Error) => void
  ): void {
    if (this.wsConnection?.readyState === WebSocket.OPEN) {
      return;
    }
    
    const wsUrl = this.options.baseUrl.replace(/^http/, 'ws') + '/telemetry/ws';
    
    try {
      this.wsConnection = new WebSocket(wsUrl);
      
      this.wsConnection.onopen = () => {
        console.log('Telemetry WebSocket connected');
        this.wsReconnectAttempts = 0;
        
        // Re-subscribe to all active subscriptions
        this.wsSubscriptions.forEach(sub => {
          this.wsConnection?.send(JSON.stringify({
            type: 'subscribe',
            subscription: sub
          }));
        });
      };
      
      this.wsConnection.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as TelemetryWebSocketMessage;
          onMessage(message);
        } catch (error) {
          console.error('Failed to parse WebSocket message:', error);
        }
      };
      
      this.wsConnection.onerror = (event) => {
        console.error('Telemetry WebSocket error:', event);
        onError?.(new Error('WebSocket error'));
      };
      
      this.wsConnection.onclose = () => {
        console.log('Telemetry WebSocket disconnected');
        this.handleWebSocketReconnect(onMessage, onError);
      };
    } catch (error) {
      console.error('Failed to connect WebSocket:', error);
      onError?.(error as Error);
    }
  }
  
  /**
   * Subscribe to specific metrics via WebSocket
   */
  subscribe(subscription: TelemetrySubscription): void {
    if (!this.wsConnection || this.wsConnection.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected');
    }
    
    this.wsSubscriptions.set(subscription.id, subscription);
    
    this.wsConnection.send(JSON.stringify({
      type: 'subscribe',
      subscription
    }));
  }
  
  /**
   * Unsubscribe from metrics
   */
  unsubscribe(subscriptionId: string): void {
    if (!this.wsConnection || this.wsConnection.readyState !== WebSocket.OPEN) {
      return;
    }
    
    this.wsSubscriptions.delete(subscriptionId);
    
    this.wsConnection.send(JSON.stringify({
      type: 'unsubscribe',
      subscriptionId
    }));
  }
  
  /**
   * Disconnect WebSocket
   */
  disconnectWebSocket(): void {
    if (this.wsConnection) {
      this.wsConnection.close();
      this.wsConnection = undefined;
      this.wsSubscriptions.clear();
    }
  }
  
  // ============================================================================
  // UTILITY METHODS
  // ============================================================================
  
  /**
   * Clear all cached data
   */
  clearCache(): void {
    this.cache.clear();
  }
  
  /**
   * Set base URL (useful for switching environments)
   */
  setBaseUrl(url: string): void {
    this.options.baseUrl = url;
    this.axios.defaults.baseURL = url;
  }
  
  /**
   * Set API key
   */
  setApiKey(apiKey: string): void {
    this.options.apiKey = apiKey;
    this.axios.defaults.headers['Authorization'] = `Bearer ${apiKey}`;
  }
  
  // ============================================================================
  // PRIVATE METHODS
  // ============================================================================
  
  private async request<T>(
    method: string,
    url: string,
    config?: any,
    options?: RequestOptions
  ): Promise<T> {
    try {
      const response = await this.axios.request<T>({
        method,
        url,
        ...config,
        ...(options && {
          signal: options.signal,
          timeout: options.timeout || this.options.timeout,
          headers: { ...config?.headers, ...options.headers }
        })
      });
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }
  
  private handleAxiosError(error: AxiosError): Promise<never> {
    if (error.response?.status === 503) {
      throw new CollectionError(
        'Telemetry service unavailable',
        error.response.data
      );
    }
    
    if (error.response?.status === 500) {
      throw new StorageError(
        'Telemetry storage error',
        error.response.data
      );
    }
    
    throw error;
  }
  
  private handleError(error: any): Error {
    if (axios.isAxiosError(error)) {
      const message = error.response?.data?.detail || error.message;
      return new TelemetryError(
        message,
        error.response?.status,
        error.response?.data
      );
    }
    return error;
  }
  
  private getCached(key: string): any {
    if (!this.options.enableCache) return null;
    
    const cached = this.cache.get(key);
    if (cached && cached.expiry > Date.now()) {
      return cached.data;
    }
    
    this.cache.delete(key);
    return null;
  }
  
  private setCache(key: string, data: any, timeout?: number): void {
    if (!this.options.enableCache) return;
    
    const expiry = Date.now() + (timeout || this.options.cacheTimeout || 60000);
    this.cache.set(key, { data, expiry });
  }
  
  private cleanupCache(): void {
    const now = Date.now();
    for (const [key, value] of this.cache.entries()) {
      if (value.expiry <= now) {
        this.cache.delete(key);
      }
    }
  }
  
  private handleWebSocketReconnect(
    onMessage: (message: TelemetryWebSocketMessage) => void,
    onError?: (error: Error) => void
  ): void {
    if (this.wsReconnectAttempts >= this.wsMaxReconnectAttempts) {
      console.error('Max WebSocket reconnection attempts reached');
      onError?.(new Error('Max reconnection attempts reached'));
      return;
    }
    
    this.wsReconnectAttempts++;
    const delay = this.wsReconnectDelay * Math.pow(2, this.wsReconnectAttempts - 1);
    
    console.log(`Attempting WebSocket reconnection in ${delay}ms...`);
    
    setTimeout(() => {
      this.connectWebSocket(onMessage, onError);
    }, delay);
  }
}

// ============================================================================
// CONVENIENCE EXPORTS
// ============================================================================

export * from './types';

/**
 * Create a new telemetry client with default options
 */
export function createTelemetryClient(
  baseUrl: string,
  apiKey?: string
): CIRISTelemetryClient {
  return new CIRISTelemetryClient({
    baseUrl,
    apiKey,
    timeout: 30000,
    retryAttempts: 3,
    retryDelay: 1000,
    enableCache: true,
    cacheTimeout: 60000
  });
}