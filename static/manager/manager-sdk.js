/**
 * CIRIS Manager UI - SDK Migration Version
 * 
 * This is a progressive migration of manager.js to use the CIRIS Manager SDK
 * instead of raw fetch calls. The migration is done incrementally to ensure
 * stability while transitioning to the SDK.
 */

// Configuration
const API_BASE = '/manager/v1';
let agents = [];
let templates = [];
let managerStatus = null;
let deploymentCheckInterval = null;
let currentDeployment = null;

// Migration flag - set to true to use SDK for specific operations
const USE_SDK = {
    agents: true,        // Agent CRUD operations
    deployments: true,   // Deployment operations
    telemetry: false,    // Telemetry operations (limited SDK support)
    templates: false,    // Templates (not in SDK)
    canary: false,       // Canary groups (not in SDK)
    oauth: false,        // OAuth (not in SDK)
    dashboard: false     // Dashboard (not in SDK)
};

// Initialize the page
document.addEventListener('DOMContentLoaded', async () => {
    // Initialize SDK if enabled
    if (Object.values(USE_SDK).some(v => v)) {
        initializeSDK();
    }
    
    // Show loading
    showLoading();
    
    try {
        await fetchData();
        await checkPendingDeployments();
    } catch (error) {
        console.error('Failed to initialize:', error);
        showError('Failed to load data. Please refresh the page.');
    } finally {
        hideLoading();
    }
    
    // Set up auto-refresh
    setInterval(refreshData, 30000);
});

// Fetch initial data
async function fetchData() {
    try {
        hideError();

        if (USE_SDK.agents) {
            // Use SDK for agents
            const [agentsResult, statusResponse] = await Promise.all([
                SDKMigration.fetchAgents(),
                fetch('/manager/v1/status', { credentials: 'include' })
            ]);

            if (!agentsResult.ok) throw new Error(`Failed to fetch agents: ${agentsResult.error}`);
            if (!statusResponse.ok) throw new Error(`Failed to fetch status: ${statusResponse.status}`);

            agents = agentsResult.data.agents || [];
            managerStatus = await statusResponse.json();
        } else {
            // Original fetch implementation
            const [agentsResponse, statusResponse] = await Promise.all([
                fetch('/manager/v1/agents', { credentials: 'include' }),
                fetch('/manager/v1/status', { credentials: 'include' })
            ]);

            if (!agentsResponse.ok) throw new Error(`Failed to fetch agents: ${agentsResponse.status}`);
            if (!statusResponse.ok) throw new Error(`Failed to fetch status: ${statusResponse.status}`);

            const agentsData = await agentsResponse.json();
            const statusData = await statusResponse.json();

            agents = agentsData.agents || [];
            managerStatus = statusData;
        }

        renderAgents();
        renderStatus();
    } catch (error) {
        showError(error.message);
        throw error;
    }
}

// Copy all the render functions from the original manager.js
// (These remain unchanged as they work with the same data structures)

function renderAgents() {
    const container = document.getElementById('agents-list');
    const countElement = document.getElementById('agent-count');

    countElement.textContent = agents.length;

    if (agents.length === 0) {
        container.innerHTML = `
            <div class="text-center py-8 text-gray-500">
                No agents running. Create one to get started.
            </div>
        `;
        return;
    }

    container.innerHTML = agents.map(agent => `
        <div class="border rounded-lg p-4 hover:bg-gray-50 transition-colors">
            <div class="flex items-start justify-between">
                <div class="space-y-1">
                    <div class="flex items-center gap-2">
                        <i class="fas fa-server text-gray-600"></i>
                        <h3 class="font-semibold">${escapeHtml(agent.name || agent.agent_name)}</h3>
                        ${agent.version ? `<span class="text-xs px-2 py-1 bg-gray-100 rounded">${escapeHtml(agent.version)}</span>` : ''}
                    </div>
                    <div class="flex items-center gap-4 text-sm text-gray-600">
                        <span class="flex items-center gap-1">
                            ${getStatusIcon(agent.status)}
                            ${agent.status}
                        </span>
                        ${agent.container_id ? `
                            <span class="font-mono text-xs">${agent.container_id.substring(0, 12)}</span>
                        ` : ''}
                    </div>
                </div>
                <div class="flex gap-2">
                    ${renderAgentActions(agent)}
                </div>
            </div>
            ${agent.resources ? renderResourceUsage(agent.resources) : ''}
        </div>
    `).join('');
}

