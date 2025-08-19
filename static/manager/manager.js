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

    container.innerHTML = agents.map(agent => {
        // Determine cognitive state badge
        let cognitiveStateBadge = '';
        if (agent.cognitive_state) {
            const stateColors = {
                'WAKEUP': 'bg-yellow-100 text-yellow-700',
                'WORK': 'bg-green-100 text-green-700',
                'SHUTDOWN': 'bg-red-100 text-red-700',
                'SLEEP': 'bg-gray-100 text-gray-700',
                'ERROR': 'bg-red-100 text-red-700'
            };
            const color = stateColors[agent.cognitive_state] || 'bg-gray-100 text-gray-700';
            cognitiveStateBadge = `
                <span class="px-2 py-1 ${color} text-sm rounded" title="Cognitive State">
                    <i class="fas fa-brain text-xs"></i>
                    ${escapeHtml(agent.cognitive_state)}
                </span>
            `;
        }

        return `
        <div class="border rounded-lg p-4 hover:bg-gray-50 transition-colors">
            <div class="flex items-start justify-between">
                <div class="space-y-1">
                    <div class="flex items-center gap-2">
                        <i class="fas fa-server text-gray-600"></i>
                        <h3 class="font-semibold">${escapeHtml(agent.name || agent.agent_name)}</h3>
                        <span class="px-2 py-1 bg-gray-100 text-gray-700 text-sm rounded">
                            ${escapeHtml(agent.template)}
                        </span>
                        ${agent.deployment ? `
                            <span class="px-2 py-1 bg-purple-100 text-purple-700 text-sm rounded" title="Deployment">
                                <i class="fas fa-layer-group text-xs"></i>
                                ${escapeHtml(agent.deployment)}
                            </span>
                        ` : ''}
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
                        ${cognitiveStateBadge}
                    </div>
                    <div class="text-sm text-gray-600 space-y-1">
                        <div>ID: ${escapeHtml(agent.agent_id)}</div>
                        <div>Container: ${escapeHtml(agent.container_name)}</div>
                        <div>Port: ${agent.api_port || agent.port}</div>
                        ${agent.deployment ? `<div>Deployment: ${escapeHtml(agent.deployment)}</div>` : ''}
                        ${agent.codename ? `<div>Codename: ${escapeHtml(agent.codename)}</div>` : ''}
                        ${agent.code_hash ? `<div class="font-mono text-xs">Hash: ${escapeHtml(agent.code_hash).substring(0, 8)}...</div>` : ''}
                        <div class="flex items-center gap-1">
                            <span class="inline-block w-2 h-2 ${agent.status === 'running' ? 'bg-green-500' : 'bg-gray-400'} rounded-full"></span>
                            ${agent.status || 'unknown'}
                        </div>
                    </div>
                </div>
                <div class="space-y-2">
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
                        <button onclick="showDeployVersion('${agent.agent_id}')" class="px-3 py-1 text-amber-600 hover:bg-amber-50 rounded" title="Change release version for this agent">
                            <i class="fas fa-code-branch"></i> Change Release
                        </button>
                    </div>
                    <div>
                        ${agent.status === 'running' ? `
                            <button onclick="requestStopAgent('${agent.agent_id}')" class="px-3 py-1 text-yellow-600 hover:bg-yellow-50 rounded">
                                <i class="fas fa-hand-paper"></i> Request Stop
                            </button>
                            <button onclick="forceStopAgent('${agent.agent_id}')" class="px-3 py-1 text-red-600 hover:bg-red-50 rounded">
                                <i class="fas fa-stop"></i> Force Stop
                            </button>
                        ` : `
                            <button onclick="startAgent('${agent.agent_id}')" class="px-3 py-1 text-green-600 hover:bg-green-50 rounded">
                                <i class="fas fa-play"></i> Start
                            </button>
                        `}
                        <button onclick="deleteAgent('${agent.agent_id}')" class="px-3 py-1 text-red-600 hover:bg-red-50 rounded">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
            </div>
        </div>
        `;
    }).join('');
}

