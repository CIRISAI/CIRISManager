import { AxiosInstance } from 'axios';
import { 
  SystemSummary,
  TelemetryHealth,
  TelemetryHistory,
  PublicStatus 
} from '../types';

export interface HistoryOptions {
  hours?: number;
  interval?: '1m' | '5m' | '1h' | '1d';
}

/**
 * API for accessing telemetry data
 */
export class TelemetryAPI {
  constructor(private axios: AxiosInstance) {}

  /**
   * Get telemetry system health
   */
  async health(): Promise<TelemetryHealth> {
    const response = await this.axios.get('/telemetry/health');
    return response.data;
  }

  /**
   * Get current system telemetry
   */
  async getStatus(): Promise<SystemSummary> {
    const response = await this.axios.get('/telemetry/status');
    return response.data;
  }

  /**
   * Get historical telemetry data
   */
  async getHistory(options: HistoryOptions = {}): Promise<TelemetryHistory> {
    const response = await this.axios.get('/telemetry/history', {
      params: {
        hours: options.hours || 24,
        interval: options.interval || '5m'
      }
    });
    return response.data;
  }

  /**
   * Get public status (safe for external display)
   */
  async getPublicStatus(): Promise<PublicStatus> {
    const response = await this.axios.get('/telemetry/public/status');
    return response.data;
  }

  /**
   * Get public history
   */
  async getPublicHistory(hours = 24): Promise<any[]> {
    const response = await this.axios.get('/telemetry/public/history', {
      params: { hours }
    });
    return response.data;
  }

  /**
   * Get agent-specific metrics
   */
  async getAgentMetrics(agentName: string, hours = 24): Promise<any> {
    const response = await this.axios.get(`/telemetry/agent/${agentName}`, {
      params: { hours }
    });
    return response.data;
  }

  /**
   * Get container-specific metrics
   */
  async getContainerMetrics(containerName: string, hours = 24): Promise<any> {
    const response = await this.axios.get(`/telemetry/container/${containerName}`, {
      params: { hours }
    });
    return response.data;
  }

  /**
   * Trigger manual telemetry collection
   */
  async collect(): Promise<{ status: string; message: string }> {
    const response = await this.axios.post('/telemetry/collect');
    return response.data;
  }

  /**
   * Stream real-time telemetry updates
   */
  streamMetrics(onUpdate: (metrics: SystemSummary) => void, intervalMs = 5000): () => void {
    let intervalId: NodeJS.Timeout | null = null;
    
    const startStreaming = async () => {
      // Initial fetch
      try {
        const status = await this.getStatus();
        onUpdate(status);
      } catch (error) {
        console.error('Failed to fetch initial telemetry:', error);
      }

      // Set up polling
      intervalId = setInterval(async () => {
        try {
          const status = await this.getStatus();
          onUpdate(status);
        } catch (error) {
          console.error('Failed to fetch telemetry:', error);
        }
      }, intervalMs);
    };

    startStreaming();

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }
}