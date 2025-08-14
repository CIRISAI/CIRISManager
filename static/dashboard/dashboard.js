/**
 * CIRIS Public Dashboard
 * Real-time telemetry visualization
 */

// Initialize telemetry client
let telemetryClient;
let charts = {};
let refreshInterval;
let currentTab = 'overview';

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    await initializeDashboard();
});

async function initializeDashboard() {
    try {
        // Initialize telemetry client - no auth required for public endpoints
        const baseUrl = window.location.origin;
        
        // The SDK exports CIRISTelemetryClient as default, available as CIRISTelemetry global
        // Access the actual client class from the module
        const ClientConstructor = CIRISTelemetry.default || CIRISTelemetry.CIRISTelemetryClient || CIRISTelemetry;
        telemetryClient = new ClientConstructor({
            baseUrl: baseUrl,
            timeout: 30000,
            enableCache: true,
            cacheTimeout: 5000
        });
        
        // Initialize charts
        initializeCharts();
        
        // Load initial data
        await loadDashboardData();
        
        // Hide loading, show dashboard
        document.getElementById('loading').classList.add('hidden');
        document.getElementById('dashboard').classList.remove('hidden');
        
        // Start auto-refresh (every 30 seconds)
        startAutoRefresh();
        
    } catch (error) {
        console.error('Failed to initialize dashboard:', error);
        showError('Failed to connect to telemetry system');
    }
}

