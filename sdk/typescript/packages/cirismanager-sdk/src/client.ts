import axios, { AxiosInstance, AxiosRequestConfig } from 'axios';
import { AgentsAPI } from './api/agents';
import { DeploymentsAPI } from './api/deployments';
import { TelemetryAPI } from './api/telemetry';
import { CIRISError, NetworkError, AuthenticationError } from './errors';

export interface ClientConfig {
  baseURL?: string;
  token?: string;
  timeout?: number;
  retries?: number;
  onAuthFailure?: () => void;
}

/**
 * Main client for interacting with CIRIS Manager API
 */
export class CIRISManagerClient {
  private axios: AxiosInstance;
  public agents: AgentsAPI;
  public deployments: DeploymentsAPI;
  public telemetry: TelemetryAPI;

  constructor(config: ClientConfig = {}) {
    const baseURL = config.baseURL || '/manager/v1';

    this.axios = axios.create({
      baseURL,
      timeout: config.timeout || 30000,
      headers: {
        'Content-Type': 'application/json',
        ...(config.token ? { 'Authorization': `Bearer ${config.token}` } : {})
      }
    });

    // Add response interceptor for error handling
    this.axios.interceptors.response.use(
      response => response,
      async error => {
        if (error.response?.status === 401) {
          config.onAuthFailure?.();
          throw new AuthenticationError('Authentication failed');
        }

        if (error.code === 'ECONNABORTED' || !error.response) {
          throw new NetworkError('Network request failed');
        }

        throw new CIRISError(
          error.response?.data?.detail || error.message,
          error.response?.status
        );
      }
    );

    // Add retry logic
    if (config.retries) {
      this.setupRetry(config.retries);
    }

    // Initialize API modules
    this.agents = new AgentsAPI(this.axios);
    this.deployments = new DeploymentsAPI(this.axios);
    this.telemetry = new TelemetryAPI(this.axios);
  }

  private setupRetry(maxRetries: number) {
    this.axios.interceptors.response.use(undefined, async (error) => {
      const config = error.config;

      if (!config || !config.retry) {
        config.retry = { count: 0 };
      }

      config.retry.count++;

      if (config.retry.count > maxRetries) {
        return Promise.reject(error);
      }

      // Exponential backoff
      const delayMs = Math.min(1000 * Math.pow(2, config.retry.count), 10000);
      await new Promise(resolve => setTimeout(resolve, delayMs));

      return this.axios(config);
    });
  }

  /**
   * Update authentication token
   */
  setToken(token: string) {
    this.axios.defaults.headers.common['Authorization'] = `Bearer ${token}`;
  }

  /**
   * Health check
   */
  async health(): Promise<{ status: string }> {
    const response = await this.axios.get('/health');
    return response.data;
  }

  /**
   * Get system status
   */
  async status(): Promise<any> {
    const response = await this.axios.get('/status');
    return response.data;
  }
}