function renderStatus() {
    if (!managerStatus) return;
    
    const statusElement = document.getElementById('manager-status');
    if (statusElement) {
        statusElement.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="text-sm text-gray-600">Manager Status</span>
                <span class="flex items-center gap-2">
                    <span class="w-2 h-2 bg-green-500 rounded-full"></span>
                    <span class="text-sm font-medium">Healthy</span>
                </span>
            </div>
            <div class="mt-2 text-xs text-gray-500">
                ${managerStatus.agents_running || 0} agents running
            </div>
        `;
    }
}

// Agent actions using SDK
async function restartAgent(agentId) {
    if (!confirm(`Restart agent ${agentId}?`)) return;
    
    try {
        showLoading();
        
        if (USE_SDK.agents) {
            const result = await SDKMigration.restartAgent(agentId);
            if (!result.ok) throw new Error(result.error);
        } else {
            const response = await fetch(`/manager/v1/agents/${agentId}/restart`, {
                method: 'POST',
                credentials: 'include'
            });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to restart agent');
            }
        }
        
        showToast('Agent restarting...', 'success');
        await fetchData();
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

async function startAgent(agentId) {
    try {
        showLoading();
        
        if (USE_SDK.agents) {
            const result = await SDKMigration.startAgent(agentId);
            if (!result.ok) throw new Error(result.error);
        } else {
            const response = await fetch(`/manager/v1/agents/${agentId}/start`, {
                method: 'POST',
                credentials: 'include'
            });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to start agent');
            }
        }
        
        showToast('Agent started', 'success');
        await fetchData();
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

async function stopAgent(agentId) {
    if (!confirm(`Stop agent ${agentId}?`)) return;
    
    try {
        showLoading();
        
        if (USE_SDK.agents) {
            const result = await SDKMigration.stopAgent(agentId);
            if (!result.ok) throw new Error(result.error);
        } else {
            const response = await fetch(`/manager/v1/agents/${agentId}/stop`, {
                method: 'POST',
                credentials: 'include'
            });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to stop agent');
            }
        }
        
        showToast('Agent stopped', 'success');
        await fetchData();
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

async function deleteAgent(agentId) {
    if (!confirm(`Delete agent ${agentId}? This action cannot be undone.`)) return;
    
    try {
        showLoading();
        
        if (USE_SDK.agents) {
            const result = await SDKMigration.deleteAgent(agentId);
            if (!result.ok) throw new Error(result.error);
        } else {
            const response = await fetch(`/manager/v1/agents/${agentId}`, {
                method: 'DELETE',
                credentials: 'include'
            });
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to delete agent');
            }
        }
        
        showToast('Agent deleted', 'success');
        await fetchData();
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

// Deployment functions using SDK
async function checkPendingDeployments() {
    try {
        let pending;
        
        if (USE_SDK.deployments) {
            const result = await SDKMigration.getPendingDeployments();
            if (!result.ok) return;
            pending = result.data;
        } else {
            const response = await fetch('/manager/v1/updates/pending', {
                credentials: 'include'
            });
            if (!response.ok) return;
            pending = await response.json();
        }
        
        if (pending && pending.length > 0) {
            showDeploymentNotification(pending[0]);
        }
    } catch (error) {
        console.error('Failed to check pending deployments:', error);
    }
}

async function launchDeployment(deploymentId) {
    try {
        showLoading();
        
        let status;
        if (USE_SDK.deployments) {
            const result = await SDKMigration.launchDeployment(deploymentId);
            if (!result.ok) throw new Error(result.error);
            status = result.data;
        } else {
            const response = await fetch('/manager/v1/updates/launch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ deployment_id: deploymentId })
            });
            if (!response.ok) throw new Error('Failed to launch deployment');
            status = await response.json();
        }
        
        currentDeployment = status;
        showToast('Deployment launched', 'success');
        
        // Start monitoring if using SDK
        if (USE_SDK.deployments) {
            SDKMigration.watchDeployment(deploymentId, (update) => {
                updateDeploymentProgress(update);
            });
        }
    } catch (error) {
        showError(error.message);
    } finally {
        hideLoading();
    }
}

// Utility functions (unchanged from original)
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function getStatusIcon(status) {
    const icons = {
        'running': '<i class="fas fa-check-circle text-green-500"></i>',
        'stopped': '<i class="fas fa-stop-circle text-gray-500"></i>',
        'error': '<i class="fas fa-exclamation-circle text-red-500"></i>',
        'starting': '<i class="fas fa-spinner fa-spin text-blue-500"></i>',
        'stopping': '<i class="fas fa-spinner fa-spin text-orange-500"></i>'
    };
    return icons[status] || '<i class="fas fa-question-circle text-gray-500"></i>';
}

function renderAgentActions(agent) {
    const actions = [];
    
    if (agent.status === 'running') {
        actions.push(`
            <button onclick="restartAgent('${agent.agent_id}')" 
                    class="p-2 text-blue-600 hover:bg-blue-50 rounded" 
                    title="Restart">
                <i class="fas fa-sync-alt"></i>
            </button>
            <button onclick="stopAgent('${agent.agent_id}')" 
                    class="p-2 text-orange-600 hover:bg-orange-50 rounded" 
                    title="Stop">
                <i class="fas fa-stop"></i>
            </button>
        `);
    } else {
        actions.push(`
            <button onclick="startAgent('${agent.agent_id}')" 
                    class="p-2 text-green-600 hover:bg-green-50 rounded" 
                    title="Start">
                <i class="fas fa-play"></i>
            </button>
        `);
    }
    
    actions.push(`
        <button onclick="deleteAgent('${agent.agent_id}')" 
                class="p-2 text-red-600 hover:bg-red-50 rounded" 
                title="Delete">
            <i class="fas fa-trash"></i>
        </button>
    `);
    
    return actions.join('');
}

function renderResourceUsage(resources) {
    if (!resources) return '';
    
    return `
        <div class="mt-3 pt-3 border-t text-xs text-gray-600">
            <div class="flex gap-4">
                <span>CPU: ${resources.cpu_percent?.toFixed(1) || 0}%</span>
                <span>Memory: ${resources.memory_mb?.toFixed(0) || 0} MB</span>
                ${resources.disk_usage_mb ? `<span>Disk: ${resources.disk_usage_mb.toFixed(0)} MB</span>` : ''}
            </div>
        </div>
    `;
}

// UI helper functions
function showLoading() {
    document.getElementById('loading').classList.remove('hidden');
    document.getElementById('app').classList.add('hidden');
}

function hideLoading() {
    document.getElementById('loading').classList.add('hidden');
    document.getElementById('app').classList.remove('hidden');
}

function showError(message) {
    const errorDiv = document.createElement('div');
    errorDiv.className = 'fixed top-4 right-4 bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded z-50';
    errorDiv.innerHTML = `
        <span class="block sm:inline">${escapeHtml(message)}</span>
        <button onclick="this.parentElement.remove()" class="absolute top-0 right-0 px-4 py-3">
            <i class="fas fa-times"></i>
        </button>
    `;
    document.body.appendChild(errorDiv);
    setTimeout(() => errorDiv.remove(), 5000);
}

function hideError() {
    // Remove any existing error messages
    document.querySelectorAll('.bg-red-100').forEach(el => el.remove());
}

function showToast(message, type = 'info') {
    const colors = {
        'success': 'bg-green-100 border-green-400 text-green-700',
        'error': 'bg-red-100 border-red-400 text-red-700',
        'warning': 'bg-yellow-100 border-yellow-400 text-yellow-700',
        'info': 'bg-blue-100 border-blue-400 text-blue-700'
    };
    
    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 ${colors[type]} px-4 py-3 rounded shadow-lg z-50`;
    toast.innerHTML = escapeHtml(message);
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

async function refreshData() {
    try {
        await fetchData();
        // Rotate refresh icon
        const icon = document.getElementById('refresh-icon');
        icon.classList.add('fa-spin');
        setTimeout(() => icon.classList.remove('fa-spin'), 1000);
    } catch (error) {
        console.error('Failed to refresh:', error);
    }
}

// Tab switching
function switchTab(tabName) {
    // Hide all tabs
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.classList.add('hidden');
    });
    
    // Remove active class from all tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('tab-active');
    });
    
    // Show selected tab
    const selectedTab = document.getElementById(`${tabName}-tab`);
    if (selectedTab) {
        selectedTab.classList.remove('hidden');
    }
    
    // Add active class to selected button
    event.target.classList.add('tab-active');
    
    // Load tab-specific data if needed
    if (tabName === 'deployments' && USE_SDK.deployments) {
        loadDeploymentTab();
    }
}

