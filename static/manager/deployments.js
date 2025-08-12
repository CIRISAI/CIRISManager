// Global state
let currentDeployments = [];
let versionHistory = {};
let pendingRollback = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    refreshDeployments();
    setInterval(refreshDeployments, 5000); // Auto-refresh every 5 seconds
});

async function refreshDeployments() {
    try {
        // Fetch all deployment data in parallel
        const [deploymentsRes, versionsRes, statusRes] = await Promise.all([
            fetch('/manager/v1/updates/status'),
            fetch('/manager/v1/agents/versions'),
            fetch('/manager/v1/updates/history?limit=20')
        ]);

        const deploymentStatus = await deploymentsRes.json();
        const agentVersions = await versionsRes.json();
        const deploymentHistory = await statusRes.json();

        updateActiveDeployments(deploymentStatus);
        updateVersionTimeline(agentVersions);
        updateDeploymentHistory(deploymentHistory.deployments || []);
        
    } catch (error) {
        console.error('Failed to refresh deployments:', error);
    }
}

function updateActiveDeployments(status) {
    const container = document.getElementById('activeDeployments');
    
    if (!status.active_deployment && !status.staged_deployment) {
        container.innerHTML = `
            <div class="bg-white rounded-lg shadow p-6 text-center text-gray-500">
                No active or staged deployments
            </div>
        `;
        return;
    }

    let html = '';

    // Show staged deployment
    if (status.staged_deployment) {
        const deployment = status.staged_deployment;
        html += `
            <div class="deployment-card bg-yellow-50 border-2 border-yellow-300 rounded-lg p-6">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="flex items-center">
                            <span class="inline-block w-3 h-3 bg-yellow-400 rounded-full timeline-dot mr-2"></span>
                            <h3 class="text-lg font-semibold">Staged Deployment</h3>
                        </div>
                        <p class="text-sm text-gray-600 mt-1">${deployment.deployment_id}</p>
                        <p class="mt-2">${deployment.message}</p>
                        <div class="mt-3 space-y-1">
                            <div class="text-sm">
                                <span class="font-medium">Version:</span> 
                                <span class="version-badge">${extractVersion(deployment.notification?.agent_image)}</span>
                            </div>
                            <div class="text-sm">
                                <span class="font-medium">Strategy:</span> ${deployment.notification?.strategy || 'immediate'}
                            </div>
                            <div class="text-sm">
                                <span class="font-medium">Agents:</span> ${deployment.agents_total} total
                            </div>
                        </div>
                    </div>
                    <div class="space-y-2">
                        <button onclick="approveDeployment('${deployment.deployment_id}')" 
                                class="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700">
                            <i class="fas fa-check mr-1"></i> Approve
                        </button>
                        <button onclick="rejectDeployment('${deployment.deployment_id}')" 
                                class="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700">
                            <i class="fas fa-times mr-1"></i> Reject
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    // Show active deployment
    if (status.active_deployment) {
        const deployment = status.active_deployment;
        const progress = ((deployment.agents_updated || 0) / (deployment.agents_total || 1)) * 100;
        
        html += `
            <div class="deployment-card bg-blue-50 border-2 border-blue-300 rounded-lg p-6">
                <div class="flex justify-between items-start">
                    <div class="flex-1">
                        <div class="flex items-center">
                            <span class="inline-block w-3 h-3 bg-blue-400 rounded-full timeline-dot mr-2"></span>
                            <h3 class="text-lg font-semibold">Active Deployment</h3>
                        </div>
                        <p class="text-sm text-gray-600 mt-1">${deployment.deployment_id}</p>
                        <p class="mt-2">${deployment.message}</p>
                        
                        <!-- Progress bar -->
                        <div class="mt-4">
                            <div class="flex justify-between text-sm text-gray-600 mb-1">
                                <span>Progress</span>
                                <span>${deployment.agents_updated || 0}/${deployment.agents_total || 0} agents</span>
                            </div>
                            <div class="w-full bg-gray-200 rounded-full h-2">
                                <div class="bg-blue-600 h-2 rounded-full transition-all duration-500" 
                                     style="width: ${progress}%"></div>
                            </div>
                        </div>

                        <!-- Phase information -->
                        ${deployment.canary_phase ? `
                            <div class="mt-3 text-sm">
                                <span class="font-medium">Current Phase:</span> 
                                <span class="capitalize">${deployment.canary_phase}</span>
                            </div>
                        ` : ''}
                    </div>
                    <div class="space-y-2">
                        <button onclick="pauseDeployment('${deployment.deployment_id}')" 
                                class="px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700">
                            <i class="fas fa-pause mr-1"></i> Pause
                        </button>
                        <button onclick="showRollbackOptions('${deployment.deployment_id}', 'active')" 
                                class="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700">
                            <i class="fas fa-undo mr-1"></i> Rollback
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
}

function updateVersionTimeline(versions) {
    // Get the first agent's version info as representative
    const agentVersions = Object.values(versions.agents || {})[0];
    
    if (agentVersions) {
        document.getElementById('currentVersion').textContent = 
            extractVersion(agentVersions.running_version) || 'Unknown';
        
        // We need to fetch version history to get n-1 and n-2
        fetchVersionHistory();
    }
}

async function fetchVersionHistory() {
    try {
        // Get version history from deployment history
        const response = await fetch('/manager/v1/updates/history?limit=3');
        const data = await response.json();
        const deployments = data.deployments || [];
        
        if (deployments.length > 0) {
            document.getElementById('currentVersion').textContent = 
                extractVersion(deployments[0]?.notification?.agent_image) || 'Current';
        }
        if (deployments.length > 1) {
            document.getElementById('n1Version').textContent = 
                extractVersion(deployments[1]?.notification?.agent_image) || 'n-1';
        }
        if (deployments.length > 2) {
            document.getElementById('n2Version').textContent = 
                extractVersion(deployments[2]?.notification?.agent_image) || 'n-2';
        }
    } catch (error) {
        console.error('Failed to fetch version history:', error);
    }
}

function updateDeploymentHistory(deployments) {
    const tbody = document.getElementById('deploymentTableBody');
    
    if (!deployments || deployments.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="px-6 py-4 text-center text-gray-500">
                    No deployment history available
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = deployments.map((deployment, index) => {
        const version = extractVersion(deployment.notification?.agent_image);
        const statusColor = getStatusColor(deployment.status);
        const canRollback = deployment.status === 'completed' && index > 0;
        
        return `
            <tr>
                <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                    ${deployment.deployment_id}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    <span class="version-badge">${version}</span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                    <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full ${statusColor}">
                        ${deployment.status}
                    </span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    ${formatDate(deployment.started_at)}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-sm">
                    ${canRollback ? `
                        <div class="flex space-x-2">
                            <button onclick="initiateRollback('${deployment.deployment_id}', 'n-1', '${deployments[index + 1]?.notification?.agent_image}')" 
                                    class="rollback-option px-3 py-1 border border-gray-300 rounded text-gray-700 hover:bg-blue-50">
                                <i class="fas fa-step-backward mr-1"></i> n-1
                            </button>
                            ${index < deployments.length - 2 ? `
                                <button onclick="initiateRollback('${deployment.deployment_id}', 'n-2', '${deployments[index + 2]?.notification?.agent_image}')" 
                                        class="rollback-option px-3 py-1 border border-gray-300 rounded text-gray-700 hover:bg-blue-50">
                                    <i class="fas fa-fast-backward mr-1"></i> n-2
                                </button>
                            ` : ''}
                        </div>
                    ` : '<span class="text-gray-400">-</span>'}
                </td>
            </tr>
        `;
    }).join('');
}

function initiateRollback(deploymentId, targetVersion, targetImage) {
    pendingRollback = {
        deploymentId,
        targetVersion,
        targetImage: extractVersion(targetImage)
    };
    
    // Show rollback modal
    const modal = document.getElementById('rollbackModal');
    const details = document.getElementById('rollbackDetails');
    
    details.innerHTML = `
        <div class="space-y-2">
            <div><strong>Target Version:</strong> ${targetVersion} (${pendingRollback.targetImage})</div>
            <div><strong>Deployment ID:</strong> ${deploymentId}</div>
            <div class="text-yellow-600 text-sm mt-2">
                <i class="fas fa-exclamation-triangle mr-1"></i>
                This will rollback all agents to the selected version.
            </div>
        </div>
    `;
    
    modal.classList.remove('hidden');
}

async function confirmRollback() {
    if (!pendingRollback) return;
    
    const reason = document.getElementById('rollbackReason').value;
    if (!reason.trim()) {
        alert('Please provide a reason for the rollback');
        return;
    }
    
    try {
        const response = await fetch('/manager/v1/updates/rollback', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                deployment_id: pendingRollback.deploymentId,
                target_version: pendingRollback.targetVersion,
                reason: reason
            })
        });
        
        if (response.ok) {
            showNotification('Rollback initiated successfully', 'success');
            closeRollbackModal();
            refreshDeployments();
        } else {
            const error = await response.json();
            showNotification(`Rollback failed: ${error.detail}`, 'error');
        }
    } catch (error) {
        showNotification(`Rollback failed: ${error.message}`, 'error');
    }
}

