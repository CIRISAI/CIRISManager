/**
 * SDK Wrapper for CIRIS Manager UI
 * 
 * This wrapper initializes the CIRIS Manager SDK and provides
 * a centralized client instance for the UI to use.
 */

// Global SDK client instance
let sdkClient = null;

/**
 * Initialize the SDK client
 * @returns {CIRISManagerSDK.CIRISManagerClient} The initialized SDK client
 */
function initializeSDK() {
    if (sdkClient) {
        return sdkClient;
    }

    // Initialize with default configuration
    sdkClient = new CIRISManagerSDK.CIRISManagerClient({
        baseURL: '/manager/v1',
        timeout: 30000,
        onAuthFailure: () => {
            // Handle auth failure - redirect to login or show auth dialog
            console.error('Authentication failed');
            // Could trigger re-authentication flow here
        }
    });

    return sdkClient;
}

/**
 * Migration helper - converts SDK responses to match existing UI expectations
 */
const SDKMigration = {
    /**
     * Fetch agents using SDK
     */
    async fetchAgents() {
        try {
            const client = initializeSDK();
            const response = await client.agents.list();
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to fetch agents:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Fetch agent versions using SDK
     */
    async fetchAgentVersions() {
        try {
            const client = initializeSDK();
            const response = await client.agents.getVersions();
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to fetch versions:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Start an agent
     */
    async startAgent(agentId) {
        try {
            const client = initializeSDK();
            await client.agents.start(agentId);
            return { ok: true };
        } catch (error) {
            console.error(`Failed to start agent ${agentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Stop an agent
     */
    async stopAgent(agentId) {
        try {
            const client = initializeSDK();
            await client.agents.stop(agentId);
            return { ok: true };
        } catch (error) {
            console.error(`Failed to stop agent ${agentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Restart an agent
     */
    async restartAgent(agentId) {
        try {
            const client = initializeSDK();
            await client.agents.restart(agentId);
            return { ok: true };
        } catch (error) {
            console.error(`Failed to restart agent ${agentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Delete an agent
     */
    async deleteAgent(agentId) {
        try {
            const client = initializeSDK();
            await client.agents.delete(agentId);
            return { ok: true };
        } catch (error) {
            console.error(`Failed to delete agent ${agentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Create a new agent
     */
    async createAgent(agentData) {
        try {
            const client = initializeSDK();
            const response = await client.agents.create(agentData);
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to create agent:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Get agent configuration
     */
    async getAgentConfig(agentId) {
        try {
            const client = initializeSDK();
            const response = await client.agents.getConfig(agentId);
            return { ok: true, data: response };
        } catch (error) {
            console.error(`Failed to get config for agent ${agentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Update agent configuration
     */
    async updateAgentConfig(agentId, config) {
        try {
            const client = initializeSDK();
            await client.agents.updateConfig(agentId, config);
            return { ok: true };
        } catch (error) {
            console.error(`Failed to update config for agent ${agentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Shutdown an agent gracefully
     */
    async shutdownAgent(agentId, force = false) {
        try {
            const client = initializeSDK();
            await client.agents.shutdown(agentId, force);
            return { ok: true };
        } catch (error) {
            console.error(`Failed to shutdown agent ${agentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    // Deployment APIs
    /**
     * Get deployment status
     */
    async getDeploymentStatus() {
        try {
            const client = initializeSDK();
            const response = await client.deployments.getStatus();
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to get deployment status:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Get pending deployments
     */
    async getPendingDeployments() {
        try {
            const client = initializeSDK();
            const response = await client.deployments.getPending();
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to get pending deployments:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Launch a deployment
     */
    async launchDeployment(deploymentId, force = false) {
        try {
            const client = initializeSDK();
            const response = await client.deployments.launch(deploymentId, force);
            return { ok: true, data: response };
        } catch (error) {
            console.error(`Failed to launch deployment ${deploymentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Reject a deployment
     */
    async rejectDeployment(deploymentId, reason) {
        try {
            const client = initializeSDK();
            await client.deployments.reject(deploymentId, reason);
            return { ok: true };
        } catch (error) {
            console.error(`Failed to reject deployment ${deploymentId}:`, error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Pause deployments
     */
    async pauseDeployments() {
        try {
            const client = initializeSDK();
            await client.deployments.pause();
            return { ok: true };
        } catch (error) {
            console.error('Failed to pause deployments:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Get deployment history
     */
    async getDeploymentHistory(limit = 10) {
        try {
            const client = initializeSDK();
            const response = await client.deployments.getHistory(limit);
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to get deployment history:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Get current images
     */
    async getCurrentImages() {
        try {
            const client = initializeSDK();
            const response = await client.deployments.getCurrentImages();
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to get current images:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Get rollback options
     */
    async getRollbackOptions() {
        try {
            const client = initializeSDK();
            const response = await client.deployments.getRollbackOptions();
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to get rollback options:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Initiate rollback
     */
    async rollback(request) {
        try {
            const client = initializeSDK();
            const response = await client.deployments.rollback(request);
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to rollback:', error);
            return { ok: false, error: error.message };
        }
    },

    // Telemetry APIs
    /**
     * Get telemetry status
     */
    async getTelemetryStatus() {
        try {
            const client = initializeSDK();
            const response = await client.telemetry.getStatus();
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to get telemetry status:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Get telemetry health
     */
    async getTelemetryHealth() {
        try {
            const client = initializeSDK();
            const response = await client.telemetry.health();
            return { ok: true, data: response };
        } catch (error) {
            console.error('Failed to get telemetry health:', error);
            return { ok: false, error: error.message };
        }
    },

    /**
     * Stream telemetry metrics
     * @param {Function} onUpdate - Callback for metric updates
     * @param {number} intervalMs - Update interval in milliseconds
     * @returns {Function} Unsubscribe function
     */
    streamMetrics(onUpdate, intervalMs = 5000) {
        const client = initializeSDK();
        return client.telemetry.streamMetrics(onUpdate, intervalMs);
    },

    /**
     * Watch deployment progress
     * @param {string} deploymentId - Deployment to watch
     * @param {Function} onUpdate - Callback for status updates
     * @returns {Function} Unsubscribe function
     */
    watchDeployment(deploymentId, onUpdate) {
        const client = initializeSDK();
        return client.deployments.watchDeployment(deploymentId, onUpdate);
    }
};

// Export for use in manager.js
window.SDKMigration = SDKMigration;
window.initializeSDK = initializeSDK;