async function loadDeploymentTab() {
    try {
        // Load deployment status
        const statusResult = await SDKMigration.getDeploymentStatus();
        if (statusResult.ok && statusResult.data) {
            updateDeploymentProgress(statusResult.data);
        }
        
        // Load deployment history
        const historyResult = await SDKMigration.getDeploymentHistory();
        if (historyResult.ok) {
            renderDeploymentHistory(historyResult.data);
        }
    } catch (error) {
        console.error('Failed to load deployment tab:', error);
    }
}

function updateDeploymentProgress(status) {
    // Implementation for updating deployment progress UI
    console.log('Deployment progress:', status);
}

function renderDeploymentHistory(history) {
    // Implementation for rendering deployment history
    console.log('Deployment history:', history);
}

function showDeploymentNotification(deployment) {
    // Implementation for showing deployment notification
    console.log('Pending deployment:', deployment);
}

// Export functions for HTML onclick handlers
window.fetchData = fetchData;
window.refreshData = refreshData;
window.restartAgent = restartAgent;
window.startAgent = startAgent;
window.stopAgent = stopAgent;
window.deleteAgent = deleteAgent;
window.switchTab = switchTab;
window.showCreateDialog = () => console.log('Create dialog not implemented yet');
window.copyToClipboard = (elementId) => {
    const element = document.getElementById(elementId);
    if (element) {
        navigator.clipboard.writeText(element.value);
        showToast('Copied to clipboard', 'success');
    }
};