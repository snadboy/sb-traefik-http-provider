// API Client
class APIClient {
    constructor(baseURL = '/api') {
        this.baseURL = baseURL;
    }

    async request(endpoint, options = {}) {
        try {
            const response = await fetch(`${this.baseURL}${endpoint}`, options);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error(`API request failed: ${endpoint}`, error);
            throw error;
        }
    }

    // Get all services
    async getServices() {
        return this.request('/services');
    }

    // Get containers grouped by host
    async getContainers() {
        return this.request('/containers/grouped');
    }

    // Get recent events
    async getEvents(limit = 50) {
        return this.request(`/events?limit=${limit}`);
    }

    // Get host status
    async getHosts() {
        return this.request('/hosts');
    }

    // Get full config
    async getConfig() {
        return this.request('/traefik/config');
    }
}

// Export API client instance
const api = new APIClient();
