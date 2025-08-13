/**
 * CIRIS Telemetry SDK
 * 
 * Complete TypeScript SDK for interacting with the CIRIS telemetry system.
 * Provides comprehensive monitoring, analytics, and alerting capabilities.
 */

// Main client
export { CIRISTelemetryClient, createTelemetryClient } from './client';

// API modules
export { MonitoringAPI } from './apis/monitoring';
export { AnalyticsAPI } from './apis/analytics';

// Re-export all types
export * from './types';

// Version
export const VERSION = '1.0.0';

/**
 * Quick start function to create a fully configured telemetry client
 */
export function quickStart(baseUrl: string, apiKey?: string) {
  const client = createTelemetryClient(baseUrl, apiKey);
  
  return {
    client,
    
    // Convenience methods
    async getHealth() {
      return client.getHealth();
    },
    
    async getStatus() {
      return client.getStatus();
    },
    
    async getPublicStatus() {
      return client.getPublicStatus();
    },
    
    async triggerCollection() {
      return client.triggerCollection();
    },
    
    // Monitoring shortcuts
    monitoring: {
      async getUnhealthyAgents() {
        const monitoringAPI = new (await import('./apis/monitoring')).MonitoringAPI(
          (client as any).axios
        );
        return monitoringAPI.getUnhealthyAgents();
      },
      
      async getHighResourceContainers(cpuThreshold = 80, memoryThreshold = 80) {
        const monitoringAPI = new (await import('./apis/monitoring')).MonitoringAPI(
          (client as any).axios
        );
        return monitoringAPI.getHighResourceContainers(cpuThreshold, memoryThreshold);
      },
      
      async getCostBreakdown() {
        const monitoringAPI = new (await import('./apis/monitoring')).MonitoringAPI(
          (client as any).axios
        );
        return monitoringAPI.getCostBreakdown();
      }
    },
    
    // Analytics shortcuts
    analytics: {
      async detectAnomalies(hours = 1) {
        const analyticsAPI = new (await import('./apis/analytics')).AnalyticsAPI(
          (client as any).axios
        );
        return analyticsAPI.detectAnomalies(hours);
      },
      
      async predictResourceUsage(hours = 24) {
        const analyticsAPI = new (await import('./apis/analytics')).AnalyticsAPI(
          (client as any).axios
        );
        return analyticsAPI.predictResourceUsage(hours);
      },
      
      async analyzeTrend(metric: string, hours = 24) {
        const analyticsAPI = new (await import('./apis/analytics')).AnalyticsAPI(
          (client as any).axios
        );
        return analyticsAPI.analyzeTrend(metric, hours);
      }
    }
  };
}

// Default export for convenience
export default CIRISTelemetryClient;