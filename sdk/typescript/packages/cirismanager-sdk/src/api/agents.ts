import { AxiosInstance } from 'axios';
import { 
  Agent, 
  AgentConfig, 
  CreateAgentRequest,
  AgentListResponse 
} from '../types';

/**
 * API for managing CIRIS agents
 */
export class AgentsAPI {
  constructor(private axios: AxiosInstance) {}

  /**
   * List all agents
   */
  async list(): Promise<AgentListResponse> {
    const response = await this.axios.get('/agents');
    return response.data;
  }

  /**
   * Get agent details
   */
  async get(agentId: string): Promise<Agent> {
    const response = await this.axios.get(`/agents/${agentId}`);
    return response.data;
  }

  /**
   * Create new agent
   */
  async create(request: CreateAgentRequest): Promise<Agent> {
    const response = await this.axios.post('/agents', request);
    return response.data;
  }

  /**
   * Delete agent
   */
  async delete(agentId: string): Promise<void> {
    await this.axios.delete(`/agents/${agentId}`);
  }

  /**
   * Start agent
   */
  async start(agentId: string): Promise<{ message: string }> {
    const response = await this.axios.post(`/agents/${agentId}/start`);
    return response.data;
  }

  /**
   * Stop agent
   */
  async stop(agentId: string): Promise<{ message: string }> {
    const response = await this.axios.post(`/agents/${agentId}/stop`);
    return response.data;
  }

  /**
   * Restart agent
   */
  async restart(agentId: string): Promise<{ message: string }> {
    const response = await this.axios.post(`/agents/${agentId}/restart`);
    return response.data;
  }

  /**
   * Request graceful shutdown
   */
  async shutdown(agentId: string, force = false): Promise<{ message: string }> {
    const response = await this.axios.post(`/agents/${agentId}/shutdown`, { force });
    return response.data;
  }

  /**
   * Get agent configuration
   */
  async getConfig(agentId: string): Promise<AgentConfig> {
    const response = await this.axios.get(`/agents/${agentId}/config`);
    return response.data;
  }

  /**
   * Update agent configuration
   */
  async updateConfig(agentId: string, config: Partial<AgentConfig>): Promise<{ message: string }> {
    const response = await this.axios.patch(`/agents/${agentId}/config`, config);
    return response.data;
  }

  /**
   * Get agent versions
   */
  async getVersions(): Promise<Record<string, any>> {
    const response = await this.axios.get('/agents/versions');
    return response.data;
  }

  /**
   * Watch agent status with WebSocket
   */
  watchStatus(agentId: string, onUpdate: (status: any) => void): () => void {
    // WebSocket implementation would go here
    // For now, return a no-op cleanup function
    return () => {};
  }
}