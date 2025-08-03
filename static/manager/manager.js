// CIRIS Manager Client - Based on Tyler's original work
// Using vanilla JavaScript and AJAX instead of React

let agents = [];
let templates = null;
let managerStatus = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    // Check if user is authenticated
    try {
        await fetchData();
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('app').classList.remove('hidden');
    } catch (error) {
        if (error.message.includes('401')) {
            window.location.href = '/manager/oauth/login';
        } else {
            showError(error.message);
        }
    }
});

// Fetch data from API
async function fetchData() {
    try {
        hideError();
        
        // Fetch agents and status in parallel
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

        renderAgents();
        renderStatus();
    } catch (error) {
        showError(error.message);
        throw error;
    }
}

// Render agents list
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
                        <span class="px-2 py-1 bg-gray-100 text-gray-700 text-sm rounded">
                            ${escapeHtml(agent.template)}
                        </span>
                    </div>
                    <div class="text-sm text-gray-600 space-y-1">
                        <div>ID: ${escapeHtml(agent.agent_id)}</div>
                        <div>Container: ${escapeHtml(agent.container_name)}</div>
                        <div>Port: ${agent.api_port || agent.port}</div>
                        <div class="flex items-center gap-1">
                            <span class="inline-block w-2 h-2 bg-green-500 rounded-full"></span>
                            ${agent.status || 'running'}
                        </div>
                    </div>
                </div>
                <div>
                    <button onclick="openAgentUI('${agent.agent_id}')" class="px-3 py-1 text-blue-600 hover:bg-blue-50 rounded">
                        <i class="fas fa-external-link-alt"></i> Open
                    </button>
                    <button onclick="deleteAgent('${agent.agent_id}')" class="px-3 py-1 text-red-600 hover:bg-red-50 rounded">
                        <i class="fas fa-trash"></i> Delete
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

// Render manager status
function renderStatus() {
    const container = document.getElementById('manager-status');
    
    if (!managerStatus) {
        container.innerHTML = '<div class="text-gray-500">Loading...</div>';
        return;
    }

    container.innerHTML = `
        <div class="space-y-2">
            <div><strong>Status:</strong> ${managerStatus.status}</div>
            <div><strong>Version:</strong> ${managerStatus.version || '1.0.0'}</div>
            <div><strong>Auth Mode:</strong> ${managerStatus.auth_mode || 'production'}</div>
            <div class="pt-2">
                <strong>Components:</strong>
                <ul class="list-disc list-inside mt-1">
                    ${Object.entries(managerStatus.components || {}).map(([key, value]) => 
                        `<li>${key}: ${value}</li>`
                    ).join('')}
                </ul>
            </div>
        </div>
    `;
}

// Switch tabs
function switchTab(tab) {
    // Update tab buttons
    document.querySelectorAll('[id$="-tab"]').forEach(btn => {
        btn.classList.remove('tab-active', 'text-blue-600');
        btn.classList.add('text-gray-500');
    });
    document.getElementById(`${tab}-tab`).classList.add('tab-active', 'text-blue-600');
    document.getElementById(`${tab}-tab`).classList.remove('text-gray-500');

    // Update content
    document.querySelectorAll('[id$="-content"]').forEach(content => {
        content.classList.add('hidden');
    });
    document.getElementById(`${tab}-content`).classList.remove('hidden');
    
    // Fetch version data when switching to versions tab
    if (tab === 'versions') {
        fetchVersionData();
    }
}

// Refresh data
async function refreshData() {
    const icon = document.getElementById('refresh-icon');
    icon.classList.add('fa-spin');
    
    try {
        await fetchData();
    } finally {
        icon.classList.remove('fa-spin');
    }
}

// Show create dialog
async function showCreateDialog() {
    document.getElementById('create-dialog').classList.remove('hidden');
    
    // Load templates if not already loaded
    if (!templates) {
        try {
            const response = await fetch('/manager/v1/templates', { credentials: 'include' });
            if (!response.ok) throw new Error('Failed to load templates');
            templates = await response.json();
            
            // Populate template select
            const select = document.getElementById('template-select');
            select.innerHTML = '<option value="">Select a template...</option>';
            
            Object.keys(templates.templates || {}).forEach(name => {
                const option = document.createElement('option');
                option.value = name;
                option.textContent = name;
                select.appendChild(option);
            });
        } catch (error) {
            showError('Failed to load templates: ' + error.message);
        }
    }
}

// Hide create dialog
function hideCreateDialog() {
    document.getElementById('create-dialog').classList.add('hidden');
    document.getElementById('create-agent-form').reset();
    document.getElementById('wa-signature-field').classList.add('hidden');
}