function initializeCharts() {
    // Agent Distribution Pie Chart
    const distributionCtx = document.getElementById('agent-distribution-chart')?.getContext('2d');
    if (distributionCtx) {
        charts.distribution = new Chart(distributionCtx, {
            type: 'doughnut',
            data: {
                labels: ['Healthy', 'Degraded', 'Down'],
                datasets: [{
                    data: [0, 0, 0],
                    backgroundColor: ['#10b981', '#f59e0b', '#ef4444']
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }
    
    // Activity Timeline Chart
    const activityCtx = document.getElementById('activity-chart')?.getContext('2d');
    if (activityCtx) {
        charts.activity = new Chart(activityCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Messages',
                        data: [],
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        tension: 0.4
                    },
                    {
                        label: 'Incidents',
                        data: [],
                        borderColor: '#ef4444',
                        backgroundColor: 'rgba(239, 68, 68, 0.1)',
                        tension: 0.4
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }
    
    // Cognitive State Chart
    const cognitiveCtx = document.getElementById('cognitive-chart')?.getContext('2d');
    if (cognitiveCtx) {
        charts.cognitive = new Chart(cognitiveCtx, {
            type: 'polarArea',
            data: {
                labels: ['WORK', 'DREAM', 'SOLITUDE', 'PLAY'],
                datasets: [{
                    data: [0, 0, 0, 0],
                    backgroundColor: [
                        'rgba(30, 64, 175, 0.7)',
                        'rgba(107, 33, 168, 0.7)',
                        'rgba(146, 64, 14, 0.7)',
                        'rgba(6, 95, 70, 0.7)'
                    ]
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false
            }
        });
    }
    
    // Response Time Chart
    const responseCtx = document.getElementById('response-time-chart')?.getContext('2d');
    if (responseCtx) {
        charts.responseTime = new Chart(responseCtx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [{
                    label: 'Response Time (ms)',
                    data: [],
                    backgroundColor: '#6366f1'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    }
}

async function loadDashboardData() {
    try {
        // Get public status
        const status = await telemetryClient.getPublicStatus();
        updateKeyMetrics(status);
        
        // Get public history (last 24 hours, 1 hour intervals)
        const history = await telemetryClient.getPublicHistory(24, 60);
        updateHistoryCharts(history);
        
        // Update last update time
        updateLastUpdateTime();
        
    } catch (error) {
        console.error('Failed to load dashboard data:', error);
        // Continue showing cached data if available
    }
}

function updateKeyMetrics(status) {
    // Update metric bar
    document.getElementById('metric-agents-total').textContent = status.total_agents || '0';
    document.getElementById('metric-agents-healthy').textContent = 
        Math.round((status.healthy_percentage || 0) * status.total_agents / 100) || '0';
    
    // Calculate other metrics from history if available
    document.getElementById('metric-messages').textContent = 
        formatNumber(status.message_volume_24h || 0);
    document.getElementById('metric-incidents').textContent = 
        status.incident_count_24h || '0';
    
    // Update health indicators
    const healthyPercent = status.healthy_percentage || 0;
    const healthScore = healthyPercent + '%';
    document.getElementById('health-score').textContent = healthScore;
    
    const overallStatus = document.getElementById('overall-status');
    if (healthyPercent >= 90) {
        overallStatus.textContent = 'Healthy';
        overallStatus.className = 'font-bold status-healthy';
    } else if (healthyPercent >= 70) {
        overallStatus.textContent = 'Degraded';
        overallStatus.className = 'font-bold status-degraded';
    } else {
        overallStatus.textContent = 'Critical';
        overallStatus.className = 'font-bold status-down';
    }
    
    // Update agent distribution chart
    if (charts.distribution) {
        const healthy = Math.round(healthyPercent * status.total_agents / 100);
        const down = Math.round((100 - healthyPercent) * status.total_agents / 100 * 0.3); // Estimate
        const degraded = status.total_agents - healthy - down;
        
        charts.distribution.data.datasets[0].data = [healthy, degraded, down];
        charts.distribution.update();
    }
    
    // Update deployment status
    document.getElementById('active-deployments').textContent = 
        status.deployment_active ? '1' : '0';
}

function updateHistoryCharts(history) {
    if (!history || history.length === 0) return;
    
    // Process history data
    const labels = history.map(h => formatTime(h.timestamp));
    const messages = history.map(h => h.total_messages || 0);
    const incidents = history.map(h => h.total_incidents || 0);
    const healthy = history.map(h => h.healthy_agents || 0);
    const total = history.map(h => h.total_agents || 0);
    
    // Update activity chart
    if (charts.activity) {
        charts.activity.data.labels = labels;
        charts.activity.data.datasets[0].data = messages;
        charts.activity.data.datasets[1].data = incidents;
        charts.activity.update();
    }
    
    // Calculate aggregates
    const totalMessages = messages.reduce((a, b) => a + b, 0);
    const totalIncidents = incidents.reduce((a, b) => a + b, 0);
    const avgHealthy = healthy.reduce((a, b) => a + b, 0) / healthy.length;
    
    // Update success rate
    const successRate = totalMessages > 0 
        ? ((totalMessages - totalIncidents) / totalMessages * 100).toFixed(1) + '%'
        : '100%';
    document.getElementById('success-rate').textContent = successRate;
}

function updateAgentsTab(agents) {
    const container = document.getElementById('agent-cards');
    if (!container) return;
    
    container.innerHTML = '';
    
    agents.forEach(agent => {
        const card = document.createElement('div');
        card.className = 'border rounded-lg p-4 hover:shadow-lg transition-shadow';
        
        const statusClass = agent.api_healthy ? 'status-healthy' : 'status-down';
        const statusIcon = agent.api_healthy ? 'check-circle' : 'times-circle';
        
        card.innerHTML = `
            <div class="flex justify-between items-start mb-2">
                <h4 class="font-semibold">${agent.agent_name}</h4>
                <i class="fas fa-${statusIcon} ${statusClass}"></i>
            </div>
            <div class="space-y-1 text-sm">
                <div class="flex justify-between">
                    <span class="text-gray-500">State:</span>
                    <span class="cognitive-${agent.cognitive_state.toLowerCase()}">${agent.cognitive_state}</span>
                </div>
                <div class="flex justify-between">
                    <span class="text-gray-500">Messages:</span>
                    <span>${formatNumber(agent.message_count_24h)}</span>
                </div>
                <div class="flex justify-between">
                    <span class="text-gray-500">Response:</span>
                    <span>${agent.api_response_time_ms || '-'}ms</span>
                </div>
            </div>
        `;
        
        container.appendChild(card);
    });
}

function switchTab(tabName) {
    // Hide all content
    document.querySelectorAll('[id$="-content"]').forEach(el => {
        el.classList.add('hidden');
    });
    
    // Remove active class from all tabs
    document.querySelectorAll('[id$="-tab"]').forEach(el => {
        el.classList.remove('tab-active');
        el.classList.add('text-gray-500');
    });
    
    // Show selected content
    document.getElementById(`${tabName}-content`).classList.remove('hidden');
    
    // Activate selected tab
    const tab = document.getElementById(`${tabName}-tab`);
    tab.classList.add('tab-active');
    tab.classList.remove('text-gray-500');
    
    currentTab = tabName;
    
    // Load tab-specific data if needed
    if (tabName === 'agents') {
        loadAgentsData();
    } else if (tabName === 'cognitive') {
        loadCognitiveData();
    } else if (tabName === 'performance') {
        loadPerformanceData();
    } else if (tabName === 'history') {
        loadHistoryData();
    }
}

async function loadAgentsData() {
    // For public dashboard, we only have access to aggregated data
    // Individual agent details would require authentication
    const status = await telemetryClient.getPublicStatus();
    
    // Update counts
    document.getElementById('agents-healthy-count').textContent = 
        Math.round(status.healthy_percentage * status.total_agents / 100);
    document.getElementById('agents-degraded-count').textContent = '0';
    document.getElementById('agents-down-count').textContent = 
        status.total_agents - Math.round(status.healthy_percentage * status.total_agents / 100);
}

async function loadCognitiveData() {
    // Simulated cognitive state data for public view
    // Real data would come from authenticated endpoints
    if (charts.cognitive) {
        // Use estimated distribution
        const total = 10;
        charts.cognitive.data.datasets[0].data = [
            Math.floor(total * 0.4), // WORK
            Math.floor(total * 0.2), // DREAM
            Math.floor(total * 0.2), // SOLITUDE
            Math.floor(total * 0.2)  // PLAY
        ];
        charts.cognitive.update();
    }
}

async function loadPerformanceData() {
    // Load aggregated performance metrics
    const history = await telemetryClient.getPublicHistory(24, 60);
    
    // Update performance table with aggregated data
    const tableBody = document.getElementById('performance-table');
    if (tableBody && history.length > 0) {
        const latest = history[history.length - 1];
        tableBody.innerHTML = `
            <tr>
                <td class="px-6 py-4 text-sm">All Agents (Aggregated)</td>
                <td class="px-6 py-4 text-sm">
                    <span class="px-2 py-1 bg-green-100 text-green-800 rounded text-xs">
                        ${latest.healthy_agents}/${latest.total_agents} Healthy
                    </span>
                </td>
                <td class="px-6 py-4 text-sm">-</td>
                <td class="px-6 py-4 text-sm">${formatNumber(latest.total_messages)}</td>
                <td class="px-6 py-4 text-sm">-</td>
                <td class="px-6 py-4 text-sm">-</td>
            </tr>
        `;
    }
}

async function loadHistoryData() {
    const range = document.getElementById('history-range').value;
    const history = await telemetryClient.getPublicHistory(parseInt(range), 60);
    
    // Update history charts
    if (history && history.length > 0) {
        const labels = history.map(h => formatTime(h.timestamp));
        const availability = history.map(h => 
            h.total_agents > 0 ? (h.healthy_agents / h.total_agents * 100) : 0
        );
        
        // Update availability chart
        const availCtx = document.getElementById('history-availability')?.getContext('2d');
        if (availCtx && !charts.historyAvailability) {
            charts.historyAvailability = new Chart(availCtx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Availability %',
                        data: availability,
                        borderColor: '#10b981',
                        backgroundColor: 'rgba(16, 185, 129, 0.1)',
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100
                        }
                    }
                }
            });
        } else if (charts.historyAvailability) {
            charts.historyAvailability.data.labels = labels;
            charts.historyAvailability.data.datasets[0].data = availability;
            charts.historyAvailability.update();
        }
    }
}

async function refreshData() {
    const icon = document.getElementById('refresh-icon');
    icon.classList.add('fa-spin');
    
    try {
        await loadDashboardData();
        
        // Refresh current tab data
        if (currentTab === 'agents') {
            await loadAgentsData();
        } else if (currentTab === 'cognitive') {
            await loadCognitiveData();
        } else if (currentTab === 'performance') {
            await loadPerformanceData();
        } else if (currentTab === 'history') {
            await loadHistoryData();
        }
    } finally {
        icon.classList.remove('fa-spin');
    }
}

function startAutoRefresh() {
    refreshInterval = setInterval(() => {
        refreshData();
    }, 30000); // Refresh every 30 seconds
}

function stopAutoRefresh() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
}

// Utility functions
function formatTime(timestamp) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function formatNumber(num) {
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}

function updateLastUpdateTime() {
    const now = new Date();
    document.getElementById('last-update').textContent = 
        `Updated ${now.toLocaleTimeString()}`;
}

function showError(message) {
    console.error(message);
    // Could show a toast or alert
}

// Handle visibility change to pause/resume updates
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        stopAutoRefresh();
    } else {
        startAutoRefresh();
        refreshData();
    }
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    stopAutoRefresh();
});