// Render manager status
function renderStatus() {
    const container = document.getElementById('manager-status');

    if (!managerStatus) {
        container.innerHTML = '<div class="text-gray-500">Loading...</div>';
        return;
    }

    // Format uptime
    let uptimeStr = 'N/A';
    if (managerStatus.uptime_seconds) {
        const days = Math.floor(managerStatus.uptime_seconds / 86400);
        const hours = Math.floor((managerStatus.uptime_seconds % 86400) / 3600);
        const minutes = Math.floor((managerStatus.uptime_seconds % 3600) / 60);
        
        if (days > 0) {
            uptimeStr = `${days}d ${hours}h ${minutes}m`;
        } else if (hours > 0) {
            uptimeStr = `${hours}h ${minutes}m`;
        } else {
            uptimeStr = `${minutes}m`;
        }
    }

    // Format start time
    let startTimeStr = 'N/A';
    if (managerStatus.start_time) {
        const startDate = new Date(managerStatus.start_time);
        startTimeStr = startDate.toLocaleString();
    }

    // Status badge color
    const statusColor = managerStatus.status === 'running' ? 'green' : 'red';

    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="space-y-3">
                <div class="flex items-center gap-2">
                    <strong>Status:</strong> 
                    <span class="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-${statusColor}-100 text-${statusColor}-800">
                        ${managerStatus.status}
                    </span>
                </div>
                <div><strong>Version:</strong> ${managerStatus.version || '2.2.0'}</div>
                <div><strong>Auth Mode:</strong> ${managerStatus.auth_mode || 'production'}</div>
                <div><strong>Uptime:</strong> ${uptimeStr}</div>
                <div><strong>Started:</strong> ${startTimeStr}</div>
            </div>
            <div>
                <div class="mb-2"><strong>Components:</strong></div>
                <div class="space-y-1">
                    ${Object.entries(managerStatus.components || {}).map(([key, value]) => {
                        const isRunning = value === 'running' || value === 'enabled';
                        const icon = isRunning ? '✅' : '❌';
                        const color = isRunning ? 'text-green-600' : 'text-red-600';
                        return `
                            <div class="flex items-center gap-2">
                                <span class="${color}">${icon}</span>
                                <span class="capitalize">${key.replace('_', ' ')}:</span>
                                <span class="text-gray-600">${value}</span>
                            </div>
                        `;
                    }).join('')}
                </div>
            </div>
        </div>
    `;
    
    // Display system health metrics if available
    if (managerStatus.system_metrics) {
        renderSystemHealth(managerStatus.system_metrics);
    }
    
    // Fetch and display version summary
    fetchVersionSummary();
}

// Render system health metrics
function renderSystemHealth(metrics) {
    const container = document.getElementById('system-health');
    if (!container) return;
    
    const cpuColor = metrics.cpu_percent > 80 ? 'red' : metrics.cpu_percent > 50 ? 'yellow' : 'green';
    const memColor = metrics.memory_percent > 80 ? 'red' : metrics.memory_percent > 50 ? 'yellow' : 'green';
    const diskColor = metrics.disk_percent > 80 ? 'red' : metrics.disk_percent > 50 ? 'yellow' : 'green';
    
    container.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="bg-white p-3 rounded border border-gray-200">
                <div class="flex justify-between items-center mb-2">
                    <span class="text-sm font-medium">CPU Usage</span>
                    <span class="text-sm font-bold text-${cpuColor}-600">${metrics.cpu_percent?.toFixed(1) || 'N/A'}%</span>
                </div>
                <div class="w-full bg-gray-200 rounded-full h-2">
                    <div class="bg-${cpuColor}-500 h-2 rounded-full" style="width: ${metrics.cpu_percent || 0}%"></div>
                </div>
            </div>
            
            <div class="bg-white p-3 rounded border border-gray-200">
                <div class="flex justify-between items-center mb-2">
                    <span class="text-sm font-medium">Memory Usage</span>
                    <span class="text-sm font-bold text-${memColor}-600">${metrics.memory_percent?.toFixed(1) || 'N/A'}%</span>
                </div>
                <div class="w-full bg-gray-200 rounded-full h-2">
                    <div class="bg-${memColor}-500 h-2 rounded-full" style="width: ${metrics.memory_percent || 0}%"></div>
                </div>
            </div>
            
            <div class="bg-white p-3 rounded border border-gray-200">
                <div class="flex justify-between items-center mb-2">
                    <span class="text-sm font-medium">Disk Usage</span>
                    <span class="text-sm font-bold text-${diskColor}-600">${metrics.disk_percent?.toFixed(1) || 'N/A'}%</span>
                </div>
                <div class="w-full bg-gray-200 rounded-full h-2">
                    <div class="bg-${diskColor}-500 h-2 rounded-full" style="width: ${metrics.disk_percent || 0}%"></div>
                </div>
            </div>
        </div>
        
        ${metrics.load_average ? `
            <div class="mt-4 p-3 bg-white rounded border border-gray-200">
                <div class="text-sm font-medium mb-1">Load Average</div>
                <div class="flex gap-4 text-sm">
                    <span>1 min: <strong>${metrics.load_average[0]?.toFixed(2)}</strong></span>
                    <span>5 min: <strong>${metrics.load_average[1]?.toFixed(2)}</strong></span>
                    <span>15 min: <strong>${metrics.load_average[2]?.toFixed(2)}</strong></span>
                </div>
            </div>
        ` : ''}
    `;
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
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                    <div class="bg-white p-3 rounded border border-gray-200">
                        <div class="text-2xl font-bold text-blue-600">${data.total_agents}</div>
                        <div class="text-sm text-gray-600">Total Agents</div>
                    </div>
                    <div class="bg-white p-3 rounded border border-gray-200">
                        <div class="text-2xl font-bold text-green-600">${Object.keys(data.version_summary || {}).length}</div>
                        <div class="text-sm text-gray-600">Unique Versions</div>
                    </div>
                </div>
                
                <div class="mb-4">
                    <strong class="block mb-2">Version Distribution:</strong>
                    <div class="space-y-2">
                        ${Object.entries(data.version_summary || {}).map(([version, count]) => {
                            const percentage = ((count / data.total_agents) * 100).toFixed(1);
                            return `
                                <div class="flex items-center gap-2">
                                    <div class="flex-1">
                                        <div class="flex justify-between mb-1">
                                            <span class="text-sm font-medium">${version}</span>
                                            <span class="text-sm text-gray-600">${count} agent${count !== 1 ? 's' : ''} (${percentage}%)</span>
                                        </div>
                                        <div class="w-full bg-gray-200 rounded-full h-2">
                                            <div class="bg-blue-600 h-2 rounded-full" style="width: ${percentage}%"></div>
                                        </div>
                                    </div>
                                </div>
                            `;
                        }).join('')}
                    </div>
                </div>
                
                ${data.agents && data.agents.length > 0 ? `
                    <div class="border-t pt-4">
                        <strong class="block mb-2">Agent Details:</strong>
                        <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                            ${data.agents.map(agent => `
                                <div class="flex items-center gap-2 p-2 bg-white rounded border border-gray-100">
                                    <div class="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                                        <span class="text-xs font-bold text-blue-600">${agent.agent_name.charAt(0).toUpperCase()}</span>
                                    </div>
                                    <div class="flex-1">
                                        <div class="font-medium text-sm">${escapeHtml(agent.agent_name)}</div>
                                        <div class="text-xs text-gray-600">
                                            v${escapeHtml(agent.version)}
                                            ${agent.codename !== 'unknown' ? `<span class="text-gray-500">(${escapeHtml(agent.codename)})</span>` : ''}
                                        </div>
                                    </div>
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

    // Fetch version/deployment data when switching to versions tab
    if (tab === 'versions') {
        updateDeploymentTab();
    }
    
    // Fetch canary data when switching to canary tab
    if (tab === 'canary') {
        fetchCanaryData();
    }
    
    // Dashboard has been moved to external CIRISLens service
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

// Start a stopped agent
async function startAgent(agentId) {
    try {
        const response = await fetch(`/manager/v1/agents/${agentId}/start`, {
            method: 'POST',
            credentials: 'same-origin'
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to start agent');
        }

        showNotification(`Agent ${agentId} is starting...`, 'success');
        
        // Refresh agents list after a short delay
        setTimeout(() => {
            fetchData();
        }, 2000);
    } catch (error) {
        console.error('Error starting agent:', error);
        showNotification(error.message || 'Failed to start agent', 'error');
    }
}

// Request stop with reason
async function requestStopAgent(agentId) {
    const reason = prompt(`Please provide a reason for stopping agent ${agentId}:`);
    if (!reason) {
        return;
    }
    
    try {
        const response = await fetch(`/manager/v1/agents/${agentId}/shutdown`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify({ reason: reason })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to request stop');
        }

        showNotification(`Stop requested for agent ${agentId}: ${reason}`, 'success');
        
        // Refresh agents list after a short delay
        setTimeout(() => {
            fetchData();
        }, 3000);
    } catch (error) {
        console.error('Error requesting stop:', error);
        showNotification(error.message || 'Failed to request agent stop', 'error');
    }
}

// Force stop (immediate)
async function forceStopAgent(agentId) {
    if (!confirm(`Are you sure you want to force stop agent ${agentId}? This will immediately terminate the agent.`)) {
        return;
    }
    
    try {
        const response = await fetch(`/manager/v1/agents/${agentId}/stop`, {
            method: 'POST',
            credentials: 'same-origin'
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.detail || 'Failed to stop agent');
        }

        showNotification(`Agent ${agentId} is being force stopped...`, 'warning');
        
        // Refresh agents list after a short delay
        setTimeout(() => {
            fetchData();
        }, 2000);
    } catch (error) {
        console.error('Error force stopping agent:', error);
        showNotification(error.message || 'Failed to force stop agent', 'error');
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

// Fetch canary group data
async function fetchCanaryData() {
    try {
        const response = await fetch('/manager/v1/canary/groups', {
            credentials: 'include'
        });

        if (!response.ok) throw new Error(`Failed to fetch canary data: ${response.status}`);

        const data = await response.json();
        renderCanaryData(data);
    } catch (error) {
        showError('Failed to fetch canary data: ' + error.message);
    }
}

// Render canary group data
function renderCanaryData(data) {
    const statsContainer = document.getElementById('canary-stats');
    const groupsContainer = document.getElementById('canary-groups');
    
    // Render stats cards
    const groupOrder = ['explorer', 'early_adopter', 'general', 'unassigned'];
    const groupConfig = {
        explorer: { icon: 'fa-rocket', color: 'purple', label: 'Explorers', description: 'First to receive updates' },
        early_adopter: { icon: 'fa-bolt', color: 'blue', label: 'Early Adopters', description: 'Second wave deployment' },
        general: { icon: 'fa-users', color: 'green', label: 'General', description: 'Stable production rollout' },
        unassigned: { icon: 'fa-question-circle', color: 'gray', label: 'Unassigned', description: 'Not in canary program' }
    };
    
    statsContainer.innerHTML = groupOrder.map(group => {
        const stats = data.stats[group];
        const config = groupConfig[group];
        
        return `
            <div class="bg-white rounded-lg border p-4">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                        <i class="fas ${config.icon} text-${config.color}-600"></i>
                        <h4 class="font-semibold">${config.label}</h4>
                    </div>
                    <span class="text-2xl font-bold">${stats.count}</span>
                </div>
                <p class="text-xs text-gray-500 mb-2">${config.description}</p>
                <div class="flex justify-between text-xs">
                    <span>Target: ${stats.target_percentage}%</span>
                    <span>Actual: ${stats.actual_percentage}%</span>
                </div>
                <div class="mt-2 bg-gray-200 rounded-full h-2">
                    <div class="bg-${config.color}-500 h-2 rounded-full" style="width: ${stats.actual_percentage}%"></div>
                </div>
            </div>
        `;
    }).join('');
    
    // Render group assignments
    groupsContainer.innerHTML = groupOrder.map(group => {
        const agents = data.groups[group];
        const config = groupConfig[group];
        
        if (agents.length === 0 && group === 'unassigned') {
            return ''; // Don't show unassigned if empty
        }
        
        return `
            <div class="bg-white rounded-lg border">
                <div class="p-4 border-b bg-${config.color}-50">
                    <div class="flex items-center justify-between">
                        <div class="flex items-center gap-2">
                            <i class="fas ${config.icon} text-${config.color}-600"></i>
                            <h4 class="font-semibold">${config.label}</h4>
                            <span class="px-2 py-1 bg-${config.color}-100 text-${config.color}-700 text-xs rounded-full">
                                ${agents.length} agent${agents.length !== 1 ? 's' : ''}
                            </span>
                        </div>
                    </div>
                </div>
                <div class="p-4">
                    ${agents.length > 0 ? `
                        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                            ${agents.map(agent => `
                                <div class="border rounded-lg p-3 hover:bg-gray-50">
                                    <div class="flex items-center justify-between mb-2">
                                        <span class="font-medium">${escapeHtml(agent.agent_name)}</span>
                                        <span class="px-2 py-1 text-xs rounded-full ${
                                            agent.status === 'running' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'
                                        }">
                                            ${escapeHtml(agent.status)}
                                        </span>
                                    </div>
                                    <div class="text-xs text-gray-600 space-y-1">
                                        <div>Version: v${escapeHtml(agent.version)} 
                                            ${agent.code_hash !== 'unknown' ? `(${escapeHtml(agent.code_hash.substring(0, 7))})` : ''}
                                        </div>
                                        <div>Updated: ${agent.last_updated === 'never' ? 'Never' : getTimeAgo(new Date(agent.last_updated))}</div>
                                    </div>
                                    <div class="mt-2 flex gap-1">
                                        <button onclick="moveAgent('${escapeHtml(agent.agent_id)}', 'explorer')" 
                                                class="px-2 py-1 text-xs bg-purple-100 text-purple-700 rounded hover:bg-purple-200"
                                                ${group === 'explorer' ? 'disabled style="opacity: 0.5"' : ''}>
                                            <i class="fas fa-rocket"></i>
                                        </button>
                                        <button onclick="moveAgent('${escapeHtml(agent.agent_id)}', 'early_adopter')" 
                                                class="px-2 py-1 text-xs bg-blue-100 text-blue-700 rounded hover:bg-blue-200"
                                                ${group === 'early_adopter' ? 'disabled style="opacity: 0.5"' : ''}>
                                            <i class="fas fa-bolt"></i>
                                        </button>
                                        <button onclick="moveAgent('${escapeHtml(agent.agent_id)}', 'general')" 
                                                class="px-2 py-1 text-xs bg-green-100 text-green-700 rounded hover:bg-green-200"
                                                ${group === 'general' ? 'disabled style="opacity: 0.5"' : ''}>
                                            <i class="fas fa-users"></i>
                                        </button>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    ` : `
                        <p class="text-gray-500 text-center py-4">No agents in this group</p>
                    `}
                </div>
            </div>
        `;
    }).filter(html => html !== '').join('');
}

// Move agent to a different canary group
async function moveAgent(agentId, group) {
    try {
        const response = await fetch(`/manager/v1/canary/agent/${agentId}/group`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'include',
            body: JSON.stringify({ group })
        });
        
        if (!response.ok) throw new Error(`Failed to update agent group: ${response.status}`);
        
        // Refresh canary data
        fetchCanaryData();
    } catch (error) {
        showError('Failed to update agent group: ' + error.message);
    }
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
                
                <!-- Action Buttons for Failed Deployments -->
                ${deployment.status === 'failed' ? `
                    <div class="flex gap-2 pt-3 border-t">
                        <button onclick="cancelDeployment('${deployment.deployment_id}')" 
                                class="px-3 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-700 transition-colors">
                            <i class="fas fa-times mr-1"></i>Clear & Reset
                        </button>
                        <button onclick="triggerNewDeployment()" 
                                class="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 transition-colors">
                            <i class="fas fa-redo mr-1"></i>Retry Deployment
                        </button>
                    </div>
                ` : ''}
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
                        ${agent.version && agent.version !== 'unknown' ? `
                            <div class="flex items-center gap-2">
                                <span class="font-medium">v${escapeHtml(agent.version)}</span>
                                ${agent.code_hash && agent.code_hash !== 'unknown' ? 
                                    `<span class="text-xs font-mono text-gray-400">(${escapeHtml(agent.code_hash.substring(0, 7))})</span>` : 
                                    ''
                                }
                            </div>
                        ` : formatVersionDisplay(agent.current_agent_image)}
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
                                <div class="ml-2">
                                    ${agent.version && agent.version !== 'unknown' ? `
                                        <span class="font-medium">v${escapeHtml(agent.version)}</span>
                                        ${agent.code_hash && agent.code_hash !== 'unknown' ? 
                                            `<span class="text-xs font-mono text-gray-400 ml-1">(${escapeHtml(agent.code_hash.substring(0, 7))})</span>` : 
                                            ''
                                        }
                                    ` : formatVersionDisplay(agent.current_agent_image)}
                                </div>
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

// Show shutdown reasons modal
async function showShutdownReasons(deploymentId) {
    try {
        const response = await fetch(`/manager/v1/updates/shutdown-reasons/${deploymentId}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}`
            }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to get shutdown reasons: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Create modal
        const modal = document.createElement('div');
        modal.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';
        modal.onclick = (e) => {
            if (e.target === modal) modal.remove();
        };
        
        const content = document.createElement('div');
        content.className = 'bg-white rounded-lg shadow-xl max-w-4xl max-h-[80vh] overflow-hidden';
        
        content.innerHTML = `
            <div class="p-6 border-b">
                <h2 class="text-2xl font-bold text-gray-800">Agent Shutdown Messages</h2>
                <p class="text-sm text-gray-600 mt-2">
                    Messages that will be sent to agents when they are notified to shutdown for update
                </p>
                <p class="text-xs text-yellow-600 mt-2">
                    ${data.note || ''}
                </p>
            </div>
            <div class="p-6 overflow-y-auto max-h-[60vh]">
                <div class="space-y-4">
                    <div class="bg-blue-50 p-4 rounded-lg">
                        <h3 class="font-semibold text-blue-800 mb-2">🚀 Explorers (First Group)</h3>
                        <code class="block bg-white p-3 rounded border border-blue-200 text-sm whitespace-pre-wrap break-all">
${data.shutdown_reasons.explorers}
                        </code>
                        <p class="text-xs text-blue-600 mt-2">
                            ℹ️ First group receives no peer information
                        </p>
                    </div>
                    
                    <div class="bg-green-50 p-4 rounded-lg">
                        <h3 class="font-semibold text-green-800 mb-2">🌟 Early Adopters</h3>
                        <code class="block bg-white p-3 rounded border border-green-200 text-sm whitespace-pre-wrap break-all">
${data.shutdown_reasons.early_adopters}
                        </code>
                        <p class="text-xs text-green-600 mt-2">
                            ℹ️ Receives explorer results if explorers exist
                        </p>
                    </div>
                    
                    <div class="bg-purple-50 p-4 rounded-lg">
                        <h3 class="font-semibold text-purple-800 mb-2">👥 General Population</h3>
                        <code class="block bg-white p-3 rounded border border-purple-200 text-sm whitespace-pre-wrap break-all">
${data.shutdown_reasons.general}
                        </code>
                        <p class="text-xs text-purple-600 mt-2">
                            ℹ️ Receives results from all prior groups
                        </p>
                    </div>
                </div>
            </div>
            <div class="p-6 border-t bg-gray-50">
                <button onclick="this.closest('.fixed').remove()" 
                        class="px-4 py-2 bg-gray-600 text-white rounded hover:bg-gray-700">
                    Close
                </button>
            </div>
        `;
        
        modal.appendChild(content);
        document.body.appendChild(modal);
        
    } catch (error) {
        console.error('Error fetching shutdown reasons:', error);
        alert(`Failed to get shutdown reasons: ${error.message}`);
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

// Show loading indicator
function showLoading() {
    const loading = document.getElementById('loading');
    const app = document.getElementById('app');
    if (loading) loading.classList.remove('hidden');
    if (app) app.classList.add('hidden');
}

// Hide loading indicator
function hideLoading() {
    const loading = document.getElementById('loading');
    const app = document.getElementById('app');
    if (loading) loading.classList.add('hidden');
    if (app) app.classList.remove('hidden');
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

// Single Agent Deployment Functions
async function showDeployVersion(agentId) {
    console.log('showDeployVersion called for agent:', agentId);
    
    const modal = document.getElementById('single-deploy-modal');
    const agentSpan = document.getElementById('deploy-agent-id');
    const versionSelect = document.getElementById('deploy-version');
    
    agentSpan.textContent = agentId;
    
    // Load available versions
    versionSelect.innerHTML = '<option value="">Loading versions...</option>';
    console.log('Starting to fetch versions...');
    
    try {
        // Fetch available versions from the registry or API
        const versions = await fetchAvailableVersions();
        console.log('Successfully fetched versions:', versions);
        
        // Populate the dropdown
        versionSelect.innerHTML = '';
        
        // Add latest option first
        const latestOption = document.createElement('option');
        latestOption.value = 'latest';
        latestOption.textContent = 'latest (newest available)';
        versionSelect.appendChild(latestOption);
        
        // Add separator if we have versions
        if (versions.length > 0) {
            const separator = document.createElement('option');
            separator.disabled = true;
            separator.textContent = '──────────────';
            versionSelect.appendChild(separator);
            
            // Add specific versions
            versions.forEach(version => {
                const option = document.createElement('option');
                option.value = version.tag;
                // Show both semantic version and short hash
                const shortHash = version.hash ? version.hash.substring(0, 7) : '';
                option.textContent = `${version.tag}${shortHash ? ' (' + shortHash + ')' : ''}`;
                versionSelect.appendChild(option);
            });
        }
        
        // Select latest by default
        versionSelect.value = 'latest';
        console.log('Version dropdown populated successfully');
        
    } catch (error) {
        console.error('VERSION FETCH FAILED:', error);
        console.error('Error stack:', error.stack);
        
        // Show error prominently
        versionSelect.innerHTML = `<option value="" disabled selected>ERROR: ${error.message}</option>`;
        versionSelect.style.backgroundColor = '#fee';
        versionSelect.style.color = '#c00';
        
        // Show alert to user
        alert(`CHANGE RELEASE UNAVAILABLE\n\n${error.message}\n\nPlease ensure you are logged in and try again.`);
        
        // Close the modal since we can't proceed
        closeSingleDeployModal();
        return;
    }
    
    // Set default deployment message
    document.getElementById('deploy-message').value = 'Routine maintenance update';
    
    // Set consensual deployment as default
    document.getElementById('deploy-strategy').value = 'manual';
    
    modal.classList.remove('hidden');
}

function closeSingleDeployModal() {
    const modal = document.getElementById('single-deploy-modal');
    modal.classList.add('hidden');
    
    // Reset form
    document.getElementById('single-deploy-form').reset();
}

// Fetch available versions from registry
async function fetchAvailableVersions() {
    // No try-catch - let errors propagate for proper handling
    const response = await fetch('/manager/v1/agents/versions', {
        credentials: 'include'
    });
    
    if (!response.ok) {
        if (response.status === 401) {
            throw new Error('AUTHENTICATION REQUIRED: You must be logged in to deploy versions');
        }
        throw new Error(`FAILED TO FETCH VERSIONS: ${response.status} ${response.statusText}`);
    }
    
    const data = await response.json();
    const versions = [];
    
    // Only show REAL versions from the API response
    if (data.agent && data.agent.current) {
        const tag = data.agent.current.tag || data.agent.current.image?.split(':').pop();
        if (tag && tag !== 'latest') {
            versions.push({
                tag: tag,
                hash: data.agent.current.digest?.substring(0, 12) || ''
            });
        }
    }
    
    // Add previous versions if available
    if (data.agent && data.agent.n_minus_1) {
        const tag = data.agent.n_minus_1.tag || data.agent.n_minus_1.image?.split(':').pop();
        if (tag && tag !== 'latest') {
            versions.push({
                tag: tag,
                hash: data.agent.n_minus_1.digest?.substring(0, 12) || ''
            });
        }
    }
    
    if (data.agent && data.agent.n_minus_2) {
        const tag = data.agent.n_minus_2.tag || data.agent.n_minus_2.image?.split(':').pop();
        if (tag && tag !== 'latest') {
            versions.push({
                tag: tag,
                hash: data.agent.n_minus_2.digest?.substring(0, 12) || ''
            });
        }
    }
    
    // If no versions found, return empty array (UI will show latest only)
    console.log('Version history extracted:', versions);
    
    return versions;
}


// Update strategy info based on selection
function updateStrategyInfo() {
    const strategy = document.getElementById('deploy-strategy').value;
    const infoDiv = document.getElementById('strategy-info');
    const icon = document.getElementById('strategy-icon');
    const title = document.getElementById('strategy-title');
    const description = document.getElementById('strategy-description');
    
    switch(strategy) {
        case 'manual':
            infoDiv.className = 'bg-blue-50 border border-blue-200 rounded-lg p-4';
            icon.className = 'fas fa-info-circle text-blue-600 mt-1';
            title.className = 'text-sm font-medium text-blue-900';
            title.textContent = 'Consensual Deployment';
            description.className = 'text-xs text-blue-700 mt-1';
            description.textContent = 'This deployment respects agent autonomy. The agent will review the update and decide when to apply it based on its current state and policies.';
            break;
            
        case 'immediate':
            infoDiv.className = 'bg-amber-50 border border-amber-200 rounded-lg p-4';
            icon.className = 'fas fa-exclamation-triangle text-amber-600 mt-1';
            title.className = 'text-sm font-medium text-amber-900';
            title.textContent = 'API Forced Shutdown';
            description.className = 'text-xs text-amber-700 mt-1';
            description.textContent = 'Sends a forced shutdown request via the agent API. The agent will attempt to shut down immediately, but may still perform cleanup tasks.';
            break;
            
        case 'docker':
            infoDiv.className = 'bg-red-50 border border-red-200 rounded-lg p-4';
            icon.className = 'fas fa-exclamation-circle text-red-600 mt-1';
            title.className = 'text-sm font-medium text-red-900';
            title.textContent = 'Manager Forced Restart';
            description.className = 'text-xs text-red-700 mt-1';
            description.textContent = 'Forcibly restarts the Docker container, bypassing the agent entirely. Use only when the agent is unresponsive or in emergency situations.';
            break;
    }
}

// Close single agent deployment modal
function closeSingleDeployModal() {
    const modal = document.getElementById('single-deploy-modal');
    modal.classList.add('hidden');
    
    // Reset form but keep defaults
    document.getElementById('single-deploy-form').reset();
    document.getElementById('deploy-message').value = 'Routine maintenance update';
    document.getElementById('deploy-strategy').value = 'manual';
    updateStrategyInfo(); // Reset info display
}

async function deploySingleAgent(event) {
    event.preventDefault();
    
    const form = event.target;
    const agentId = document.getElementById('deploy-agent-id').textContent;
    const version = form.version.value.trim();
    const message = form.message.value.trim() || 'Routine maintenance update';
    const strategy = form.strategy.value;
    
    // Construct the full image name
    const agentImage = version === 'latest' 
        ? 'ghcr.io/cirisai/ciris-agent:latest'
        : `ghcr.io/cirisai/ciris-agent:${version.startsWith('v') ? version.substring(1) : version}`;
    
    try {
        showLoading();
        
        const response = await fetch('/manager/v1/updates/deploy-single', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
                agent_id: agentId,
                agent_image: agentImage,
                message: message,
                strategy: strategy,
                metadata: {
                    test_deployment: true,
                    source: 'manager_ui'
                }
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to start deployment');
        }
        
        const result = await response.json();
        
        showSuccess(`Deployment ${result.deployment_id} started for ${agentId}`);
        closeSingleDeployModal();
        
        // Show deployment progress notification
        showDeploymentProgress(result);
        
    } catch (error) {
        showError(`Deployment failed: ${error.message}`);
    } finally {
        hideLoading();
    }
}

function showDeploymentProgress(deployment) {
    // Create a notification showing deployment progress
    const notification = document.createElement('div');
    notification.className = 'fixed bottom-4 right-4 bg-white border border-amber-200 rounded-lg shadow-lg p-4 max-w-md';
    notification.innerHTML = `
        <div class="flex items-start gap-3">
            <div class="animate-spin">
                <i class="fas fa-circle-notch text-amber-600"></i>
            </div>
            <div class="flex-1">
                <h4 class="font-semibold text-sm">Deployment in Progress</h4>
                <p class="text-xs text-gray-600 mt-1">
                    Deploying to ${deployment.agent_id}
                </p>
                <p class="text-xs text-gray-500 mt-1">
                    ID: ${deployment.deployment_id}
                </p>
            </div>
            <button onclick="this.parentElement.parentElement.remove()" class="text-gray-400 hover:text-gray-600">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `;
    document.body.appendChild(notification);
    
    // Auto-remove after 10 seconds
    setTimeout(() => notification.remove(), 10000);
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

// Cancel a failed deployment to clear the lock
async function cancelDeployment(deploymentId) {
    console.log('cancelDeployment called with ID:', deploymentId);
    
    if (!deploymentId) {
        console.error('ERROR: cancelDeployment called without deployment ID');
        throw new Error('Deployment ID is required to cancel a deployment');
    }
    
    if (!confirm('Clear this failed deployment and prepare it for retry? The deployment will be re-staged and ready to launch.')) {
        console.log('User cancelled the clear operation');
        return;
    }
    
    try {
        console.log('Sending cancel request for deployment:', deploymentId);
        const response = await fetch('/manager/v1/updates/cancel', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}`
            },
            body: JSON.stringify({
                deployment_id: deploymentId,
                reason: 'Clearing failed deployment to allow retry'
            })
        });
        
        console.log('Cancel response status:', response.status);
        
        if (response.ok) {
            const result = await response.json();
            console.log('Deployment successfully cancelled:', result);
            alert('Failed deployment cleared! The deployment has been re-staged and is ready to launch. Check the "Pending Deployment" section.');
            await updateDeploymentTab();
        } else {
            const error = await response.json();
            console.error('ERROR: Failed to cancel deployment:', error);
            alert(error.detail || 'Failed to cancel deployment');
            throw new Error(`Failed to cancel deployment: ${error.detail || response.status}`);
        }
    } catch (error) {
        console.error('ERROR: Exception while cancelling deployment:', error);
        alert('Failed to cancel deployment: ' + error.message);
        throw error; // Re-throw to make failures visible
    }
}

// Trigger a new deployment (retry)
async function triggerNewDeployment() {
    console.log('triggerNewDeployment called');
    
    // First, check if there's a failed deployment blocking us
    try {
        const checkResponse = await fetch('/manager/v1/updates/pending', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        if (checkResponse.ok) {
            const data = await checkResponse.json();
            console.log('Current deployment state:', data);
            
            if (data.pending && data.status === 'failed') {
                console.error('ERROR: Failed deployment is blocking. Must clear it first.');
                alert('Please clear the failed deployment first using the "Clear Failed Deployment" button');
                return;
            }
        }
    } catch (error) {
        console.error('ERROR: Could not check deployment state:', error);
    }
    
    if (!confirm('Retry the deployment? This will trigger a new deployment with the latest images.')) {
        console.log('User cancelled deployment retry');
        return;
    }
    
    console.log('NOTE: Manual CD trigger required - no automatic webhook implemented yet');
    alert('To retry deployment, the CD pipeline needs to be triggered again. You can also manually trigger from GitHub Actions.');
    
    // TODO: Implement actual deployment trigger
    // This would require an endpoint like /manager/v1/updates/trigger
    // that either webhooks to GitHub Actions or directly starts a deployment
    console.warn('WARNING: triggerNewDeployment does not actually trigger anything yet - manual CD trigger required');
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

// Dashboard Functions

// Staged Deployment Management Functions
async function checkPendingDeployment() {
    console.log('Checking for pending deployments...');
    try {
        // ONLY use the all endpoint - no fallbacks
        const response = await fetch('/manager/v1/updates/pending/all', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        if (!response.ok) {
            throw new Error(`Failed to check pending deployments: ${response.status}`);
        }
        
        const data = await response.json();
        console.log('All pending deployments:', data);
        
        // Show the deployments (handles 0, 1, or many)
        showPendingDeployments(data);
        
    } catch (error) {
        console.error('Error checking pending deployments:', error);
        // Hide the section on error
        const section = document.getElementById('pending-deployment-section');
        if (section) {
            section.style.display = 'none';
        }
    }
}

// This is the OLD function for backwards compat only - should be removed
async function checkPendingDeploymentOLD() {
    try {
        const response = await fetch('/manager/v1/updates/pending', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        console.log('Pending deployment response status:', response.status);
        
        if (!response.ok) {
            throw new Error(`Failed to check pending deployment: ${response.status}`);
        }
        
        const data = await response.json();
        console.log('Pending deployment data:', data);
        
        if (data.pending) {
            // Check if it's a failed deployment that needs clearing
            if (data.status === 'failed') {
                console.log('Showing FAILED deployment:', data);
                showFailedDeployment(data);
            } else if (data.status === 'pending' || !data.status) {
                console.log('Showing PENDING deployment:', data);
                showPendingDeployment(data);
            } else {
                console.error('INVALID DEPLOYMENT STATUS:', data.status, 'Full data:', data);
                throw new Error(`Invalid deployment status: ${data.status}. Expected 'pending' or 'failed'`);
            }
        } else {
            console.log('No pending deployment');
            hidePendingDeployment();
        }
    } catch (error) {
        console.error('Error checking pending deployment:', error);
        hidePendingDeployment();
    }
}

// NEW: Single function to show all pending deployments
function showPendingDeployments(data) {
    const section = document.getElementById('pending-deployment-section');
    if (!section) {
        throw new Error('pending-deployment-section element not found');
    }
    
    // No deployments - hide section
    if (data.total_pending === 0) {
        section.style.display = 'none';
        return;
    }
    
    // Clear existing content
    section.innerHTML = '';
    section.style.display = 'block';
    
    // Show latest tag info if available
    if (data.latest_tag && Object.keys(data.latest_tag).length > 0) {
        const latestInfo = document.createElement('div');
        latestInfo.className = 'bg-gray-100 p-4 rounded-lg mb-4';
        latestInfo.innerHTML = `
            <h3 class="text-lg font-semibold mb-2">Current 'latest' Tag Status</h3>
            <div class="grid grid-cols-2 gap-2 text-sm">
                ${data.latest_tag.local_image_id ? `<div><span class="font-medium">Local Image:</span> ${data.latest_tag.local_image_id}</div>` : ''}
                ${data.latest_tag.running_version ? `<div><span class="font-medium">Running Version:</span> ${data.latest_tag.running_version}</div>` : ''}
            </div>
        `;
        section.appendChild(latestInfo);
    }
    
    // Show each deployment
    data.deployments.forEach((deployment, index) => {
        const deploymentDiv = document.createElement('div');
        deploymentDiv.className = `bg-white p-6 rounded-lg shadow-md ${index > 0 ? 'mt-4' : ''}`;
        deploymentDiv.innerHTML = `
            <div class="flex justify-between items-start mb-4">
                <h3 class="text-xl font-semibold text-blue-600">
                    ${index === 0 ? '🚀 Latest Staged Deployment' : `📦 Staged Deployment #${index + 1}`}
                </h3>
                <span class="text-sm text-gray-500">${formatDate(deployment.staged_at)}</span>
            </div>
            
            <div class="grid grid-cols-2 gap-4 mb-4">
                <div>
                    <p class="text-sm text-gray-600">Deployment ID</p>
                    <p class="font-mono text-xs">${deployment.deployment_id}</p>
                </div>
                <div>
                    <p class="text-sm text-gray-600">Version</p>
                    <p class="font-semibold ${deployment.version && deployment.version.includes('.') ? 'text-green-600' : 'text-yellow-600'}">
                        ${deployment.version || 'No semantic version'}
                    </p>
                </div>
                <div>
                    <p class="text-sm text-gray-600">Strategy</p>
                    <p class="font-medium">${deployment.strategy || 'canary'}</p>
                </div>
                <div>
                    <p class="text-sm text-gray-600">Affected Agents</p>
                    <p class="font-medium">${deployment.affected_agents || 0}</p>
                </div>
            </div>
            
            <div class="mb-4">
                <p class="text-sm text-gray-600">Message</p>
                <p class="text-gray-800">${deployment.message || 'No message provided'}</p>
            </div>
            
            <div class="flex gap-2">
                <button onclick="executeDeploymentAction('launch', '${deployment.deployment_id}')" 
                        class="px-4 py-2 bg-green-600 text-white rounded hover:bg-green-700">
                    🚀 Launch
                </button>
                <button onclick="fetchDeploymentPreview('${deployment.deployment_id}')" 
                        class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700">
                    👁️ Preview
                </button>
                <button onclick="showShutdownReasons('${deployment.deployment_id}')" 
                        class="px-4 py-2 bg-purple-600 text-white rounded hover:bg-purple-700">
                    💬 Agent Messages
                </button>
                <button onclick="executeDeploymentAction('reject', '${deployment.deployment_id}')" 
                        class="px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700">
                    ❌ Reject
                </button>
            </div>
        `;
        section.appendChild(deploymentDiv);
    });
}

// OLD function - kept for compatibility but should be removed
function showPendingDeployment(deploymentData) {
    // FAIL FAST: Only handle pending deployments
    if (deploymentData.status && deploymentData.status !== 'pending') {
        console.error('ERROR: showPendingDeployment called with non-pending status:', deploymentData.status);
        throw new Error(`showPendingDeployment called with status '${deploymentData.status}' - only 'pending' is allowed`);
    }
    
    const section = document.getElementById('pending-deployment-section');
    if (!section) {
        console.error('ERROR: pending-deployment-section not found in DOM');
        throw new Error('pending-deployment-section element not found');
    }
    
    // Populate deployment details
    document.getElementById('pending-agent-image').textContent = 
        deploymentData.agent_image || 'N/A';
    
    // Add version to agent image if available
    if (deploymentData.version) {
        const agentImageEl = document.getElementById('pending-agent-image');
        agentImageEl.innerHTML = `${deploymentData.agent_image || 'N/A'}<br><span class="text-blue-600 font-semibold">Version: ${deploymentData.version}</span>`;
    }
    
    document.getElementById('pending-gui-image').textContent = 
        deploymentData.gui_image || 'N/A';
    document.getElementById('pending-strategy').textContent = 
        deploymentData.strategy || 'canary';
    document.getElementById('pending-message').textContent = 
        deploymentData.message || 'No message provided';
    document.getElementById('pending-staged-at').textContent = 
        formatDate(deploymentData.staged_at);
    document.getElementById('affected-agents-count').textContent = 
        `${deploymentData.affected_agents || 0} agents will be updated`;
    
    // Fetch and show deployment preview
    if (deploymentData.deployment_id) {
        fetchDeploymentPreview(deploymentData.deployment_id);
    }
    
    // Show the section
    section.classList.remove('hidden');
    
    // Setup button handlers
    setupDeploymentButtons(deploymentData);
}

async function fetchDeploymentPreview(deploymentId) {
    try {
        const response = await fetch(`/manager/v1/updates/preview/${deploymentId}`, {
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('idToken')}`
            }
        });
        
        if (!response.ok) {
            console.error('Failed to fetch deployment preview:', response.status);
            return;
        }
        
        const preview = await response.json();
        displayDeploymentPreview(preview);
    } catch (error) {
        console.error('Error fetching deployment preview:', error);
    }
}

function displayDeploymentPreview(preview) {
    // Find or create preview container
    let previewContainer = document.getElementById('deployment-preview');
    if (!previewContainer) {
        // Create preview container after the affected agents count
        const affectedAgentsEl = document.getElementById('affected-agents-count');
        if (!affectedAgentsEl) return;
        
        previewContainer = document.createElement('div');
        previewContainer.id = 'deployment-preview';
        previewContainer.className = 'mt-4 p-3 bg-gray-50 rounded-lg';
        affectedAgentsEl.parentElement.parentElement.appendChild(previewContainer);
    }
    
    // Build preview HTML
    let html = '<h4 class="font-semibold mb-2 text-sm">Deployment Preview:</h4>';
    
    if (preview.error) {
        html += `<p class="text-red-600">${preview.error}</p>`;
    } else {
        // Summary
        html += `<div class="text-sm mb-2">
            <span class="font-medium">${preview.agents_to_update}</span> of 
            <span class="font-medium">${preview.total_agents}</span> agents need updates
        </div>`;
        
        // Agent details table
        if (preview.agent_details && preview.agent_details.length > 0) {
            html += '<div class="overflow-x-auto"><table class="min-w-full text-xs">';
            html += '<thead><tr class="border-b">';
            html += '<th class="text-left py-1">Agent</th>';
            html += '<th class="text-left py-1">Current Version</th>';
            html += '<th class="text-left py-1">Status</th>';
            html += '<th class="text-left py-1">Group</th>';
            html += '</tr></thead><tbody>';
            
            preview.agent_details.forEach(agent => {
                const statusClass = agent.needs_update ? 'text-orange-600' : 'text-green-600';
                const statusIcon = agent.needs_update ? '⚠️' : '✓';
                
                html += '<tr class="border-b">';
                html += `<td class="py-1 pr-2">${agent.agent_name}</td>`;
                html += `<td class="py-1 pr-2">${agent.current_version || 'unknown'}</td>`;
                html += `<td class="py-1 pr-2 ${statusClass}">${statusIcon} ${agent.status}</td>`;
                html += `<td class="py-1">${agent.canary_group || 'none'}</td>`;
                html += '</tr>';
            });
            
            html += '</tbody></table></div>';
        }
        
        // Show deployment order for agents that need updates
        const agentsToUpdate = preview.agent_details.filter(a => a.needs_update);
        if (agentsToUpdate.length > 0) {
            const explorers = agentsToUpdate.filter(a => a.canary_group === 'explorer');
            const earlyAdopters = agentsToUpdate.filter(a => a.canary_group === 'early_adopter');
            const general = agentsToUpdate.filter(a => !a.canary_group || a.canary_group === 'general');
            
            html += '<div class="mt-3 text-xs">';
            html += '<p class="font-semibold mb-1">Deployment Order:</p>';
            
            if (explorers.length > 0) {
                html += `<div class="ml-2">1. Explorers (${explorers.length}): ${explorers.map(a => a.agent_name).join(', ')}</div>`;
            }
            if (earlyAdopters.length > 0) {
                html += `<div class="ml-2">2. Early Adopters (${earlyAdopters.length}): ${earlyAdopters.map(a => a.agent_name).join(', ')}</div>`;
            }
            if (general.length > 0) {
                html += `<div class="ml-2">3. General (${general.length}): ${general.map(a => a.agent_name).join(', ')}</div>`;
            }
            
            html += '</div>';
        }
    }
    
    previewContainer.innerHTML = html;
}

function hidePendingDeployment() {
    const section = document.getElementById('pending-deployment-section');
    if (section) {
        section.classList.add('hidden');
    }
    
    // Also hide preview
    const preview = document.getElementById('deployment-preview');
    if (preview) {
        preview.remove();
    }
}

function showFailedDeployment(deploymentData) {
    // FAIL FAST: Only handle failed deployments
    if (deploymentData.status !== 'failed') {
        console.error('ERROR: showFailedDeployment called with non-failed status:', deploymentData.status);
        throw new Error(`showFailedDeployment called with status '${deploymentData.status}' - only 'failed' is allowed`);
    }
    
    const section = document.getElementById('pending-deployment-section');
    if (!section) {
        console.error('ERROR: pending-deployment-section not found in DOM');
        throw new Error('pending-deployment-section element not found');
    }
    
    // Update the section to show it's a failed deployment
    const titleEl = section.querySelector('h3');
    if (titleEl) {
        titleEl.innerHTML = '<i class="fas fa-exclamation-circle text-red-500 mr-2"></i>Failed Deployment Blocking New Deployments';
    }
    
    // Populate deployment details
    document.getElementById('pending-agent-image').textContent = 
        deploymentData.agent_image || 'N/A';
    
    // Add version to agent image if available
    if (deploymentData.version) {
        const agentImageEl = document.getElementById('pending-agent-image');
        agentImageEl.innerHTML = `${deploymentData.agent_image || 'N/A'}<br><span class="text-blue-600 font-semibold">Version: ${deploymentData.version}</span>`;
    }
    
    document.getElementById('pending-gui-image').textContent = 
        deploymentData.gui_image || 'N/A';
    document.getElementById('pending-strategy').textContent = 
        deploymentData.strategy || 'canary';
    document.getElementById('pending-message').textContent = 
        deploymentData.message || 'Deployment failed';
    document.getElementById('pending-staged-at').textContent = 
        formatDate(deploymentData.staged_at);
    document.getElementById('affected-agents-count').textContent = 
        `${deploymentData.affected_agents || 0} agents were targeted`;
    
    // Fetch and show deployment preview for failed deployments too
    if (deploymentData.deployment_id) {
        fetchDeploymentPreview(deploymentData.deployment_id);
    }
    
    // Hide launch/reject buttons and show clear/retry buttons
    // Look for the button container - it has classes "flex flex-wrap gap-2"
    const buttonsContainer = section.querySelector('.flex.flex-wrap.gap-2');
    if (buttonsContainer) {
        console.log('Replacing buttons for failed deployment');
        buttonsContainer.innerHTML = `
            <button onclick="cancelDeployment('${deploymentData.deployment_id}')" 
                    class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors">
                <i class="fas fa-redo mr-2"></i>Clear & Retry Deployment
            </button>
        `;
    } else {
        console.error('ERROR: Could not find button container to replace with failed deployment buttons');
        // Try to find the launch button and replace its parent container
        const launchBtn = document.getElementById('launch-deployment-btn');
        if (launchBtn && launchBtn.parentElement) {
            console.log('Found button container via launch button parent');
            launchBtn.parentElement.innerHTML = `
                <button onclick="cancelDeployment('${deploymentData.deployment_id}')" 
                        class="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors">
                    <i class="fas fa-redo mr-2"></i>Clear & Retry Deployment
                </button>
            `;
        } else {
            console.error('CRITICAL ERROR: Cannot find any button container in pending deployment section');
        }
    }
    
    // Show the section
    section.classList.remove('hidden');
}

function setupDeploymentButtons(deploymentData) {
    // Launch button
    const launchBtn = document.getElementById('launch-deployment-btn');
    if (launchBtn) {
        launchBtn.onclick = async () => {
            if (confirm('Are you sure you want to launch this deployment? This will begin the canary rollout process.')) {
                await executeDeploymentAction('launch', deploymentData.deployment_id);
            }
        };
    }
    
    // Reject button
    const rejectBtn = document.getElementById('reject-deployment-btn');
    if (rejectBtn) {
        rejectBtn.onclick = async () => {
            if (confirm('Are you sure you want to reject this update? The deployment will be cancelled.')) {
                await executeDeploymentAction('reject', deploymentData.deployment_id);
            }
        };
    }
    
    // View details button
    const detailsBtn = document.getElementById('view-details-btn');
    if (detailsBtn) {
        detailsBtn.onclick = () => {
            showDeploymentDetails(deploymentData);
        };
    }
}

async function executeDeploymentAction(action, deploymentId) {
    try {
        const response = await fetch(`/manager/v1/updates/${action}`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                deployment_id: deploymentId,
                reason: action === 'reject' ? 'Manual rejection by operator' : undefined
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || `Failed to ${action} deployment`);
        }
        
        const result = await response.json();
        
        // Show success message
        alert(`Deployment ${action}ed successfully`);
        
        // Refresh the deployment status
        await checkPendingDeployment();
        await updateDeploymentStatus();
        
    } catch (error) {
        console.error(`Error ${action}ing deployment:`, error);
        alert(`Failed to ${action} deployment: ${error.message}`);
    }
}

function showDeploymentDetails(deploymentData) {
    // Create a modal or expand the details view
    const details = `
        Deployment ID: ${deploymentData.deployment_id}
        Agent Image: ${deploymentData.agent_image}
        GUI Image: ${deploymentData.gui_image || 'Not specified'}
        Strategy: ${deploymentData.strategy}
        Message: ${deploymentData.message}
        Staged At: ${formatDate(deploymentData.staged_at)}
        Affected Agents: ${deploymentData.affected_agents || 0}
        
        Risk Assessment:
        - Canary safety checks enabled
        - Automatic rollback on failure
        - WORK state validation required
        - 1 minute stability period enforced
    `;
    
    alert(details);
}

// Deployment status functions
async function updateCurrentImages() {
    try {
        const response = await fetch('/manager/v1/updates/current-images', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        if (!response.ok) throw new Error('Failed to fetch current images');
        
        const data = await response.json();
        
        document.getElementById('current-agent-image').textContent = data.agent_image || 'N/A';
        document.getElementById('current-agent-digest').textContent = data.agent_digest || 'N/A';
        document.getElementById('current-gui-image').textContent = data.gui_image || 'N/A';
        document.getElementById('current-gui-digest').textContent = data.gui_digest || 'N/A';
    } catch (error) {
        console.error('Error fetching current images:', error);
    }
}

async function updateDeploymentStatus() {
    try {
        const response = await fetch('/manager/v1/updates/status', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        if (!response.ok) throw new Error('Failed to fetch deployment status');
        
        const data = await response.json();
        const statusDiv = document.getElementById('deployment-status');
        
        if (data && data.deployment_id) {
            statusDiv.innerHTML = `
                <div class="space-y-2">
                    <div class="flex justify-between">
                        <span class="font-medium">Status:</span>
                        <span class="${data.status === 'in_progress' ? 'text-blue-600' : 
                                       data.status === 'completed' ? 'text-green-600' : 
                                       data.status === 'failed' ? 'text-red-600' : 
                                       'text-gray-600'}">${data.status}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="font-medium">Phase:</span>
                        <span>${data.canary_phase || 'N/A'}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="font-medium">Progress:</span>
                        <span>${data.agents_updated || 0}/${data.agents_total || 0}</span>
                    </div>
                    ${data.message ? `<div class="text-sm text-gray-600 italic">${data.message}</div>` : ''}
                </div>
                
                <!-- Event Timeline -->
                <div id="deployment-events-${data.deployment_id}" class="mt-4">
                    <button onclick="toggleDeploymentEvents('${data.deployment_id}')" 
                            class="text-sm text-blue-600 hover:text-blue-800">
                        <i class="fas fa-clock-rotate-left"></i> Show Event Timeline
                    </button>
                    <div id="events-content-${data.deployment_id}" class="hidden mt-2"></div>
                </div>
                
                <!-- Action Buttons for Failed Deployments -->
                ${data.status === 'failed' ? `
                    <div class="flex gap-2 pt-3 border-t mt-3">
                        <button onclick="cancelDeployment('${data.deployment_id}')" 
                                class="px-3 py-1.5 bg-gray-600 text-white text-sm rounded hover:bg-gray-700 transition-colors">
                            <i class="fas fa-times mr-1"></i>Clear & Reset
                        </button>
                        <button onclick="triggerNewDeployment()" 
                                class="px-3 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 transition-colors">
                            <i class="fas fa-redo mr-1"></i>Retry Deployment
                        </button>
                    </div>
                ` : ''}
            `;
        } else {
            statusDiv.innerHTML = '<p class="text-gray-600">No active deployment</p>';
        }
    } catch (error) {
        console.error('Error fetching deployment status:', error);
        const statusDiv = document.getElementById('deployment-status');
        if (statusDiv) {
            statusDiv.innerHTML = '<p class="text-gray-600">No active deployment</p>';
        }
    }
}

async function toggleDeploymentEvents(deploymentId) {
    const contentDiv = document.getElementById(`events-content-${deploymentId}`);
    const button = event.target.closest('button');
    
    if (contentDiv.classList.contains('hidden')) {
        // Fetch and show events
        try {
            const response = await fetch(`/manager/v1/updates/events/${deploymentId}`, {
                headers: {
                    'Authorization': `Bearer ${localStorage.getItem('access_token')}`
                }
            });
            
            if (response.ok) {
                const data = await response.json();
                displayDeploymentEvents(contentDiv, data.events || []);
                contentDiv.classList.remove('hidden');
                button.innerHTML = '<i class="fas fa-clock-rotate-left"></i> Hide Event Timeline';
            }
        } catch (error) {
            console.error('Error fetching deployment events:', error);
        }
    } else {
        // Hide events
        contentDiv.classList.add('hidden');
        button.innerHTML = '<i class="fas fa-clock-rotate-left"></i> Show Event Timeline';
    }
}

function displayDeploymentEvents(container, events) {
    if (!events || events.length === 0) {
        container.innerHTML = '<p class="text-sm text-gray-500">No events recorded</p>';
        return;
    }
    
    const eventHtml = events.map(event => {
        const time = new Date(event.timestamp).toLocaleTimeString();
        const eventIcon = getEventIcon(event.type);
        const eventColor = getEventColor(event.type);
        
        return `
            <div class="flex items-start space-x-3 py-2 border-b border-gray-100 last:border-0">
                <div class="flex-shrink-0 w-8 h-8 rounded-full ${eventColor} flex items-center justify-center">
                    <i class="${eventIcon} text-white text-xs"></i>
                </div>
                <div class="flex-grow">
                    <div class="text-sm font-medium">${event.message}</div>
                    <div class="text-xs text-gray-500">${time}</div>
                    ${event.details ? `
                        <div class="text-xs text-gray-600 mt-1">
                            ${formatEventDetails(event.details)}
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
    
    container.innerHTML = `
        <div class="bg-gray-50 rounded-lg p-3 max-h-64 overflow-y-auto">
            ${eventHtml}
        </div>
    `;
}

function getEventIcon(type) {
    const icons = {
        'staged': 'fas fa-inbox',
        'phase_started': 'fas fa-play',
        'phase_complete': 'fas fa-check-circle',
        'agent_stable': 'fas fa-heartbeat',
        'agent_updated': 'fas fa-sync',
        'deployment_complete': 'fas fa-flag-checkered',
        'error': 'fas fa-exclamation-triangle',
        'warning': 'fas fa-exclamation-circle'
    };
    return icons[type] || 'fas fa-info-circle';
}

function getEventColor(type) {
    const colors = {
        'staged': 'bg-blue-500',
        'phase_started': 'bg-indigo-500',
        'phase_complete': 'bg-green-500',
        'agent_stable': 'bg-emerald-500',
        'agent_updated': 'bg-purple-500',
        'deployment_complete': 'bg-green-600',
        'error': 'bg-red-500',
        'warning': 'bg-yellow-500'
    };
    return colors[type] || 'bg-gray-500';
}

function formatEventDetails(details) {
    if (!details) return '';
    
    const parts = [];
    if (details.agent_id) parts.push(`Agent: ${details.agent_id}`);
    if (details.phase) parts.push(`Phase: ${details.phase}`);
    if (details.version) parts.push(`Version: ${details.version}`);
    if (details.time_to_work) parts.push(`Time to WORK: ${details.time_to_work} min`);
    
    return parts.join(' • ');
}

async function updateDeploymentHistory() {
    try {
        const response = await fetch('/manager/v1/updates/history?limit=10', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        if (!response.ok) throw new Error('Failed to fetch deployment history');
        
        const data = await response.json();
        const historyDiv = document.getElementById('deployment-history');
        
        if (data.deployments && data.deployments.length > 0) {
            historyDiv.innerHTML = data.deployments.map(d => `
                <div class="border-b pb-2 mb-2 last:border-b-0">
                    <div class="flex justify-between">
                        <span class="text-sm font-medium">${formatDate(d.started_at)}</span>
                        <span class="text-sm ${d.status === 'completed' ? 'text-green-600' : 
                                               d.status === 'failed' ? 'text-red-600' : 
                                               'text-gray-600'}">${d.status}</span>
                    </div>
                    <div class="text-xs text-gray-600">${d.message || 'No message'}</div>
                </div>
            `).join('');
        } else {
            historyDiv.innerHTML = '<p class="text-gray-600">No deployment history</p>';
        }
    } catch (error) {
        console.error('Error fetching deployment history:', error);
    }
}

async function updateAgentVersions() {
    try {
        const response = await fetch('/manager/v1/agents', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        if (!response.ok) throw new Error('Failed to fetch agent versions');
        
        const data = await response.json();
        const agents = data.agents || [];
        const tableBody = document.getElementById('agent-versions-table');
        
        if (agents && agents.length > 0) {
            tableBody.innerHTML = agents.map(agent => `
                <tr>
                    <td class="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        ${agent.agent_name || agent.name || agent.agent_id}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm">
                        <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full 
                                   ${agent.status === 'running' ? 'bg-green-100 text-green-800' : 
                                     'bg-gray-100 text-gray-800'}">
                            ${agent.status}
                        </span>
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        ${agent.version || 'N/A'}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        ${agent.image || 'N/A'}
                    </td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        ${agent.created_at ? formatDate(agent.created_at) : 'N/A'}
                    </td>
                </tr>
            `).join('');
        } else {
            tableBody.innerHTML = '<tr><td colspan="5" class="text-center py-4 text-gray-500">No agents found</td></tr>';
        }
    } catch (error) {
        console.error('Error fetching agent versions:', error);
    }
}

// Main deployment tab update function
async function updateDeploymentTab() {
    // Call each function independently to ensure they all run
    // even if one fails
    const updates = [
        updateCurrentImages().catch(e => console.error('Error updating current images:', e)),
        updateDeploymentStatus().catch(e => console.error('Error updating deployment status:', e)),
        updateDeploymentHistory().catch(e => console.error('Error updating deployment history:', e)),
        updateAgentVersions().catch(e => console.error('Error updating agent versions:', e)),
        checkPendingDeployment().catch(e => console.error('Error checking pending deployment:', e)),
        updateRollbackOptions().catch(e => console.error('Error updating rollback options:', e))
    ];
    
    await Promise.all(updates);
}

// Update rollback options
async function updateRollbackOptions() {
    try {
        // Fetch rollback options from the new endpoint
        const response = await fetch('/manager/v1/updates/rollback-options', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        if (!response.ok) {
            document.getElementById('rollback-options').innerHTML = 
                '<p class="text-sm text-gray-600">Failed to load rollback options</p>';
            return;
        }
        
        const data = await response.json();
        
        // Extract options for each container type
        const agentOptions = data.agents || {};
        const guiOptions = data.gui || {};
        const nginxOptions = data.nginx || {};
        const rollbackDiv = document.getElementById('rollback-options');
        
        // Check if we have any rollback options
        const hasOptions = (agentOptions.n_minus_1 || agentOptions.n_minus_2 ||
                           guiOptions.n_minus_1 || guiOptions.n_minus_2 ||
                           nginxOptions.n_minus_1 || nginxOptions.n_minus_2);
        
        if (!hasOptions) {
            rollbackDiv.innerHTML = '<p class="text-sm text-gray-600">No rollback options available yet</p>';
            return;
        }
        
        let html = '';
        
        // N-1 rollback option (previous version)
        if (agentOptions.n_minus_1 || guiOptions.n_minus_1 || nginxOptions.n_minus_1) {
            html += `
                <div class="p-3 bg-white rounded-lg border border-gray-200 mb-2">
                    <div class="flex justify-between items-start">
                        <div class="flex-1">
                            <h5 class="font-medium text-sm text-gray-700 mb-2">Previous Version (n-1)</h5>
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
                                <div>
                                    <span class="font-medium text-gray-700">Agents:</span>
                                    <p class="text-gray-600 truncate">${agentOptions.n_minus_1?.image || 'No previous'}</p>
                                </div>
                                <div>
                                    <span class="font-medium text-gray-700">GUI:</span>
                                    <p class="text-gray-600 truncate">${guiOptions.n_minus_1?.image || 'No previous'}</p>
                                </div>
                                <div>
                                    <span class="font-medium text-gray-700">Nginx:</span>
                                    <p class="text-gray-600 truncate">${nginxOptions.n_minus_1?.image || 'No previous'}</p>
                                </div>
                            </div>
                        </div>
                        <button onclick="initiateRollback('n-1', {
                            agents: ${JSON.stringify(agentOptions.n_minus_1).replace(/"/g, '&quot;')},
                            gui: ${JSON.stringify(guiOptions.n_minus_1).replace(/"/g, '&quot;')},
                            nginx: ${JSON.stringify(nginxOptions.n_minus_1).replace(/"/g, '&quot;')}
                        })" 
                                class="px-3 py-1 bg-orange-600 text-white text-sm rounded hover:bg-orange-700">
                            <i class="fas fa-undo mr-1"></i>Rollback
                        </button>
                    </div>
                </div>
            `;
        }
        
        // N-2 rollback option (older version)
        if (agentOptions.n_minus_2 || guiOptions.n_minus_2 || nginxOptions.n_minus_2) {
            html += `
                <div class="p-3 bg-white rounded-lg border border-gray-200">
                    <div class="flex justify-between items-start">
                        <div class="flex-1">
                            <h5 class="font-medium text-sm text-gray-700 mb-2">Older Version (n-2)</h5>
                            <div class="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs">
                                <div>
                                    <span class="font-medium text-gray-700">Agents:</span>
                                    <p class="text-gray-600 truncate">${agentOptions.n_minus_2?.image || 'No older'}</p>
                                </div>
                                <div>
                                    <span class="font-medium text-gray-700">GUI:</span>
                                    <p class="text-gray-600 truncate">${guiOptions.n_minus_2?.image || 'No older'}</p>
                                </div>
                                <div>
                                    <span class="font-medium text-gray-700">Nginx:</span>
                                    <p class="text-gray-600 truncate">${nginxOptions.n_minus_2?.image || 'No older'}</p>
                                </div>
                            </div>
                        </div>
                        <button onclick="initiateRollback('n-2', {
                            agents: ${JSON.stringify(agentOptions.n_minus_2).replace(/"/g, '&quot;')},
                            gui: ${JSON.stringify(guiOptions.n_minus_2).replace(/"/g, '&quot;')},
                            nginx: ${JSON.stringify(nginxOptions.n_minus_2).replace(/"/g, '&quot;')}
                        })" 
                                class="px-3 py-1 bg-red-600 text-white text-sm rounded hover:bg-red-700">
                            <i class="fas fa-history mr-1"></i>Rollback
                        </button>
                    </div>
                </div>
            `;
        }
        
        rollbackDiv.innerHTML = html;
        
    } catch (error) {
        console.error('Error fetching rollback options:', error);
        document.getElementById('rollback-options').innerHTML = 
            '<p class="text-sm text-red-600">Failed to load rollback options</p>';
    }
}

// Initiate rollback with confirmation
let pendingRollback = null;

function initiateRollback(targetVersion, versionDetails) {
    pendingRollback = { targetVersion, versionDetails };
    
    // Update modal with details for all container types
    const detailsDiv = document.getElementById('rollback-details');
    
    // Handle new multi-container format
    let detailsHtml = `<div class="space-y-2">`;
    
    detailsHtml += `
        <div class="flex justify-between">
            <span class="text-sm font-medium">Rollback Target:</span>
            <span class="text-sm font-semibold">${targetVersion}</span>
        </div>
    `;
    
    // Agent version
    if (versionDetails.agents) {
        detailsHtml += `
            <div class="border-t pt-2">
                <span class="text-sm font-medium">Agents:</span>
                <p class="text-xs font-mono text-gray-600 truncate">${versionDetails.agents?.image || 'No change'}</p>
            </div>
        `;
    }
    
    // GUI version
    if (versionDetails.gui) {
        detailsHtml += `
            <div>
                <span class="text-sm font-medium">GUI:</span>
                <p class="text-xs font-mono text-gray-600 truncate">${versionDetails.gui?.image || 'No change'}</p>
            </div>
        `;
    }
    
    // Nginx version
    if (versionDetails.nginx) {
        detailsHtml += `
            <div>
                <span class="text-sm font-medium">Nginx:</span>
                <p class="text-xs font-mono text-gray-600 truncate">${versionDetails.nginx?.image || 'No change'}</p>
            </div>
        `;
    }
    
    detailsHtml += `</div>`;
    detailsDiv.innerHTML = detailsHtml;
    
    // Show modal
    document.getElementById('rollback-confirmation-modal').classList.remove('hidden');
}

function cancelRollback() {
    pendingRollback = null;
    document.getElementById('rollback-confirmation-modal').classList.add('hidden');
}

async function confirmRollback() {
    if (!pendingRollback) return;
    
    const button = event.currentTarget;
    const originalHTML = button.innerHTML;
    
    try {
        button.disabled = true;
        button.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Rolling back...';
        
        // Get the latest deployment ID first
        const statusResponse = await fetch('/manager/v1/updates/status', {
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}` 
            }
        });
        
        if (!statusResponse.ok) throw new Error('Failed to get deployment status');
        
        const status = await statusResponse.json();
        const deploymentId = status.deployment_id || 'latest';
        
        // Build target versions for each container type
        const targetVersions = {};
        
        if (pendingRollback.versionDetails.agents?.image) {
            targetVersions.agent_image = pendingRollback.versionDetails.agents.image;
        }
        if (pendingRollback.versionDetails.gui?.image) {
            targetVersions.gui_image = pendingRollback.versionDetails.gui.image;
        }
        if (pendingRollback.versionDetails.nginx?.image) {
            targetVersions.nginx_image = pendingRollback.versionDetails.nginx.image;
        }
        
        // Perform rollback
        const response = await fetch(`/manager/v1/updates/rollback`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem('managerToken')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                deployment_id: deploymentId,
                target_version: pendingRollback.targetVersion,
                target_versions: targetVersions
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Rollback failed');
        }
        
        const result = await response.json();
        
        // Show success
        showNotification('Rollback initiated successfully', 'success');
        
        // Close modal
        cancelRollback();
        
        // Refresh the deployment tab
        await updateDeploymentTab();
        
    } catch (error) {
        console.error('Rollback error:', error);
        showNotification(`Rollback failed: ${error.message}`, 'error');
        button.disabled = false;
        button.innerHTML = originalHTML;
    }
}

// Show notification helper
function showNotification(message, type = 'info') {
    const alertDiv = document.getElementById('error-alert');
    const messageSpan = document.getElementById('error-message');
    
    messageSpan.textContent = message;
    alertDiv.className = `mb-6 px-4 py-3 rounded border ${
        type === 'success' ? 'bg-green-50 border-green-200 text-green-700' :
        type === 'error' ? 'bg-red-50 border-red-200 text-red-700' :
        'bg-blue-50 border-blue-200 text-blue-700'
    }`;
    alertDiv.classList.remove('hidden');
    
    // Auto-hide after 5 seconds
    setTimeout(() => {
        alertDiv.classList.add('hidden');
    }, 5000);
}
