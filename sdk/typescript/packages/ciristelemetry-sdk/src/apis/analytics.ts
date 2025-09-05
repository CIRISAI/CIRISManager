/**
 * Analytics API for telemetry data analysis
 *
 * Provides methods for analyzing trends, patterns, and anomalies
 * in telemetry data.
 */

import { AxiosInstance } from 'axios';
import {
  TelemetryQuery,
  TelemetryResponse,
  RequestOptions
} from '../types';

export interface TrendAnalysis {
  metric: string;
  trend: 'increasing' | 'decreasing' | 'stable';
  changePercent: number;
  currentValue: number;
  previousValue: number;
  timeRange: string;
}

export interface AnomalyDetection {
  metric: string;
  value: number;
  expectedRange: { min: number; max: number };
  severity: 'low' | 'medium' | 'high';
  timestamp: string;
  entity: string;
}

export interface PerformanceBaseline {
  metric: string;
  mean: number;
  median: number;
  stdDev: number;
  p95: number;
  p99: number;
  samples: number;
}

export class AnalyticsAPI {
  constructor(private axios: AxiosInstance) {}

  /**
   * Analyze trends for a specific metric
   */
  async analyzeTrend(
    metric: string,
    hours: number = 24,
    options?: RequestOptions
  ): Promise<TrendAnalysis> {
    const query: TelemetryQuery = {
      query_type: 'timeseries',
      metric_name: metric,
      time_range: {
        start: new Date(Date.now() - hours * 3600000).toISOString(),
        end: new Date().toISOString()
      },
      interval: hours <= 24 ? '1h' : '1d'
    };

    const response = await this.executeQuery(query, options);
    const data = response.data;

    if (data.length < 2) {
      return {
        metric,
        trend: 'stable',
        changePercent: 0,
        currentValue: data[0]?.value || 0,
        previousValue: data[0]?.value || 0,
        timeRange: `${hours}h`
      };
    }

    const current = data[data.length - 1].value;
    const previous = data[0].value;
    const changePercent = ((current - previous) / previous) * 100;

    return {
      metric,
      trend: changePercent > 5 ? 'increasing' : changePercent < -5 ? 'decreasing' : 'stable',
      changePercent,
      currentValue: current,
      previousValue: previous,
      timeRange: `${hours}h`
    };
  }

  /**
   * Detect anomalies in telemetry data
   */
  async detectAnomalies(
    hours: number = 1,
    options?: RequestOptions
  ): Promise<AnomalyDetection[]> {
    const anomalies: AnomalyDetection[] = [];

    // Check CPU anomalies
    const cpuQuery: TelemetryQuery = {
      query_type: 'distribution',
      metric_name: 'cpu_percent',
      time_range: {
        start: new Date(Date.now() - hours * 3600000).toISOString(),
        end: new Date().toISOString()
      }
    };

    const cpuResponse = await this.executeQuery(cpuQuery, options);
    const cpuData = cpuResponse.data;

    // Calculate statistics
    const cpuValues = cpuData.map(d => d.value);
    const mean = cpuValues.reduce((a, b) => a + b, 0) / cpuValues.length;
    const stdDev = Math.sqrt(
      cpuValues.reduce((sq, n) => sq + Math.pow(n - mean, 2), 0) / cpuValues.length
    );

    // Detect outliers (values beyond 3 standard deviations)
    cpuData.forEach(item => {
      if (Math.abs(item.value - mean) > 3 * stdDev) {
        anomalies.push({
          metric: 'cpu_percent',
          value: item.value,
          expectedRange: {
            min: Math.max(0, mean - 2 * stdDev),
            max: mean + 2 * stdDev
          },
          severity: Math.abs(item.value - mean) > 4 * stdDev ? 'high' : 'medium',
          timestamp: item.timestamp,
          entity: item.entity || 'unknown'
        });
      }
    });

    // Check memory anomalies
    const memoryQuery: TelemetryQuery = {
      query_type: 'distribution',
      metric_name: 'memory_percent',
      time_range: {
        start: new Date(Date.now() - hours * 3600000).toISOString(),
        end: new Date().toISOString()
      }
    };

    const memoryResponse = await this.executeQuery(memoryQuery, options);
    const memoryData = memoryResponse.data;

    // Detect high memory usage (>90%)
    memoryData.forEach(item => {
      if (item.value > 90) {
        anomalies.push({
          metric: 'memory_percent',
          value: item.value,
          expectedRange: { min: 0, max: 90 },
          severity: item.value > 95 ? 'high' : 'medium',
          timestamp: item.timestamp,
          entity: item.entity || 'unknown'
        });
      }
    });

    return anomalies;
  }

  /**
   * Calculate performance baselines
   */
  async calculateBaselines(
    metrics: string[],
    days: number = 7,
    options?: RequestOptions
  ): Promise<PerformanceBaseline[]> {
    const baselines: PerformanceBaseline[] = [];

    for (const metric of metrics) {
      const query: TelemetryQuery = {
        query_type: 'aggregate',
        metric_name: metric,
        time_range: {
          start: new Date(Date.now() - days * 86400000).toISOString(),
          end: new Date().toISOString()
        },
        aggregation: 'avg'
      };

      const response = await this.executeQuery(query, options);
      const values = response.data.map(d => d.value).sort((a, b) => a - b);

      if (values.length === 0) continue;

      const mean = values.reduce((a, b) => a + b, 0) / values.length;
      const median = values[Math.floor(values.length / 2)];
      const stdDev = Math.sqrt(
        values.reduce((sq, n) => sq + Math.pow(n - mean, 2), 0) / values.length
      );
      const p95 = values[Math.floor(values.length * 0.95)];
      const p99 = values[Math.floor(values.length * 0.99)];

      baselines.push({
        metric,
        mean,
        median,
        stdDev,
        p95,
        p99,
        samples: values.length
      });
    }

    return baselines;
  }