// Check if template needs approval
function checkTemplateApproval() {
    const template = document.getElementById('template-select').value;
    const waField = document.getElementById('wa-signature-field');
    
    if (templates && template) {
        const isPreApproved = templates.pre_approved?.includes(template);
        if (isPreApproved) {
            waField.classList.add('hidden');
        } else {
            waField.classList.remove('hidden');
        }
    }
}

// Add environment variable row
function addEnvVar() {
    const container = document.getElementById('env-vars-container');
    const newRow = document.createElement('div');
    newRow.className = 'flex gap-2';
    newRow.innerHTML = `
        <input type="text" placeholder="Key" class="flex-1 p-2 border rounded-lg env-key">
        <input type="text" placeholder="Value" class="flex-1 p-2 border rounded-lg env-value">
        <button type="button" onclick="this.parentElement.remove()" class="px-3 py-2 bg-red-100 rounded-lg hover:bg-red-200">
            <i class="fas fa-trash"></i>
        </button>
    `;
    container.appendChild(newRow);
}

// Handle create agent form submission
async function handleCreateAgent(event) {
    event.preventDefault();
    
    const formData = new FormData(event.target);
    const data = {
        template: formData.get('template'),
        name: formData.get('name'),
        environment: {},
        wa_signature: formData.get('wa_signature') || undefined
    };
    
    // Collect environment variables
    const envKeys = document.querySelectorAll('.env-key');
    const envValues = document.querySelectorAll('.env-value');
    
    envKeys.forEach((key, index) => {
        if (key.value && envValues[index]) {
            data.environment[key.value] = envValues[index].value;
        }
    });
    
    try {
        const response = await fetch('/manager/v1/agents', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create agent');
        }
        
        hideCreateDialog();
        await refreshData();
    } catch (error) {
        showError('Failed to create agent: ' + error.message);
    }
}

