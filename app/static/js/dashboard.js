// Dashboard Main Logic
class Dashboard {
    constructor() {
        this.currentTab = 'services';
        this.autoRefreshInterval = null;
        this.init();
    }

    init() {
        this.setupTabs();
        this.setupRefreshButtons();
        this.setupSearch();
        this.setupAutoRefresh();
        this.loadInitialData();
        this.updateStatus(true);
    }

    setupTabs() {
        const tabButtons = document.querySelectorAll('.tab-button');
        tabButtons.forEach(button => {
            button.addEventListener('click', () => {
                const tabName = button.dataset.tab;
                this.switchTab(tabName);
            });
        });
    }

    switchTab(tabName) {
        // Update active tab button
        document.querySelectorAll('.tab-button').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        // Update active tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.toggle('active', content.id === `${tabName}-tab`);
        });

        this.currentTab = tabName;

        // Load tab data if not already loaded
        this.loadTabData(tabName);
    }

    setupRefreshButtons() {
        document.getElementById('refresh-services').addEventListener('click', () => this.loadServices());
        document.getElementById('refresh-containers').addEventListener('click', () => this.loadContainers());
        document.getElementById('refresh-events').addEventListener('click', () => this.loadEvents());
        document.getElementById('refresh-hosts').addEventListener('click', () => this.loadHosts());
    }

    setupSearch() {
        document.getElementById('services-search').addEventListener('input', (e) => {
            this.filterServices(e.target.value);
        });

        document.getElementById('containers-search').addEventListener('input', (e) => {
            this.filterContainers(e.target.value);
        });
    }

    setupAutoRefresh() {
        const checkbox = document.getElementById('auto-refresh-events');
        checkbox.addEventListener('change', (e) => {
            if (e.target.checked) {
                this.startAutoRefresh();
            } else {
                this.stopAutoRefresh();
            }
        });
    }

    startAutoRefresh() {
        this.autoRefreshInterval = setInterval(() => {
            if (this.currentTab === 'events') {
                this.loadEvents();
            }
        }, 5000);
    }

    stopAutoRefresh() {
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
            this.autoRefreshInterval = null;
        }
    }

    async loadInitialData() {
        await this.loadServices();
    }

    async loadTabData(tabName) {
        switch(tabName) {
            case 'services':
                await this.loadServices();
                break;
            case 'containers':
                await this.loadContainers();
                break;
            case 'events':
                await this.loadEvents();
                break;
            case 'hosts':
                await this.loadHosts();
                break;
        }
    }

    async loadServices() {
        const content = document.getElementById('services-content');
        content.classList.add('loading');
        content.innerHTML = '<div class="spinner"></div><p>Loading services...</p>';

        try {
            const data = await api.getServices();
            this.renderServices(data);
            this.updateLastUpdate();
            this.updateStatus(true);
        } catch (error) {
            this.showError(content, 'Failed to load services');
            this.updateStatus(false);
        }
    }

    renderServices(data) {
        const content = document.getElementById('services-content');
        content.classList.remove('loading');

        if (!data.services || data.services.length === 0) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📭</div>
                    <div class="empty-state-text">No services found</div>
                </div>
            `;
            return;
        }

        const servicesHTML = data.services.map(service => `
            <div class="service-card" data-name="${service.name.toLowerCase()}">
                <div class="service-name">
                    ${service.name}
                    ${service.is_static ? '<span class="service-badge static">STATIC</span>' : ''}
                    ${service.is_local ? '<span class="service-badge local">LOCAL</span>' : ''}
                    ${service.insecure_skip_verify ? '<span class="service-badge insecure">INSECURE</span>' : ''}
                </div>
                <div class="service-links">
                    ${service.public_urls && service.public_urls.length > 0 ?
                        service.public_urls.map(urlInfo => `
                            <a href="${urlInfo.url}" target="_blank" class="service-link">
                                <span class="link-icon">🌐</span>
                                <span>${urlInfo.domain}</span>
                            </a>
                        `).join('')
                    : ''}
                    ${service.backend_url ? `
                        <a href="${service.backend_url}" target="_blank" class="service-link">
                            <span class="link-icon">🔗</span>
                            <span>${service.backend_url}</span>
                        </a>
                    ` : ''}
                    ${service.container ? `
                        <div class="service-link" style="cursor: default;">
                            <span class="link-icon">📦</span>
                            <span>${service.container} @ ${service.host}</span>
                        </div>
                    ` : ''}
                    ${service.is_local && service.networks && service.networks.length > 0 ? `
                        <div class="service-link service-networks" style="cursor: default;">
                            <span class="link-icon">🔌</span>
                            <span>Networks: ${service.networks.join(', ')}</span>
                        </div>
                    ` : ''}
                </div>
            </div>
        `).join('');

        content.innerHTML = `<div class="service-grid">${servicesHTML}</div>`;
    }

    async loadContainers() {
        const content = document.getElementById('containers-content');
        content.classList.add('loading');
        content.innerHTML = '<div class="spinner"></div><p>Loading containers...</p>';

        try {
            const data = await api.getContainers();
            this.renderContainers(data);
            this.updateLastUpdate();
        } catch (error) {
            this.showError(content, 'Failed to load containers');
        }
    }

    renderContainers(data) {
        const content = document.getElementById('containers-content');
        content.classList.remove('loading');

        if (!data.hosts || Object.keys(data.hosts).length === 0) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📭</div>
                    <div class="empty-state-text">No containers found</div>
                </div>
            `;
            return;
        }

        const hostsHTML = Object.entries(data.hosts).map(([hostName, hostData]) => `
            <div class="host-group" data-host="${hostName.toLowerCase()}">
                <div class="host-header">
                    <div class="host-name">🖥️ ${hostName}</div>
                    <div class="host-count">${hostData.containers.length} containers</div>
                </div>
                <div class="container-list">
                    ${hostData.containers.map(container => `
                        <div class="container-item" data-name="${container.name.toLowerCase()}">
                            <div class="container-info">
                                <div class="container-name">${container.name}</div>
                                <div class="container-meta">
                                    ${container.image} · ${container.id.substring(0, 12)}
                                    ${container.ports ? ` · ${container.ports}` : ''}
                                </div>
                            </div>
                            <span class="container-status ${container.status}">${container.status}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `).join('');

        content.innerHTML = hostsHTML;
    }

    async loadEvents() {
        const content = document.getElementById('events-content');
        content.classList.add('loading');
        content.innerHTML = '<div class="spinner"></div><p>Loading events...</p>';

        try {
            const data = await api.getEvents();
            this.renderEvents(data);
            this.updateLastUpdate();
        } catch (error) {
            this.showError(content, 'Failed to load events');
        }
    }

    renderEvents(data) {
        const content = document.getElementById('events-content');
        content.classList.remove('loading');

        if (!data.events || data.events.length === 0) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📭</div>
                    <div class="empty-state-text">No recent events</div>
                </div>
            `;
            return;
        }

        const eventsHTML = `
            <table class="events-table">
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Host</th>
                        <th>Container</th>
                        <th>Action</th>
                        <th>Details</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.events.map(event => `
                        <tr class="${event.container === 'ssh' ? 'ssh-event' : ''}">
                            <td>${this.formatTime(event.timestamp)}</td>
                            <td>${event.host}</td>
                            <td>${event.container === 'ssh' ? '🔌 SSH' : event.container}</td>
                            <td><span class="event-action ${event.action}">${event.action}</span></td>
                            <td class="event-details">${event.details || ''}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;

        content.innerHTML = eventsHTML;
    }

    async loadHosts() {
        const content = document.getElementById('hosts-content');
        content.classList.add('loading');
        content.innerHTML = '<div class="spinner"></div><p>Loading host status...</p>';

        try {
            const data = await api.getHosts();
            this.renderHosts(data);
            this.updateLastUpdate();
        } catch (error) {
            this.showError(content, 'Failed to load host status');
        }
    }

    renderHosts(data) {
        const content = document.getElementById('hosts-content');
        content.classList.remove('loading');

        if (!data.hosts || Object.keys(data.hosts).length === 0) {
            content.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state-icon">📭</div>
                    <div class="empty-state-text">No hosts configured</div>
                </div>
            `;
            return;
        }

        const hostsHTML = Object.entries(data.hosts).map(([hostName, hostData]) => {
            // Count containers with snadboy labels
            const withLabelsCount = (hostData.containers_running_details || [])
                .filter(c => c.snadboy_labels && Object.keys(c.snadboy_labels).length > 0)
                .length;

            return `
                <div class="host-status-card">
                    <div class="host-status-header">
                        <div class="host-status-name">${hostName}</div>
                        <span class="host-status-badge ${hostData.status}">${hostData.status}</span>
                    </div>
                    <div class="host-stats">
                        <div class="stat-item">
                            <div class="stat-value">${hostData.containers_running || 0}</div>
                            <div class="stat-label">Running</div>
                        </div>
                        <div class="stat-item">
                            <div class="stat-value">${withLabelsCount}</div>
                            <div class="stat-label">With Labels</div>
                        </div>
                    </div>
                </div>
            `;
        }).join('');

        content.innerHTML = `<div class="host-status-grid">${hostsHTML}</div>`;
    }

    filterServices(query) {
        const cards = document.querySelectorAll('.service-card');
        const lowerQuery = query.toLowerCase();

        cards.forEach(card => {
            const name = card.dataset.name;
            const match = name.includes(lowerQuery);
            card.style.display = match ? '' : 'none';
        });
    }

    filterContainers(query) {
        const items = document.querySelectorAll('.container-item');
        const hosts = document.querySelectorAll('.host-group');
        const lowerQuery = query.toLowerCase();

        items.forEach(item => {
            const name = item.dataset.name;
            const match = name.includes(lowerQuery);
            item.style.display = match ? '' : 'none';
        });

        // Hide empty host groups
        hosts.forEach(host => {
            const visibleContainers = host.querySelectorAll('.container-item[style="display: ;"], .container-item:not([style])');
            host.style.display = visibleContainers.length > 0 ? '' : 'none';
        });
    }

    updateLastUpdate() {
        const now = new Date();
        document.getElementById('last-update').textContent = now.toLocaleTimeString();
    }

    updateStatus(connected) {
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');

        if (connected) {
            statusDot.classList.add('connected');
            statusText.textContent = 'Connected';
        } else {
            statusDot.classList.remove('connected');
            statusText.textContent = 'Disconnected';
        }
    }

    showError(element, message) {
        element.classList.remove('loading');
        element.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">⚠️</div>
                <div class="empty-state-text">${message}</div>
            </div>
        `;
    }

    formatTime(timestamp) {
        const date = new Date(timestamp * 1000);
        const now = new Date();
        const diff = now - date;

        // Less than 1 minute
        if (diff < 60000) {
            return 'Just now';
        }

        // Less than 1 hour
        if (diff < 3600000) {
            const minutes = Math.floor(diff / 60000);
            return `${minutes}m ago`;
        }

        // Less than 24 hours
        if (diff < 86400000) {
            const hours = Math.floor(diff / 3600000);
            return `${hours}h ago`;
        }

        // Format as time
        return date.toLocaleTimeString();
    }
}

// Initialize dashboard on page load
document.addEventListener('DOMContentLoaded', () => {
    new Dashboard();
});
