import { AxiosInstance } from 'axios';
import {
  DeploymentStatus,
  UpdateNotification,
  PendingDeployment,
  RollbackRequest
} from '../types';

/**
 * API for managing deployments and updates
 */
export class DeploymentsAPI {
  constructor(private axios: AxiosInstance) {}

  /**
   * Get current deployment status
   */
  async getStatus(): Promise<DeploymentStatus | null> {
    try {
      const response = await this.axios.get('/updates/status');
      return response.data;
    } catch (error: any) {
      if (error.response?.status === 404) {
        return null;
      }
      throw error;
    }
  }

  /**
   * Get pending deployments awaiting approval
   */
  async getPending(): Promise<PendingDeployment[]> {
    const response = await this.axios.get('/updates/pending');
    return response.data;
  }

  /**
   * Launch a staged deployment
   */
  async launch(deploymentId: string, force = false): Promise<DeploymentStatus> {
    const response = await this.axios.post('/updates/launch', {
      deployment_id: deploymentId,
      force
    });
    return response.data;
  }

  /**
   * Reject a pending deployment
   */
  async reject(deploymentId: string, reason?: string): Promise<{ message: string }> {
    const response = await this.axios.post('/updates/reject', {
      deployment_id: deploymentId,
      reason
    });
    return response.data;
  }

  /**
   * Pause current deployment
   */
  async pause(): Promise<{ message: string }> {
    const response = await this.axios.post('/updates/pause');
    return response.data;
  }

  /**
   * Initiate rollback
   */
  async rollback(request: RollbackRequest): Promise<DeploymentStatus> {
    const response = await this.axios.post('/updates/rollback', request);
    return response.data;
  }

  /**
   * Get deployment history
   */
  async getHistory(limit = 10): Promise<DeploymentStatus[]> {
    const response = await this.axios.get('/updates/history', {
      params: { limit }
    });
    return response.data;
  }

  /**
   * Get rollback options (n-1, n-2 versions)
   */
  async getRollbackOptions(): Promise<any> {
    const response = await this.axios.get('/updates/rollback-options');
    return response.data;
  }

  /**
   * Get current running images
   */
  async getCurrentImages(): Promise<Record<string, string>> {
    const response = await this.axios.get('/updates/current-images');
    return response.data;
  }

  /**
   * Subscribe to deployment status updates
   */
  watchDeployment(deploymentId: string, onUpdate: (status: DeploymentStatus) => void): () => void {
    // Polling implementation for now
    let intervalId: NodeJS.Timeout | null = null;

    const startPolling = async () => {
      // Initial fetch
      try {
        const status = await this.getStatus();
        if (status && status.deployment_id === deploymentId) {
          onUpdate(status);
          if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
            return; // Don't start interval if already complete
          }
        }
      } catch (error) {
        console.error('Failed to fetch initial deployment status:', error);
      }

      // Set up polling
      intervalId = setInterval(async () => {
        try {
          const status = await this.getStatus();
          if (status && status.deployment_id === deploymentId) {
            onUpdate(status);
            if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled') {
              if (intervalId) clearInterval(intervalId);
            }
          }
        } catch (error) {
          console.error('Failed to poll deployment status:', error);
        }
      }, 2000);
    };

    startPolling();

    return () => {
      if (intervalId) clearInterval(intervalId);
    };
  }

  /**
   * Notify of new update (used by CD pipeline)
   */
  async notify(notification: UpdateNotification): Promise<DeploymentStatus> {
    const response = await this.axios.post('/updates/notify', notification);
    return response.data;
  }
}