function closeRollbackModal() {
    document.getElementById('rollbackModal').classList.add('hidden');
    document.getElementById('rollbackReason').value = '';
    pendingRollback = null;
}

async function approveDeployment(deploymentId) {
    try {
        const response = await fetch('/manager/v1/updates/approve', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ deployment_id: deploymentId })
        });
        
        if (response.ok) {
            showNotification('Deployment approved', 'success');
            refreshDeployments();
        } else {
            const error = await response.json();
            showNotification(`Failed to approve: ${error.detail}`, 'error');
        }
    } catch (error) {
        showNotification(`Failed to approve: ${error.message}`, 'error');
    }
}

async function rejectDeployment(deploymentId) {
    const reason = prompt('Please provide a reason for rejection:');
    if (!reason) return;
    
    try {
        const response = await fetch('/manager/v1/updates/reject', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                deployment_id: deploymentId,
                reason: reason
            })
        });
        
        if (response.ok) {
            showNotification('Deployment rejected', 'success');
            refreshDeployments();
        } else {
            const error = await response.json();
            showNotification(`Failed to reject: ${error.detail}`, 'error');
        }
    } catch (error) {
        showNotification(`Failed to reject: ${error.message}`, 'error');
    }
}

async function pauseDeployment(deploymentId) {
    try {
        const response = await fetch('/manager/v1/updates/pause', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ deployment_id: deploymentId })
        });
        
        if (response.ok) {
            showNotification('Deployment paused', 'success');
            refreshDeployments();
        } else {
            const error = await response.json();
            showNotification(`Failed to pause: ${error.detail}`, 'error');
        }
    } catch (error) {
        showNotification(`Failed to pause: ${error.message}`, 'error');
    }
}

// Utility functions
function extractVersion(imageTag) {
    if (!imageTag) return 'Unknown';
    const match = imageTag.match(/:v?(\d+\.\d+\.\d+)/);
    return match ? `v${match[1]}` : imageTag.split(':').pop();
}

function getStatusColor(status) {
    const colors = {
        'completed': 'bg-green-100 text-green-800',
        'in_progress': 'bg-blue-100 text-blue-800',
        'staged': 'bg-yellow-100 text-yellow-800',
        'failed': 'bg-red-100 text-red-800',
        'rolled_back': 'bg-purple-100 text-purple-800',
        'rejected': 'bg-gray-100 text-gray-800'
    };
    return colors[status] || 'bg-gray-100 text-gray-800';
}

function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleString();
}

function showNotification(message, type = 'info') {
    // Create notification element
    const notification = document.createElement('div');
    notification.className = `fixed bottom-4 right-4 p-4 rounded-lg shadow-lg ${
        type === 'success' ? 'bg-green-500 text-white' :
        type === 'error' ? 'bg-red-500 text-white' :
        'bg-blue-500 text-white'
    }`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    // Remove after 3 seconds
    setTimeout(() => {
        notification.remove();
    }, 3000);
}