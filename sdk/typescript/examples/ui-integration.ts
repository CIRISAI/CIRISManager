/**
 * Example: Integrating CIRIS Manager SDK with the UI
 */

import { CIRISManagerClient } from '@ciris/cirismanager-sdk';

// Initialize the client
const client = new CIRISManagerClient({
  baseURL: '/manager/v1',
  timeout: 30000,
  retries: 3,
  onAuthFailure: () => {
    // Redirect to login
    window.location.href = '/manager/v1/login';
  }
});

// Set token from storage if available
const token = localStorage.getItem('ciris_token');
if (token) {
  client.setToken(token);
}

/**
 * Example: Agent Management UI
 */
class AgentManagerUI {
  private stopWatching?: () => void;

  async loadAgents() {
    try {
      const response = await client.agents.list();
      this.renderAgents(response.agents);
    } catch (error) {
      this.showError('Failed to load agents', error);
    }
  }

  async createAgent(name: string, template: string) {
    try {
      const agent = await client.agents.create({
        agent_name: name,
        template: template,
        memory_limit: '1G',
        cpu_limit: '2.0'
      });

      this.showSuccess(`Agent ${agent.agent_name} created`);
      await this.loadAgents();
    } catch (error) {
      this.showError('Failed to create agent', error);
    }
  }

  async startAgent(agentId: string) {
    try {
      await client.agents.start(agentId);
      this.showSuccess('Agent started');
      await this.loadAgents();
    } catch (error) {
      this.showError('Failed to start agent', error);
    }
  }

  watchAgentStatus(agentId: string) {
    // Stop previous watching if any
    this.stopWatching?.();

    this.stopWatching = client.agents.watchStatus(agentId, (status) => {
      this.updateAgentStatus(agentId, status);
    });
  }

  private renderAgents(agents: any[]) {
    // UI rendering logic
  }

  private updateAgentStatus(agentId: string, status: any) {
    // Update UI with new status
  }

  private showSuccess(message: string) {
    // Show success notification
  }

  private showError(message: string, error: any) {
    // Show error notification
  }
}

/**
 * Example: Deployment Management UI
 */
class DeploymentUI {
  private stopWatching?: () => void;

  async checkPendingDeployments() {
    try {
      const pending = await client.deployments.getPending();

      if (pending.length > 0) {
        this.showPendingDeployments(pending);
      }
    } catch (error) {
      console.error('Failed to check pending deployments:', error);
    }
  }

  async launchDeployment(deploymentId: string) {
    try {
      const status = await client.deployments.launch(deploymentId);

      // Start watching the deployment
      this.watchDeployment(status.deployment_id);

      this.showDeploymentStatus(status);
    } catch (error) {
      this.showError('Failed to launch deployment', error);
    }
  }

  async initiateRollback(targetVersion: 'n-1' | 'n-2') {
    try {
      const status = await client.deployments.rollback({
        target_version: targetVersion,
        reason: 'User initiated rollback'
      });

      this.watchDeployment(status.deployment_id);
      this.showDeploymentStatus(status);
    } catch (error) {
      this.showError('Failed to initiate rollback', error);
    }
  }

  watchDeployment(deploymentId: string) {
    this.stopWatching?.();

    this.stopWatching = client.deployments.watchDeployment(deploymentId, (status) => {
      this.updateDeploymentProgress(status);

      if (status.status === 'completed') {
        this.showSuccess('Deployment completed successfully');
        this.stopWatching?.();
      } else if (status.status === 'failed') {
        this.showError('Deployment failed', status.message);
        this.stopWatching?.();
      }
    });
  }

  private showPendingDeployments(deployments: any[]) {
    // Show pending deployments in UI
  }

  private showDeploymentStatus(status: any) {
    // Update deployment status in UI
  }

  private updateDeploymentProgress(status: any) {
    // Update progress bar and status
  }

  private showSuccess(message: string) {
    // Show success notification
  }

  private showError(message: string, detail?: any) {
    // Show error notification
  }
}

/**
 * Example: Telemetry Dashboard
 */
class TelemetryDashboard {
  private stopStreaming?: () => void;
  private chartData: any[] = [];

  async initialize() {
    // Load initial data
    const [status, history] = await Promise.all([
      client.telemetry.getStatus(),
      client.telemetry.getHistory({ hours: 24, interval: '5m' })
    ]);

    this.renderDashboard(status);
    this.renderChart(history.data);

    // Start streaming real-time updates
    this.startStreaming();
  }

  startStreaming() {
    this.stopStreaming = client.telemetry.streamMetrics(
      (metrics) => {
        this.updateDashboard(metrics);
        this.addChartPoint(metrics);
      },
      5000 // Update every 5 seconds
    );
  }

  stopMetricsStreaming() {
    this.stopStreaming?.();
  }

  private renderDashboard(status: any) {
    // Render initial dashboard
    document.getElementById('total-agents')!.textContent = status.agents_total.toString();
    document.getElementById('healthy-agents')!.textContent = status.agents_healthy.toString();
    document.getElementById('cpu-usage')!.textContent = `${status.total_cpu_percent.toFixed(1)}%`;
    document.getElementById('memory-usage')!.textContent = `${status.total_memory_mb} MB`;
  }

  private updateDashboard(metrics: any) {
    // Update dashboard with new metrics
    this.renderDashboard(metrics);
  }

  private renderChart(data: any[]) {
    // Initialize chart with historical data
    this.chartData = data;
    // Chart rendering logic (e.g., Chart.js)
  }

  private addChartPoint(metrics: any) {
    // Add new data point to chart
    this.chartData.push({
      timestamp: metrics.timestamp,
      agents: metrics.agents_total,
      healthy: metrics.agents_healthy
    });

    // Keep only last 100 points
    if (this.chartData.length > 100) {
      this.chartData.shift();
    }

    // Update chart
    this.updateChart();
  }

  private updateChart() {
    // Update chart visualization
  }
}

// Export for use in the actual UI
export { AgentManagerUI, DeploymentUI, TelemetryDashboard };
