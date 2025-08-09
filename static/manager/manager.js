// CIRIS Manager Client - Based on Tyler's original work
// Using vanilla JavaScript and AJAX instead of React

const API_BASE = '/manager/v1';
let agents = [];
let templates = null;
let managerStatus = null;
let refreshInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    // Check if user is authenticated
    try {
        await fetchData();
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('app').classList.remove('hidden');

        // Start auto-refresh every 5 seconds
        refreshInterval = setInterval(fetchData, 5000);
    } catch (error) {
        if (error.message.includes('401')) {
            window.location.href = '/manager/v1/oauth/login';
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
                        ${agent.version ? `
                            <span class="px-2 py-1 bg-blue-100 text-blue-700 text-sm rounded flex items-center gap-1" title="${escapeHtml(agent.codename || '')}">
                                <i class="fas fa-tag text-xs"></i>
                                v${escapeHtml(agent.version)}
                            </span>
                        ` : ''}
                        ${agent.code_hash ? `
                            <span class="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded font-mono" title="Commit: ${escapeHtml(agent.code_hash)}">
                                ${escapeHtml(agent.code_hash.substring(0, 7))}
                            </span>
                        ` : ''}
                    </div>
                    <div class="text-sm text-gray-600 space-y-1">
                        <div>ID: ${escapeHtml(agent.agent_id)}</div>
                        <div>Container: ${escapeHtml(agent.container_name)}</div>
                        <div>Port: ${agent.api_port || agent.port}</div>
                        ${agent.codename ? `<div>Codename: ${escapeHtml(agent.codename)}</div>` : ''}
                        ${agent.code_hash ? `<div class="font-mono text-xs">Hash: ${escapeHtml(agent.code_hash).substring(0, 8)}...</div>` : ''}
                        <div class="flex items-center gap-1">
                            <span class="inline-block w-2 h-2 bg-green-500 rounded-full"></span>
                            ${agent.status || 'running'}
                        </div>
                    </div>
                </div>
                <div>
                    <button onclick="openAgentUI('${agent.agent_id}')" class="px-3 py-1 text-blue-600 hover:bg-blue-50 rounded">
                        <i class="fas fa-book"></i> API Docs
                    </button>
                    <button onclick="showAgentSettings('${agent.agent_id}')" class="px-3 py-1 text-purple-600 hover:bg-purple-50 rounded">
                        <i class="fas fa-cog"></i> Settings
                    </button>
                    <button onclick="showOAuthSetup('${agent.agent_id}')" class="px-3 py-1 text-indigo-600 hover:bg-indigo-50 rounded">
                        <i class="fas fa-key"></i> OAuth
                    </button>
                    <button onclick="restartAgent('${agent.agent_id}')" class="px-3 py-1 text-orange-600 hover:bg-orange-50 rounded">
                        <i class="fas fa-sync-alt"></i> Restart
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
    
    // Fetch and display version summary
    fetchVersionSummary();
}

// Fetch version summary for agents
async function fetchVersionSummary() {
    try {
        const response = await fetch('/manager/v1/agents/versions', { credentials: 'include' });
        if (!response.ok) return;
        
        const data = await response.json();
        
        // Add version summary to status tab
        const statusContent = document.getElementById('status-content');
        let versionSummaryDiv = document.getElementById('version-summary');
        
        if (!versionSummaryDiv) {
            versionSummaryDiv = document.createElement('div');
            versionSummaryDiv.id = 'version-summary';
            versionSummaryDiv.className = 'mt-6';
            statusContent.appendChild(versionSummaryDiv);
        }
        
        versionSummaryDiv.innerHTML = `
            <h3 class="text-lg font-semibold mb-2">Agent Versions</h3>
            <div class="bg-gray-50 p-4 rounded-lg">
                <div class="mb-3">
                    <strong>Total Agents:</strong> ${data.total_agents}
                </div>
                <div>
                    <strong>Version Distribution:</strong>
                    <ul class="list-disc list-inside mt-2">
                        ${Object.entries(data.version_summary || {}).map(([version, count]) =>
                            `<li>${version}: ${count} agent${count !== 1 ? 's' : ''}</li>`
                        ).join('')}
                    </ul>
                </div>
                ${data.agents && data.agents.length > 0 ? `
                    <div class="mt-4">
                        <strong>Agent Details:</strong>
                        <div class="mt-2 space-y-1">
                            ${data.agents.map(agent => `
                                <div class="text-sm">
                                    <span class="font-medium">${escapeHtml(agent.agent_name)}:</span>
                                    <span class="text-gray-600">v${escapeHtml(agent.version)}</span>
                                    ${agent.codename !== 'unknown' ? `<span class="text-gray-500">(${escapeHtml(agent.codename)})</span>` : ''}
                                </div>
                            `).join('')}
                        </div>
                    </div>
                ` : ''}
            </div>
        `;
    } catch (error) {
        console.error('Failed to fetch version summary:', error);
    }
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

// Check if template needs approval and load template defaults
async function checkTemplateApproval() {
    const template = document.getElementById('template-select').value;
    const waField = document.getElementById('wa-signature-field');
    const waReviewSection = document.getElementById('wa-review-section');
    const waReviewCheckbox = document.getElementById('wa-review-checkbox');

    if (templates && template) {
        const isPreApproved = templates.pre_approved?.includes(template);
        if (isPreApproved) {
            waField.classList.add('hidden');
        } else {
            waField.classList.remove('hidden');
        }

        // Fetch template details to check stewardship tier
        try {
            const response = await fetch(`/manager/v1/templates/${template}/details`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('managerToken')}` }
            });
            
            if (response.ok) {
                const details = await response.json();
                
                // Show WA review checkbox for Tier 4/5 agents
                if (details.stewardship_tier >= 4) {
                    waReviewSection.classList.remove('hidden');
                    // Update the message to show the tier
                    const message = waReviewSection.querySelector('.text-amber-700');
                    if (message) {
                        message.textContent = `I confirm that this Tier ${details.stewardship_tier} agent has been reviewed and approved by the WA team.`;
                    }
                } else {
                    waReviewSection.classList.add('hidden');
                    waReviewCheckbox.checked = false;
                }
            }
        } catch (error) {
            console.error('Failed to fetch template details:', error);
            // Hide on error
            waReviewSection.classList.add('hidden');
            waReviewCheckbox.checked = false;
        }

        // Load template default environment variables
        await loadTemplateDefaults(template);
    }
}

// Load environment variables from .env or .txt file
async function loadEnvFromFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.env,.txt,text/plain';
    
    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        try {
            console.log('Loading file:', file.name);
            const text = await file.text();
            console.log('File content length:', text.length);
            
            const env = parseEnvFile(text);
            console.log('Parsed environment variables:', env);
            
            // Check if we got any variables
            if (Object.keys(env).length === 0) {
                showError('No valid environment variables found in file');
                return;
            }
            
            // Clear existing env vars
            const container = document.getElementById('env-vars-container');
            if (!container) {
                console.error('Container env-vars-container not found');
                showError('Failed to find environment variables container');
                return;
            }
            container.innerHTML = '';
            
            // Add each env var
            let count = 0;
            for (const [key, value] of Object.entries(env)) {
                addEnvVarRow(key, value);
                count++;
            }
            
            showSuccess(`Loaded ${count} environment variables from ${file.name}`);
        } catch (error) {
            console.error('Error loading file:', error);
            showError('Failed to load environment file: ' + error.message);
        }
    };
    
    input.click();
}

// Parse .env file content
function parseEnvFile(content) {
    const env = {};
    const lines = content.split('\n');
    
    for (let line of lines) {
        // Trim the line
        line = line.trim();
        
        // Skip comments and empty lines
        if (!line || line.startsWith('#')) continue;
        
        // Check if line contains an equals sign
        const equalsIndex = line.indexOf('=');
        if (equalsIndex > 0) {
            const key = line.substring(0, equalsIndex).trim();
            let value = line.substring(equalsIndex + 1).trim();
            
            // Remove quotes if present
            if ((value.startsWith('"') && value.endsWith('"')) ||
                (value.startsWith("'") && value.endsWith("'"))) {
                value = value.slice(1, -1);
            }
            
            env[key] = value;
        }
    }
    
    return env;
}

// Add environment variable row in create dialog
function addEnvVarRow(key = '', value = '') {
    const container = document.getElementById('env-vars-container');
    const row = document.createElement('div');
    row.className = 'flex gap-2';
    row.innerHTML = `
        <input type="text" placeholder="Key" value="${escapeHtml(key)}" 
               class="flex-1 p-2 border rounded-lg env-key">
        <input type="text" placeholder="Value" value="${escapeHtml(value)}" 
               class="flex-1 p-2 border rounded-lg env-value">
        <button type="button" onclick="this.parentElement.remove()" 
                class="px-3 py-2 text-red-600 hover:bg-red-50 rounded-lg">
            <i class="fas fa-times"></i>
        </button>
    `;
    container.appendChild(row);
}

// Load template default environment variables
async function loadTemplateDefaults(templateName) {
    // Clear existing env vars
    const container = document.getElementById('env-vars-container');
    container.innerHTML = '';

    try {
        // Fetch default environment variables from the API
        const response = await fetch('/manager/v1/env/default', {
            credentials: 'include'
        });
        
        if (response.ok) {
            const data = await response.json();
            const env = parseEnvFile(data.content);
            
            // Add template-specific overrides
            env['CIRIS_AGENT_NAME'] = templateName;
            if (templateName === 'test') {
                env['CIRIS_MOCK_LLM'] = 'true';
            }
            
            // Add each env var
            for (const [key, value] of Object.entries(env)) {
                addEnvVarRow(key, value);
            }
            return;
        }
    } catch (error) {
        console.error('Failed to fetch default env vars:', error);
    }
    
    // Fallback to minimal defaults if API fails
    const fallbackDefaults = {
        'OPENAI_API_KEY': '',
        'CIRIS_AGENT_NAME': templateName,
        'CIRIS_API_PORT': '8080',
        'DISCORD_BOT_TOKEN': '',
        'DISCORD_CHANNEL_IDS': '',
        'OAUTH_CALLBACK_BASE_URL': 'https://agents.ciris.ai'
    };
    
    if (templateName === 'test') {
        fallbackDefaults['CIRIS_MOCK_LLM'] = 'true';
    }

    // Add env var rows with defaults
    Object.entries(fallbackDefaults).forEach(([key, value]) => {
        const newRow = document.createElement('div');
        newRow.className = 'flex gap-2';
        newRow.innerHTML = `
            <input type="text" placeholder="Key" value="${key}" class="flex-1 p-2 border rounded-lg env-key">
            <input type="text" placeholder="Value" value="${value}" class="flex-1 p-2 border rounded-lg env-value">
            <button type="button" onclick="this.parentElement.remove()" class="px-3 py-2 bg-red-100 rounded-lg hover:bg-red-200">
                <i class="fas fa-trash"></i>
            </button>
        `;
        container.appendChild(newRow);
    });
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
    const waReviewSection = document.getElementById('wa-review-section');
    const waReviewCheckbox = document.getElementById('wa-review-checkbox');
    
    // Check if WA review is required (section is visible) but not completed
    if (!waReviewSection.classList.contains('hidden') && !waReviewCheckbox.checked) {
        showError('WA review confirmation is required for Tier 4/5 agents');
        return;
    }
    
    const data = {
        template: formData.get('template'),
        name: formData.get('name'),
        environment: {},
        wa_signature: formData.get('wa_signature') || undefined,
        use_mock_llm: formData.get('use_mock_llm') === 'on',
        enable_discord: formData.get('enable_discord') === 'on',
        wa_review_completed: formData.get('wa_review_completed') === 'on'
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

// Restart agent
async function restartAgent(agentId) {
    if (!confirm(`Are you sure you want to restart agent ${agentId}? The agent will be temporarily unavailable.`)) {
        return;
    }

    try {
        // Show loading state
        showSuccess(`Restarting agent ${agentId}...`);
        
        const response = await fetch(`/manager/v1/agents/${agentId}/restart`, {
            method: 'POST',
            credentials: 'include'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to restart agent');
        }

        const result = await response.json();
        showSuccess(result.message || `Agent ${agentId} is restarting`);
        
        // Wait a moment then refresh the list to show updated status
        setTimeout(async () => {
            await refreshData();
        }, 3000);
    } catch (error) {
        showError('Failed to restart agent: ' + error.message);
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

// Open agent API documentation
function openAgentUI(agentId) {
    window.open(`/api/${agentId}/docs`, '_blank');
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
    // Render latest versions with semantic version parsing
    const latestVersions = data.latest_versions || {};
    const agentImageEl = document.getElementById('current-agent-image');
    const guiImageEl = document.getElementById('current-gui-image');
    
    // Display parsed versions with semantic version and hash
    if (latestVersions.agent_image) {
        agentImageEl.innerHTML = formatVersionDisplay(latestVersions.agent_image);
    } else {
        agentImageEl.textContent = 'Unknown';
    }
    
    if (latestVersions.gui_image) {
        guiImageEl.innerHTML = formatVersionDisplay(latestVersions.gui_image);
    } else {
        guiImageEl.textContent = 'Unknown';
    }

    // Extract digests from version data (if available)
    document.getElementById('current-agent-digest').textContent = 'N/A';
    document.getElementById('current-gui-digest').textContent = 'N/A';

    // Render deployment status
    const deploymentStatus = document.getElementById('deployment-status');
    if (data.current_deployment) {
        const deployment = data.current_deployment;
        
        // Calculate progress percentage
        const progressPercent = deployment.agents_total > 0 
            ? Math.round((deployment.agents_updated / deployment.agents_total) * 100)
            : 0;
        
        // Format start time
        const startTime = new Date(deployment.started_at);
        const timeAgo = getTimeAgo(startTime);
        
        // Determine status color and icon
        let statusColor = 'text-gray-600';
        let statusBg = 'bg-gray-100';
        let statusIcon = 'fa-circle';
        
        if (deployment.status === 'in_progress') {
            statusColor = 'text-yellow-600';
            statusBg = 'bg-yellow-100';
            statusIcon = 'fa-spinner fa-spin';
        } else if (deployment.status === 'completed') {
            statusColor = 'text-green-600';
            statusBg = 'bg-green-100';
            statusIcon = 'fa-check-circle';
        } else if (deployment.status === 'failed') {
            statusColor = 'text-red-600';
            statusBg = 'bg-red-100';
            statusIcon = 'fa-exclamation-circle';
        }
        
        deploymentStatus.innerHTML = `
            <div class="space-y-3">
                <!-- Status Header -->
                <div class="flex items-center justify-between">
                    <div class="flex items-center gap-2">
                        <i class="fas ${statusIcon} ${statusColor}"></i>
                        <span class="font-semibold text-lg capitalize">${escapeHtml(deployment.status.replace('_', ' '))}</span>
                        ${deployment.canary_phase ? `
                            <span class="px-2 py-1 text-xs ${statusBg} ${statusColor} rounded-full">
                                ${escapeHtml(deployment.canary_phase)} phase
                            </span>
                        ` : ''}
                    </div>
                    <span class="text-sm text-gray-500">${timeAgo}</span>
                </div>
                
                <!-- Progress Bar -->
                <div>
                    <div class="flex justify-between text-sm mb-1">
                        <span class="font-medium">Progress</span>
                        <span>${deployment.agents_updated} of ${deployment.agents_total} agents (${progressPercent}%)</span>
                    </div>
                    <div class="w-full bg-gray-200 rounded-full h-2">
                        <div class="h-2 rounded-full transition-all duration-500 ${
                            deployment.status === 'failed' ? 'bg-red-500' :
                            deployment.status === 'completed' ? 'bg-green-500' :
                            'bg-blue-500'
                        }" style="width: ${progressPercent}%"></div>
                    </div>
                </div>
                
                <!-- Details -->
                <div class="space-y-2 text-sm">
                    ${deployment.message ? `
                        <div>
                            <span class="font-medium">Message:</span>
                            <span class="ml-2">${escapeHtml(deployment.message)}</span>
                        </div>
                    ` : ''}
                    
                    ${deployment.agents_failed > 0 ? `
                        <div class="flex items-center gap-2 text-red-600">
                            <i class="fas fa-exclamation-triangle"></i>
                            <span>${deployment.agents_failed} agent(s) failed to update</span>
                        </div>
                    ` : ''}
                    
                    ${deployment.agents_deferred > 0 ? `
                        <div class="flex items-center gap-2 text-yellow-600">
                            <i class="fas fa-clock"></i>
                            <span>${deployment.agents_deferred} agent(s) deferred update</span>
                        </div>
                    ` : ''}
                    
                    <!-- Deployment ID (shortened) -->
                    <div class="text-xs text-gray-500">
                        <span>ID: ${escapeHtml(deployment.deployment_id.substring(0, 8))}...</span>
                    </div>
                </div>
            </div>
        `;
    } else {
        deploymentStatus.innerHTML = `
            <div class="text-center py-4">
                <i class="fas fa-check-circle text-3xl text-gray-300 mb-2"></i>
                <p class="text-gray-600">No active deployment</p>
                <p class="text-xs text-gray-500 mt-1">All systems operational</p>
            </div>
        `;
    }

    // Render deployment history
    const deploymentHistory = document.getElementById('deployment-history');
    if (data.recent_deployments && data.recent_deployments.length > 0) {
        deploymentHistory.innerHTML = `
            <div class="space-y-2">
                ${data.recent_deployments.map(deployment => {
                    const startTime = new Date(deployment.started_at);
                    const endTime = deployment.completed_at ? new Date(deployment.completed_at) : null;
                    const duration = endTime ? Math.round((endTime - startTime) / 1000) : null;
                    
                    // Determine status icon and color
                    let statusIcon = 'fa-check-circle';
                    let statusColor = 'text-green-600';
                    if (deployment.status === 'failed') {
                        statusIcon = 'fa-exclamation-circle';
                        statusColor = 'text-red-600';
                    } else if (deployment.status === 'cancelled') {
                        statusIcon = 'fa-times-circle';
                        statusColor = 'text-gray-600';
                    }
                    
                    return `
                        <div class="border-l-4 ${
                            deployment.status === 'completed' ? 'border-green-500' :
                            deployment.status === 'failed' ? 'border-red-500' :
                            'border-gray-500'
                        } pl-3 py-2">
                            <div class="flex items-start justify-between">
                                <div class="flex-1">
                                    <div class="flex items-center gap-2">
                                        <i class="fas ${statusIcon} ${statusColor} text-sm"></i>
                                        <span class="text-sm font-medium">
                                            ${deployment.agents_updated} of ${deployment.agents_total} agents notified
                                        </span>
                                    </div>
                                    <div class="text-xs text-gray-600 mt-1">
                                        <span class="font-mono">${escapeHtml(deployment.deployment_id.substring(0, 8))}</span>
                                        ${deployment.message ? ` • ${escapeHtml(deployment.message)}` : ''}
                                    </div>
                                </div>
                                <div class="text-right text-xs text-gray-500">
                                    <div>${formatRelativeDate(startTime)}</div>
                                    ${duration ? `<div>${formatDuration(duration)}</div>` : ''}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    } else {
        deploymentHistory.innerHTML = `
            <div class="text-center text-gray-500">
                <i class="fas fa-history text-2xl mb-2"></i>
                <p>No recent deployments</p>
            </div>
        `;
    }

    // Render agent version table and cards
    const tableBody = document.getElementById('agent-versions-table');
    const cardsContainer = document.getElementById('agent-versions-cards');
    
    if (data.agent_versions && data.agent_versions.length > 0) {
        // Desktop table view
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
                        ${formatVersionDisplay(agent.current_agent_image)}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        ${formatVersionDisplay(agent.current_gui_image)}
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
        
        // Mobile card view
        if (cardsContainer) {
            cardsContainer.innerHTML = data.agent_versions.map(agent => {
                const isUpToDate = (
                    agent.current_agent_image === latestVersions.agent_image &&
                    agent.current_gui_image === latestVersions.gui_image
                );
                
                return `
                    <div class="bg-white border rounded-lg p-4 space-y-3">
                        <div class="flex justify-between items-start">
                            <h4 class="font-semibold text-gray-900">${escapeHtml(agent.agent_name)}</h4>
                            <span class="px-2 py-1 text-xs font-semibold rounded-full ${
                                agent.status === 'running' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                            }">
                                ${escapeHtml(agent.status)}
                            </span>
                        </div>
                        <div class="space-y-2 text-sm">
                            <div>
                                <span class="text-gray-500">Agent:</span>
                                <div class="ml-2">${formatVersionDisplay(agent.current_agent_image)}</div>
                            </div>
                            <div>
                                <span class="text-gray-500">GUI:</span>
                                <div class="ml-2">${formatVersionDisplay(agent.current_gui_image)}</div>
                            </div>
                            <div class="flex justify-between items-center pt-2 border-t">
                                <span class="text-xs text-gray-500">
                                    ${agent.last_updated === 'never' ? 'Never updated' : 'Updated ' + formatDate(agent.last_updated)}
                                </span>
                                ${isUpToDate ?
                                    '<span class="text-green-600"><i class="fas fa-check-circle"></i></span>' :
                                    '<span class="text-yellow-600"><i class="fas fa-exclamation-circle"></i></span>'
                                }
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        }
    } else {
        tableBody.innerHTML = `
            <tr>
                <td colspan="5" class="px-6 py-4 text-center text-gray-500">
                    No agent version data available
                </td>
            </tr>
        `;
        if (cardsContainer) {
            cardsContainer.innerHTML = `
                <div class="text-center text-gray-500 py-8">
                    No agent version data available
                </div>
            `;
        }
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

// Parse image tag to extract version info
function parseImageTag(imageTag) {
    if (!imageTag || imageTag === 'unknown') {
        return { tag: 'unknown', version: null, hash: null };
    }
    
    // Parse format: ghcr.io/cirisai/ciris-agent:v1.2.3-abc123
    // or ghcr.io/cirisai/ciris-agent:latest
    // or ghcr.io/cirisai/ciris-agent@sha256:...
    
    const parts = imageTag.split(':');
    if (parts.length < 2) {
        return { tag: imageTag, version: null, hash: null };
    }
    
    const tag = parts[parts.length - 1];
    
    // Check for semantic version pattern (v1.2.3 or 1.2.3)
    const semverMatch = tag.match(/^v?(\d+\.\d+\.\d+)(?:-([a-f0-9]+))?/);
    if (semverMatch) {
        return {
            tag: tag,
            version: 'v' + semverMatch[1],
            hash: semverMatch[2] || null
        };
    }
    
    // Check for commit hash pattern
    const hashMatch = tag.match(/^([a-f0-9]{7,40})/);
    if (hashMatch) {
        return {
            tag: tag,
            version: null,
            hash: hashMatch[1].substring(0, 7)
        };
    }
    
    // Default: just return the tag
    return { tag: tag, version: null, hash: null };
}

// Format version display with semantic version and hash
function formatVersionDisplay(imageTag) {
    const parsed = parseImageTag(imageTag);
    
    if (parsed.version && parsed.hash) {
        // Both version and hash: "v1.2.3 (abc123)"
        return `<span class="font-semibold">${escapeHtml(parsed.version)}</span> <span class="text-gray-500 text-xs">(${escapeHtml(parsed.hash)})</span>`;
    } else if (parsed.version) {
        // Just version: "v1.2.3"
        return `<span class="font-semibold">${escapeHtml(parsed.version)}</span>`;
    } else if (parsed.hash) {
        // Just hash: "abc123"
        return `<span class="font-mono text-xs">${escapeHtml(parsed.hash)}</span>`;
    } else if (parsed.tag === 'latest') {
        // Latest tag
        return '<span class="text-blue-600 font-medium">latest</span>';
    } else {
        // Unknown format
        return `<span class="text-gray-500 text-xs">${escapeHtml(parsed.tag)}</span>`;
    }
}

// Format date
function formatDate(dateString) {
    if (!dateString || dateString === 'never') return 'Unknown';
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return 'Unknown';
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
            // Redirect to main login page
            window.location.href = '/';
        } else {
            console.error('Logout failed:', response.status);
            showError('Failed to logout. Please try again.');
        }
    } catch (error) {
        console.error('Logout error:', error);
        showError('Failed to logout. Please try again.');
    }
}

// Show error message
function showError(message) {
    const alert = document.getElementById('error-alert');
    const messageElement = document.getElementById('error-message');
    messageElement.textContent = message;
    alert.classList.remove('hidden');
    // Auto-hide after 5 seconds
    setTimeout(() => hideError(), 5000);
}

// Hide error message
function hideError() {
    document.getElementById('error-alert').classList.add('hidden');
}

// Show success message
function showSuccess(message) {
    // For now, just log to console since we don't have a success alert in the HTML
    console.log('Success:', message);
    // Could also show a temporary notification
    const notification = document.createElement('div');
    notification.className = 'fixed top-4 right-4 bg-green-500 text-white px-4 py-2 rounded shadow-lg z-50';
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => notification.remove(), 3000);
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

// Helper function to get time ago string
function getTimeAgo(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
    return `${Math.floor(seconds / 86400)} days ago`;
}

// Helper function to format date object for relative display
function formatRelativeDate(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffHours = Math.floor(diffMs / (1000 * 60 * 60));
    
    if (diffHours < 24) {
        // Today - show time
        return date.toLocaleTimeString('en-US', { 
            hour: '2-digit', 
            minute: '2-digit'
        });
    } else if (diffHours < 48) {
        // Yesterday
        return 'Yesterday ' + date.toLocaleTimeString('en-US', { 
            hour: '2-digit', 
            minute: '2-digit'
        });
    } else {
        // Older - show date
        return date.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }
}

// Helper function to format duration
function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) {
        const mins = Math.floor(seconds / 60);
        const secs = seconds % 60;
        return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
    }
    const hours = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

// OAuth Modal Functions
function showOAuthModal(agentId) {
    // Update agent ID in modal
    document.getElementById('oauth-agent-id').textContent = agentId;

    // Update callback URLs with actual agent ID
    const baseUrl = `${window.location.origin}/v1/auth/oauth`;
    document.getElementById('google-callback-url').value = `${baseUrl}/${agentId}/google/callback`;
    document.getElementById('github-callback-url').value = `${baseUrl}/${agentId}/github/callback`;
    document.getElementById('discord-callback-url').value = `${baseUrl}/${agentId}/discord/callback`;

    // Update agent ID in env var example
    const agentIdExample = document.getElementById('agent-id-example');
    if (agentIdExample) {
        agentIdExample.textContent = agentId;
    }

    // Show modal
    document.getElementById('oauth-setup-modal').classList.remove('hidden');
}

function hideOAuthModal() {
    document.getElementById('oauth-setup-modal').classList.add('hidden');
}

// Show OAuth setup for a specific agent
function showOAuthSetup(agentId) {
    showOAuthModal(agentId);
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
async function notifyEric(event) {
    const agentId = document.getElementById('oauth-agent-id').textContent;
    const button = event.currentTarget;
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
async function verifyOAuth(event) {
    const agentId = document.getElementById('oauth-agent-id').textContent;
    const button = event.currentTarget;
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

// Show agent settings modal
async function showAgentSettings(agentId) {
    const modal = document.getElementById('agent-settings-modal');
    const agentIdSpan = document.getElementById('settings-agent-id');
    const mockLlmCheckbox = document.getElementById('settings-mock-llm');
    const discordCheckbox = document.getElementById('settings-discord');
    const discordSection = document.getElementById('discord-config-section');
    
    // Set agent ID in modal
    agentIdSpan.textContent = agentId;
    agentIdSpan.dataset.agentId = agentId;
    
    // Clear previous environment variables
    const envVarsContainer = document.getElementById('env-vars-settings');
    envVarsContainer.innerHTML = '';
    
    try {
        // Get current agent configuration from docker-compose
        const response = await fetch(`/manager/v1/agents/${agentId}/config`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('managerToken')}` }
        });
        
        if (response.ok) {
            const config = await response.json();
            
            // Set quick settings
            mockLlmCheckbox.checked = config.environment?.CIRIS_MOCK_LLM !== 'false';
            const adapters = config.environment?.CIRIS_ADAPTER || 'api';
            discordCheckbox.checked = adapters.includes('discord');
            
            // Show/hide Discord section
            if (discordCheckbox.checked) {
                discordSection.classList.remove('hidden');
            } else {
                discordSection.classList.add('hidden');
            }
            
            // Populate Discord settings
            if (config.environment) {
                document.getElementById('discord-bot-token').value = config.environment.DISCORD_BOT_TOKEN || '';
                document.getElementById('discord-channel-ids').value = config.environment.DISCORD_CHANNEL_IDS || '';
                document.getElementById('discord-deferral-channel').value = config.environment.DISCORD_DEFERRAL_CHANNEL_ID || '';
                document.getElementById('wa-user-ids').value = config.environment.WA_USER_IDS || config.environment.WA_USER_ID || '';
                document.getElementById('openai-api-key').value = config.environment.OPENAI_API_KEY || '';
                document.getElementById('llm-provider').value = config.environment.LLM_PROVIDER || 'openai';
                
                // Populate all environment variables
                for (const [key, value] of Object.entries(config.environment)) {
                    // Skip ones we handle specially
                    if (['CIRIS_MOCK_LLM', 'CIRIS_ADAPTER', 'DISCORD_BOT_TOKEN', 'DISCORD_CHANNEL_IDS', 
                         'DISCORD_DEFERRAL_CHANNEL_ID', 'WA_USER_IDS', 'WA_USER_ID', 
                         'OPENAI_API_KEY', 'LLM_PROVIDER'].includes(key)) {
                        continue;
                    }
                    addSettingsEnvVarRow(key, value);
                }
            }
        }
    } catch (error) {
        console.error('Failed to load agent config:', error);
        // Fall back to basic info from agents list
        const agent = agents.find(a => a.agent_id === agentId);
        if (agent) {
            mockLlmCheckbox.checked = agent.mock_llm === true;
            discordCheckbox.checked = agent.discord_enabled === true;
        }
    }
    
    // Add change listener to Discord checkbox
    discordCheckbox.onchange = function() {
        if (this.checked) {
            discordSection.classList.remove('hidden');
        } else {
            discordSection.classList.add('hidden');
        }
    };
    
    // Show modal
    modal.classList.remove('hidden');
}

// Hide agent settings modal
function hideAgentSettingsModal() {
    const modal = document.getElementById('agent-settings-modal');
    modal.classList.add('hidden');
}

// Add environment variable row to settings modal
function addSettingsEnvVarRow(key = '', value = '') {
    const container = document.getElementById('env-vars-settings');
    const row = document.createElement('div');
    row.className = 'flex gap-2';
    row.innerHTML = `
        <input type="text" placeholder="Key" value="${escapeHtml(key)}" 
               class="flex-1 p-2 border rounded text-sm env-settings-key">
        <input type="text" placeholder="Value" value="${escapeHtml(value)}" 
               class="flex-1 p-2 border rounded text-sm env-settings-value">
        <button type="button" onclick="this.parentElement.remove()" 
                class="px-2 py-1 text-red-600 hover:bg-red-50 rounded">
            <i class="fas fa-times"></i>
        </button>
    `;
    container.appendChild(row);
}

// Add new environment variable in settings
function addSettingsEnvVar() {
    addSettingsEnvVarRow();
}

// Load environment variables from file into settings modal
async function loadSettingsEnvFromFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.env,.txt,text/plain';
    
    input.onchange = async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        
        try {
            console.log('Loading file for settings:', file.name);
            const text = await file.text();
            const env = parseEnvFile(text);
            console.log('Parsed environment variables for settings:', env);
            
            // Check if we got any variables
            if (Object.keys(env).length === 0) {
                showError('No valid environment variables found in file');
                return;
            }
            
            // Clear existing env vars in settings
            const container = document.getElementById('env-vars-settings');
            if (!container) {
                console.error('Container env-vars-settings not found');
                showError('Failed to find settings environment variables container');
                return;
            }
            container.innerHTML = '';
            
            // Add each env var to settings
            let count = 0;
            for (const [key, value] of Object.entries(env)) {
                addSettingsEnvVarRow(key, value);
                count++;
            }
            
            showSuccess(`Loaded ${count} environment variables from ${file.name}`);
        } catch (error) {
            console.error('Error loading file for settings:', error);
            showError('Failed to load environment file: ' + error.message);
        }
    };
    
    input.click();
}

// Save agent settings
async function saveAgentSettings(event) {
    event.preventDefault();
    
    const agentId = document.getElementById('settings-agent-id').dataset.agentId;
    const mockLlm = document.getElementById('settings-mock-llm').checked;
    const discordAdapter = document.getElementById('settings-discord').checked;
    
    try {
        // Prepare configuration update
        const configUpdate = {
            environment: {}
        };
        
        // Quick settings
        configUpdate.environment.CIRIS_MOCK_LLM = mockLlm ? 'true' : 'false';
        configUpdate.environment.CIRIS_ENABLE_DISCORD = discordAdapter ? 'true' : 'false';
        
        // Discord configuration (if enabled)
        if (discordAdapter) {
            const botToken = document.getElementById('discord-bot-token').value;
            const channelIds = document.getElementById('discord-channel-ids').value;
            const deferralChannel = document.getElementById('discord-deferral-channel').value;
            const waUserIds = document.getElementById('wa-user-ids').value;
            
            if (botToken) configUpdate.environment.DISCORD_BOT_TOKEN = botToken;
            if (channelIds) {
                // Clean up channel IDs (handle newlines and commas)
                const cleanedIds = channelIds.replace(/\n/g, ',').replace(/\s+/g, '');
                configUpdate.environment.DISCORD_CHANNEL_IDS = cleanedIds;
            }
            if (deferralChannel) configUpdate.environment.DISCORD_DEFERRAL_CHANNEL_ID = deferralChannel;
            if (waUserIds) {
                // Clean up WA user IDs  
                const cleanedWaIds = waUserIds.replace(/\n/g, ',').replace(/\s+/g, '');
                configUpdate.environment.WA_USER_IDS = cleanedWaIds;
            }
        }
        
        // API configuration
        const openaiKey = document.getElementById('openai-api-key').value;
        const llmProvider = document.getElementById('llm-provider').value;
        if (openaiKey) configUpdate.environment.OPENAI_API_KEY = openaiKey;
        if (llmProvider) configUpdate.environment.LLM_PROVIDER = llmProvider;
        
        // All other environment variables
        const envKeys = document.querySelectorAll('.env-settings-key');
        const envValues = document.querySelectorAll('.env-settings-value');
        
        envKeys.forEach((key, index) => {
            if (key.value && envValues[index]) {
                configUpdate.environment[key.value] = envValues[index].value;
            }
        });
        
        // Send PATCH request to update agent configuration
        const response = await fetch(`/manager/v1/agents/${agentId}/config`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify(configUpdate)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update agent configuration');
        }
        
        const result = await response.json();
        
        // Hide modal
        hideAgentSettingsModal();
        
        // Show success message
        alert(`Agent ${agentId} configuration updated successfully. The container is being restarted.`);
        
        // Refresh agent list
        await fetchData();
        
    } catch (error) {
        console.error('Failed to save agent settings:', error);
        alert('Failed to save agent settings: ' + error.message);
    }
}
