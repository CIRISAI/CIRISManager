/**
 * Monitoring API for real-time telemetry data
 * 
 * Provides specialized methods for monitoring agents, containers,
 * and system health in real-time.
 */

import { AxiosInstance } from 'axios';
import {
  SystemSummary,
  ContainerMetrics,
  AgentOperationalMetrics,
  HealthStatus,
  CognitiveState,
  RequestOptions
} from '../types';

export class MonitoringAPI {
  constructor(private axios: AxiosInstance) {}
  
  /**
   * Get real-time agent status for all agents
   */
  async getAllAgentsStatus(options?: RequestOptions): Promise<AgentOperationalMetrics[]> {
    const response = await this.axios.get<{ agents: AgentOperationalMetrics[] }>(
      '/telemetry/agents/current',
      { signal: options?.signal, timeout: options?.timeout }
    );
    return response.data.agents;
  }
  
  /**
   * Get real-time container status for all containers
   */
  async getAllContainersStatus(options?: RequestOptions): Promise<ContainerMetrics[]> {
    const response = await this.axios.get<{ containers: ContainerMetrics[] }>(
      '/telemetry/containers/current',
      { signal: options?.signal, timeout: options?.timeout }
    );
    return response.data.containers;
  }
  
  /**
   * Get agents by cognitive state
   */
  async getAgentsByCognitiveState(
    state: CognitiveState,
    options?: RequestOptions
  ): Promise<AgentOperationalMetrics[]> {
    const allAgents = await this.getAllAgentsStatus(options);
    return allAgents.filter(agent => agent.cognitive_state === state);
  }
  
  /**
   * Get unhealthy agents
   */
  async getUnhealthyAgents(options?: RequestOptions): Promise<AgentOperationalMetrics[]> {
    const allAgents = await this.getAllAgentsStatus(options);
    return allAgents.filter(agent => !agent.api_healthy);
  }
  
  /**
   * Get containers by health status
   */
  async getContainersByHealth(
    health: HealthStatus,
    options?: RequestOptions
  ): Promise<ContainerMetrics[]> {
    const allContainers = await this.getAllContainersStatus(options);
    return allContainers.filter(container => container.health === health);
  }
  
  /**
   * Get high resource usage containers
   */
  async getHighResourceContainers(
    cpuThreshold: number = 80,
    memoryThreshold: number = 80,
    options?: RequestOptions
  ): Promise<ContainerMetrics[]> {
    const allContainers = await this.getAllContainersStatus(options);
    return allContainers.filter(container => 
      container.resources.cpu_percent > cpuThreshold ||
      container.resources.memory_percent > memoryThreshold
    );
  }
  
  /**
   * Get agents with recent incidents
   */
  async getAgentsWithIncidents(
    _hoursBack: number = 24,
    options?: RequestOptions
  ): Promise<AgentOperationalMetrics[]> {
    // Note: hoursBack parameter reserved for future use when API supports it
    const allAgents = await this.getAllAgentsStatus(options);
    return allAgents.filter(agent => agent.incident_count_24h > 0);
  }
  
  /**
   * Get system resource summary
   */
  async getResourceSummary(options?: RequestOptions): Promise<{
    totalCpu: number;
    totalMemoryMb: number;
    totalDiskReadMb: number;
    totalDiskWriteMb: number;
    totalNetworkRxMb: number;
    totalNetworkTxMb: number;
    containerCount: number;
  }> {
    const containers = await this.getAllContainersStatus(options);
    
    return containers.reduce((acc, container) => ({
      totalCpu: acc.totalCpu + container.resources.cpu_percent,
      totalMemoryMb: acc.totalMemoryMb + container.resources.memory_mb,
      totalDiskReadMb: acc.totalDiskReadMb + container.resources.disk_read_mb,
      totalDiskWriteMb: acc.totalDiskWriteMb + container.resources.disk_write_mb,
      totalNetworkRxMb: acc.totalNetworkRxMb + container.resources.network_rx_mb,
      totalNetworkTxMb: acc.totalNetworkTxMb + container.resources.network_tx_mb,
      containerCount: acc.containerCount + 1
    }), {
      totalCpu: 0,
      totalMemoryMb: 0,
      totalDiskReadMb: 0,
      totalDiskWriteMb: 0,
      totalNetworkRxMb: 0,
      totalNetworkTxMb: 0,
      containerCount: 0
    });
  }
  
  /**
   * Get cognitive state distribution
   */
  async getCognitiveStateDistribution(options?: RequestOptions): Promise<Record<CognitiveState, number>> {
    const summary = await this.getSystemSummary(options);
    
    return {
      [CognitiveState.WORK]: summary.agents_in_work,
      [CognitiveState.DREAM]: summary.agents_in_dream,
      [CognitiveState.SOLITUDE]: summary.agents_in_solitude,
      [CognitiveState.PLAY]: summary.agents_in_play,
      [CognitiveState.WAKEUP]: 0,
      [CognitiveState.SHUTDOWN]: 0,
      [CognitiveState.UNKNOWN]: 0
    };
  }
  
  /**
   * Get cost breakdown by agent
   */
  async getCostBreakdown(options?: RequestOptions): Promise<Array<{
    agentId: string;
    agentName: string;
    costCents24h: number;
    messageCount24h: number;
    costPerMessage: number;
  }>> {
    const agents = await this.getAllAgentsStatus(options);
    
    return agents.map(agent => ({
      agentId: agent.agent_id,
      agentName: agent.agent_name,
      costCents24h: agent.cost_cents_24h,
      messageCount24h: agent.message_count_24h,
      costPerMessage: agent.message_count_24h > 0 
        ? agent.cost_cents_24h / agent.message_count_24h 
        : 0
    })).sort((a, b) => b.costCents24h - a.costCents24h);
  }
  
  private async getSystemSummary(options?: RequestOptions): Promise<SystemSummary> {
    const response = await this.axios.get<SystemSummary>(
      '/telemetry/status',
      { signal: options?.signal, timeout: options?.timeout }
    );
    return response.data;
  }
}