  /**
   * Analyze agent performance over time
   */
  async analyzeAgentPerformance(
    agentName: string,
    days: number = 7,
    options?: RequestOptions
  ): Promise<{
    availability: number;
    averageResponseTime: number;
    totalMessages: number;
    totalCost: number;
    incidentRate: number;
    trends: TrendAnalysis[];
  }> {
    const hours = days * 24;

    // Get agent metrics
    const response = await this.axios.get<{ history: any[] }>(
      `/telemetry/agent/${agentName}`,
      {
        params: { hours },
        signal: options?.signal,
        timeout: options?.timeout
      }
    );

    const history = response.data.history;

    // Calculate metrics
    const totalSamples = history.length;
    const healthySamples = history.filter(h => h.api_healthy).length;
    const availability = (healthySamples / totalSamples) * 100;

    const responseTimes = history.map(h => h.api_response_time_ms || 0);
    const averageResponseTime = responseTimes.reduce((a, b) => a + b, 0) / responseTimes.length;

    const totalMessages = history.reduce((sum, h) => sum + (h.message_count_24h || 0), 0);
    const totalCost = history.reduce((sum, h) => sum + (h.cost_cents_24h || 0), 0);
    const totalIncidents = history.reduce((sum, h) => sum + (h.incident_count_24h || 0), 0);
    const incidentRate = totalMessages > 0 ? (totalIncidents / totalMessages) * 100 : 0;

    // Analyze trends
    const trends: TrendAnalysis[] = [];

    // Response time trend
    const responseTimeTrend = await this.analyzeTrend(
      `agent.${agentName}.response_time`,
      hours,
      options
    );
    trends.push(responseTimeTrend);

    // Message volume trend
    const messageTrend = await this.analyzeTrend(
      `agent.${agentName}.messages`,
      hours,
      options
    );
    trends.push(messageTrend);

    // Cost trend
    const costTrend = await this.analyzeTrend(
      `agent.${agentName}.cost`,
      hours,
      options
    );
    trends.push(costTrend);

    return {
      availability,
      averageResponseTime,
      totalMessages,
      totalCost,
      incidentRate,
      trends
    };
  }

  /**
   * Compare agent performance
   */
  async compareAgents(
    agentNames: string[],
    metric: string,
    hours: number = 24,
    options?: RequestOptions
  ): Promise<Array<{
    agentName: string;
    value: number;
    rank: number;
    percentile: number;
  }>> {
    const results: Array<{ agentName: string; value: number }> = [];

    for (const agentName of agentNames) {
      const query: TelemetryQuery = {
        query_type: 'aggregate',
        metric_name: `agent.${agentName}.${metric}`,
        time_range: {
          start: new Date(Date.now() - hours * 3600000).toISOString(),
          end: new Date().toISOString()
        },
        aggregation: 'avg'
      };

      const response = await this.executeQuery(query, options);
      const value = response.data[0]?.value || 0;

      results.push({ agentName, value });
    }

    // Sort and rank
    results.sort((a, b) => b.value - a.value);

    return results.map((result, index) => ({
      ...result,
      rank: index + 1,
      percentile: ((results.length - index) / results.length) * 100
    }));
  }

  /**
   * Predict resource usage
   */
  async predictResourceUsage(
    hours: number = 24,
    options?: RequestOptions
  ): Promise<{
    predictedCpu: number;
    predictedMemory: number;
    confidence: number;
    recommendation: string;
  }> {
    // Get historical data
    const cpuTrend = await this.analyzeTrend('total_cpu_percent', hours * 2, options);
    const memoryTrend = await this.analyzeTrend('total_memory_mb', hours * 2, options);

    // Simple linear prediction
    const cpuGrowthRate = cpuTrend.changePercent / 100;
    const memoryGrowthRate = memoryTrend.changePercent / 100;

    const predictedCpu = cpuTrend.currentValue * (1 + cpuGrowthRate);
    const predictedMemory = memoryTrend.currentValue * (1 + memoryGrowthRate);

    // Confidence based on trend stability
    const confidence =
      cpuTrend.trend === 'stable' && memoryTrend.trend === 'stable' ? 0.9 :
      cpuTrend.trend === memoryTrend.trend ? 0.7 : 0.5;

    // Generate recommendation
    let recommendation = '';
    if (predictedCpu > 80) {
      recommendation = 'Consider scaling up CPU resources';
    } else if (predictedMemory > 0.8 * 16384) { // Assuming 16GB limit
      recommendation = 'Consider scaling up memory resources';
    } else if (predictedCpu < 20 && predictedMemory < 0.2 * 16384) {
      recommendation = 'Resources are underutilized, consider scaling down';
    } else {
      recommendation = 'Resource usage is within normal parameters';
    }

    return {
      predictedCpu,
      predictedMemory,
      confidence,
      recommendation
    };
  }

  private async executeQuery(
    query: TelemetryQuery,
    options?: RequestOptions
  ): Promise<TelemetryResponse> {
    const response = await this.axios.post<TelemetryResponse>(
      '/telemetry/query',
      query,
      { signal: options?.signal, timeout: options?.timeout }
    );
    return response.data;
  }
}
