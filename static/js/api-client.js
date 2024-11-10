/**
 * API Client for KinOS
 * Centralizes all API calls and error handling
 */
class ApiClient {
    constructor(baseUrl = '') {
        this.baseUrl = ''; // Always use relative paths
        this.token = null; // For future authentication
    }

    async checkServerConnection() {
        try {
            const response = await Promise.race([
                fetch('/api/status', {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                }),
                new Promise((_, reject) => 
                    setTimeout(() => reject(new Error('Request timeout')), 5000)
                )
            ]);

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || `Server returned ${response.status}`);
            }

            const data = await response.json();
            return data.server?.running === true;
        } catch (error) {
            console.error('Server connection check failed:', error);
            throw error;
        }
    }

    async handleResponse(response) {
        if (!response.ok) {
            const error = await response.json();
            console.error('API Error:', error);
            
            // Create detailed error message with all available info
            let errorMessage = `${error.type || 'Error'}: ${error.error}\n`;
            if (error.details) {
                if (error.details.traceback) {
                    errorMessage += `\nTraceback:\n${error.details.traceback}`;
                }
                if (error.details.timestamp) {
                    errorMessage += `\nTimestamp: ${error.details.timestamp}`;
                }
                if (error.details.additional_info) {
                    errorMessage += `\nAdditional Info: ${JSON.stringify(error.details.additional_info)}`;
                }
            }
            
            // Display error in UI
            if (this.onError) {
                this.onError(errorMessage);
            }
            
            // Log full error object for debugging
            console.error('Full Error Details:', error);
            
            throw new Error(errorMessage);
        }
        return response.json();
    }

    async checkServerConnection() {
        try {
            const response = await Promise.race([
                fetch('/api/status', {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json'
                    }
                }),
                new Promise((_, reject) => 
                    setTimeout(() => reject(new Error('Connection timeout')), 5000)
                )
            ]);

            if (!response.ok) {
                throw new Error(`Server returned ${response.status}`);
            }

            const data = await response.json();
            return data.server?.running === true;
        } catch (error) {
            console.error('Server connection check failed:', error);
            return false;
        }
    }

    setToken(token) {
        this.token = token;
    }

    async handleResponse(response) {
        if (!response.ok) {
            const error = await response.json();
            console.error('API Error:', error);
            
            // Create detailed error message with all available info
            let errorMessage = `${error.type || 'Error'}: ${error.error}\n`;
            if (error.details) {
                if (error.details.traceback) {
                    errorMessage += `\nTraceback:\n${error.details.traceback}`;
                }
                if (error.details.timestamp) {
                    errorMessage += `\nTimestamp: ${error.details.timestamp}`;
                }
                if (error.details.additional_info) {
                    errorMessage += `\nAdditional Info: ${JSON.stringify(error.details.additional_info)}`;
                }
            }
            
            // Display error in UI
            if (this.onError) {
                this.onError(errorMessage);
            }
            
            // Log full error object for debugging
            console.error('Full Error Details:', error);
            
            throw new Error(errorMessage);
        }
        return response.json();
    }

    // Agent endpoints
    async getAgentStatus() {
        const response = await fetch('/api/agents/status');
        return this.handleResponse(response);
    }

    async getAgentPrompt(agentId) {
        const response = await fetch(`/api/agent/${agentId}/prompt`);
        return this.handleResponse(response);
    }

    async saveAgentPrompt(agentId, prompt) {
        const response = await fetch(`/api/agent/${agentId}/prompt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt })
        });
        return this.handleResponse(response);
    }

    async controlAgent(agentId, action) {
        const response = await fetch(`/api/agent/${agentId}/${action}`, {
            method: 'POST'
        });
        return this.handleResponse(response);
    }

    // Mission endpoints
    async getAllMissions() {
        const response = await fetch('/api/missions');
        return this.handleResponse(response);
    }

    async createMission(name, description = '') {
        const response = await fetch('/api/missions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description })
        });
        return this.handleResponse(response);
    }

    async getMissionContent(missionId) {
        const response = await fetch(`/api/missions/${missionId}/content`);
        return this.handleResponse(response);
    }

    async updateMission(missionId, updates) {
        const response = await fetch(`/api/missions/${missionId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        });
        return this.handleResponse(response);
    }

    // File operations
    async getFileContent(missionId, filePath) {
        const response = await fetch(`/api/missions/${missionId}/files/${filePath}`);
        return this.handleResponse(response);
    }

    async saveFileContent(missionId, filePath, content) {
        const response = await fetch(`/api/missions/${missionId}/files/${filePath}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content })
        });
        return this.handleResponse(response);
    }

    // Agent operations
    async getAgentLogs(agentId) {
        const response = await fetch(`/api/agent/${agentId}/logs`);
        return this.handleResponse(response);
    }

    async updateAgentConfig(agentId, config) {
        const response = await fetch(`/api/agent/${agentId}/config`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });
        return this.handleResponse(response);
    }

    async createAgent(name, prompt) {
        const response = await fetch('/api/agents', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name, prompt })
        });
        return this.handleResponse(response);
    }

    async selectMission(missionId) {
        const response = await fetch(`/api/missions/${missionId}/select`, {
            method: 'POST'
        });
        return this.handleResponse(response);
    }

    async getMissionContent(missionId) {
        const response = await fetch(`/api/missions/${missionId}/content`);
        return this.handleResponse(response);
    }

    async createMission(name, description = '') {
        const response = await fetch(`/api/missions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description })
        });
        return this.handleResponse(response);
    }

    // Notification endpoints
    async getNotifications() {
        const response = await fetch('/api/notifications');
        return this.handleResponse(response);
    }

    async sendNotification(notification) {
        const response = await fetch('/api/notifications', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(notification)
        });
        return this.handleResponse(response);
    }
}

export default ApiClient;