// Delete agent
async function deleteAgent(agentId) {
    if (!confirm(`Are you sure you want to delete agent ${agentId}?`)) {
        return;
    }
    
    try {
        const response = await fetch(`/manager/v1/agents/${agentId}`, {
            method: 'DELETE',
            credentials: 'include'
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete agent');
        }
        
        await refreshData();
    } catch (error) {
        showError('Failed to delete agent: ' + error.message);
    }
}

// Open agent UI
function openAgentUI(agentId) {
    window.open(`/comms?agent=${agentId}`, '_blank');
}

// Fetch version adoption data
async function fetchVersionData() {
    try {
        const response = await fetch('/manager/v1/versions/adoption', { 
            credentials: 'include' 
        });
        
        if (!response.ok) throw new Error(`Failed to fetch version data: ${response.status}`);
        
        const data = await response.json();
        renderVersionData(data);
    } catch (error) {
        showError('Failed to fetch version data: ' + error.message);
    }
}

// Render version data
function renderVersionData(data) {
    // Render latest versions
    const latestVersions = data.latest_versions || {};
    document.getElementById('current-agent-image').textContent = latestVersions.agent_image || 'Unknown';
    document.getElementById('current-gui-image').textContent = latestVersions.gui_image || 'Unknown';
    
    // Extract digests from version data (if available)
    document.getElementById('current-agent-digest').textContent = 'N/A';
    document.getElementById('current-gui-digest').textContent = 'N/A';
    
    // Render deployment status
    const deploymentStatus = document.getElementById('deployment-status');
    if (data.current_deployment) {
        const deployment = data.current_deployment;
        deploymentStatus.innerHTML = `
            <div class="space-y-2">
                <div class="flex justify-between">
                    <span class="font-medium">Deployment ID:</span>
                    <span class="text-sm font-mono">${escapeHtml(deployment.deployment_id)}</span>
                </div>
                <div class="flex justify-between">
                    <span class="font-medium">Status:</span>
                    <span class="px-2 py-1 text-xs rounded ${
                        deployment.status === 'in_progress' ? 'bg-yellow-100 text-yellow-800' : 
                        deployment.status === 'completed' ? 'bg-green-100 text-green-800' : 
                        'bg-red-100 text-red-800'
                    }">${escapeHtml(deployment.status)}</span>
                </div>
                <div class="flex justify-between">
                    <span class="font-medium">Progress:</span>
                    <span>${deployment.agents_updated} / ${deployment.agents_total} agents</span>
                </div>
                <div class="flex justify-between">
                    <span class="font-medium">Message:</span>
                    <span class="text-sm">${escapeHtml(deployment.message)}</span>
                </div>
            </div>
        `;
    } else {
        deploymentStatus.innerHTML = '<p class="text-gray-600">No active deployment</p>';
    }
    
    // Render agent version table
    const tableBody = document.getElementById('agent-versions-table');
    if (data.agent_versions && data.agent_versions.length > 0) {
        tableBody.innerHTML = data.agent_versions.map(agent => {
            const isUpToDate = (
                agent.current_agent_image === latestVersions.agent_image &&
                agent.current_gui_image === latestVersions.gui_image
            );
            
            return `
                <tr>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        ${escapeHtml(agent.agent_name)}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${
                            agent.status === 'running' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                        }">
                            ${escapeHtml(agent.status)}
                        </span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        <span class="font-mono text-xs">${formatImageDigest(agent.current_agent_image)}</span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        <span class="font-mono text-xs">${formatImageDigest(agent.current_gui_image)}</span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        ${agent.last_updated === 'never' ? 'Never' : formatDate(agent.last_updated)}
                        ${isUpToDate ? 
                            '<span class="ml-2 text-green-600"><i class="fas fa-check-circle"></i></span>' : 
                            '<span class="ml-2 text-yellow-600"><i class="fas fa-exclamation-circle"></i></span>'
                        }
                    </td>
                </tr>
            `;
        }).join('');
    } else {
        tableBody.innerHTML = `
            <tr>
                <td colspan="5" class="px-6 py-4 text-center text-gray-500">
                    No agent version data available
                </td>
            </tr>
        `;
    }
    
    // Render deployment history
    const historyContainer = document.getElementById('deployment-history');
    if (data.recent_deployments && data.recent_deployments.length > 0) {
        historyContainer.innerHTML = data.recent_deployments.map(deployment => `
            <div class="bg-gray-50 p-3 rounded flex justify-between items-center">
                <div>
                    <div class="text-sm font-medium">${escapeHtml(deployment.message)}</div>
                    <div class="text-xs text-gray-500">
                        ${formatDate(deployment.completed_at)} - 
                        ${deployment.agents_updated} of ${deployment.agents_total} agents updated
                    </div>
                </div>
                <span class="px-2 py-1 text-xs rounded ${
                    deployment.status === 'completed' ? 'bg-green-100 text-green-800' : 
                    'bg-red-100 text-red-800'
                }">
                    ${escapeHtml(deployment.status)}
                </span>
            </div>
        `).join('');
    } else {
        historyContainer.innerHTML = '<p class="text-gray-500 text-sm">No deployment history available</p>';
    }
}

// Format image digest for display
function formatImageDigest(digest) {
    if (!digest || digest === 'unknown') return 'Unknown';
    if (digest.startsWith('sha256:')) {
        return digest.substring(0, 19) + '...';
    }
    return digest;
}

// Format date
function formatDate(dateString) {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
}

// Logout
async function logout() {
    try {
        const response = await fetch('/manager/v1/oauth/logout', {
            method: 'POST',
            credentials: 'include'  // Use cookies, not Bearer token
        });
        
        if (response.ok) {
            // Redirect to manager root
            window.location.href = '/manager/';
        } else {
            console.error('Logout failed:', response.status);
        }
    } catch (error) {
        console.error('Logout error:', error);
    }
}

// Show error message
function showError(message) {
    const alert = document.getElementById('error-alert');
    const messageElement = document.getElementById('error-message');
    messageElement.textContent = message;
    alert.classList.remove('hidden');
}

// Hide error message
function hideError() {
    document.getElementById('error-alert').classList.add('hidden');
}

// Utility: Escape HTML to prevent XSS
function escapeHtml(unsafe) {
    return unsafe
        ? unsafe.toString()
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;")
        : '';
}

// OAuth Modal Functions
function showOAuthModal(agentId) {
    // Update agent ID in modal
    document.getElementById('oauth-agent-id').textContent = agentId;
    
    // Update callback URLs with actual agent ID
    const baseUrl = 'https://agents.ciris.ai/v1/auth/oauth';
    document.getElementById('google-callback-url').value = `${baseUrl}/${agentId}/google/callback`;
    document.getElementById('github-callback-url').value = `${baseUrl}/${agentId}/github/callback`;
    document.getElementById('discord-callback-url').value = `${baseUrl}/${agentId}/discord/callback`;
    
    // Show modal
    document.getElementById('oauth-setup-modal').classList.remove('hidden');
}

function hideOAuthModal() {
    document.getElementById('oauth-setup-modal').classList.add('hidden');
}

// Copy to clipboard with visual feedback
async function copyToClipboard(elementId) {
    const input = document.getElementById(elementId);
    const button = input.nextElementSibling;
    const originalHTML = button.innerHTML;
    
    try {
        await navigator.clipboard.writeText(input.value);
        
        // Show success feedback
        button.innerHTML = '<i class="fas fa-check"></i> Copied!';
        button.classList.remove('bg-blue-600', 'hover:bg-blue-700');
        button.classList.add('bg-green-600');
        
        // Reset after 2 seconds
        setTimeout(() => {
            button.innerHTML = originalHTML;
            button.classList.remove('bg-green-600');
            button.classList.add('bg-blue-600', 'hover:bg-blue-700');
        }, 2000);
    } catch (err) {
        console.error('Failed to copy:', err);
        // Fallback for older browsers
        input.select();
        document.execCommand('copy');
    }
}

// Notify Eric about OAuth setup request
async function notifyEric() {
    const agentId = document.getElementById('oauth-agent-id').textContent;
    const button = event.target.closest('button');
    const originalHTML = button.innerHTML;
    
    try {
        button.disabled = true;
        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
        
        // In a real implementation, this would send a notification
        // For now, we'll simulate it
        const message = `OAuth setup requested for agent: ${agentId}\n` +
                       `Google: https://agents.ciris.ai/v1/auth/oauth/${agentId}/google/callback\n` +
                       `GitHub: https://agents.ciris.ai/v1/auth/oauth/${agentId}/github/callback\n` +
                       `Discord: https://agents.ciris.ai/v1/auth/oauth/${agentId}/discord/callback`;
        
        // TODO: Implement actual notification (Slack/Discord webhook, email, etc.)
        console.log('Notification to Eric:', message);
        
        // Simulate success
        await new Promise(resolve => setTimeout(resolve, 1000));
        
        button.innerHTML = '<i class="fas fa-check"></i> Notified!';
        button.classList.remove('bg-amber-600', 'hover:bg-amber-700');
        button.classList.add('bg-green-600');
        
        setTimeout(() => {
            button.innerHTML = originalHTML;
            button.classList.remove('bg-green-600');
            button.classList.add('bg-amber-600', 'hover:bg-amber-700');
            button.disabled = false;
        }, 3000);
        
    } catch (error) {
        console.error('Failed to notify:', error);
        button.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Failed';
        button.classList.add('bg-red-600');
        setTimeout(() => {
            button.innerHTML = originalHTML;
            button.classList.remove('bg-red-600');
            button.classList.add('bg-amber-600', 'hover:bg-amber-700');
            button.disabled = false;
        }, 3000);
    }
}

// Verify OAuth setup
async function verifyOAuth() {
    const agentId = document.getElementById('oauth-agent-id').textContent;
    const button = event.target.closest('button');
    const originalHTML = button.innerHTML;
    
    try {
        button.disabled = true;
        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Verifying...';
        
        // Check OAuth status via API
        const response = await fetch(`${API_BASE}/agents/${agentId}/oauth/verify`, {
            credentials: 'include'
        });
        
        if (response.ok) {
            const result = await response.json();
            
            if (result.configured && result.working) {
                button.innerHTML = '<i class="fas fa-check-circle"></i> Verified!';
                button.classList.remove('bg-green-600', 'hover:bg-green-700');
                button.classList.add('bg-green-600');
                
                // Update status badge
                const statusBadge = document.getElementById('oauth-status');
                statusBadge.textContent = 'Configured';
                statusBadge.classList.remove('bg-yellow-100', 'text-yellow-800');
                statusBadge.classList.add('bg-green-100', 'text-green-800');
                
            } else {
                button.innerHTML = '<i class="fas fa-times-circle"></i> Not Ready';
                button.classList.add('bg-yellow-600');
            }
        } else {
            throw new Error('Verification failed');
        }
        
    } catch (error) {
        console.error('OAuth verification error:', error);
        button.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Error';
        button.classList.add('bg-red-600');
    }
    
    setTimeout(() => {
        button.innerHTML = originalHTML;
        button.classList.remove('bg-yellow-600', 'bg-red-600');
        button.classList.add('bg-green-600', 'hover:bg-green-700');
        button.disabled = false;
    }, 3000);
}

// Mark OAuth as complete
async function markOAuthComplete() {
    const agentId = document.getElementById('oauth-agent-id').textContent;
    
    try {
        const response = await fetch(`${API_BASE}/agents/${agentId}/oauth/complete`, {
            method: 'POST',
            credentials: 'include'
        });
        
        if (response.ok) {
            hideOAuthModal();
            await refreshData(); // Refresh agent list to show updated status
        } else {
            showError('Failed to mark OAuth as complete');
        }
    } catch (error) {
        console.error('Error marking OAuth complete:', error);
        showError('Failed to update OAuth status');
    }
}

// Open OAuth documentation
function openOAuthDocs() {
    window.open('https://docs.ciris.ai/oauth-setup', '_blank');
}