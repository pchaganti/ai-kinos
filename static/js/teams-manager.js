export default {
    name: 'TeamsManager',
    props: {
        currentMission: {
            type: Object,
            required: true
        }
    },
    data() {
        return {
            statusCache: new Map(),
            statusCacheTTL: 5000, // 5 seconds
            showAddAgentModal: false,
            availableAgents: [
                "SpecificationsAgent",
                "ManagementAgent", 
                "EvaluationAgent",
                "SuiviAgent",
                "DocumentalisteAgent",
                "DuplicationAgent",
                "RedacteurAgent",
                "ProductionAgent",
                "TesteurAgent",
                "ValidationAgent"
            ],
            selectedTeamForEdit: null,
            selectedAgent: null,
            teams: [{
                name: "book writing",
                agents: [
                    "SpecificationsAgent",
                    "ManagementAgent",
                    "EvaluationAgent", 
                    "SuiviAgent",
                    "DocumentalisteAgent",
                    "DuplicationAgent",
                    "RedacteurAgent",
                    "ValidationAgent"
                ]
            },
            {
                name: "literature review",
                agents: [
                    "SpecificationsAgent", 
                    "ManagementAgent",
                    "EvaluationAgent",
                    "SuiviAgent",
                    "DocumentalisteAgent", 
                    "DuplicationAgent",
                    "RedacteurAgent",
                    "ValidationAgent"
                ]
            },
            {
                name: "coding team",
                agents: [
                    "SpecificationsAgent",
                    "ManagementAgent", 
                    "EvaluationAgent",
                    "SuiviAgent",
                    "DocumentalisteAgent",
                    "DuplicationAgent",
                    "ProductionAgent",
                    "TesteurAgent",
                    "ValidationAgent"
                ]
            }],
            loading: false,
            error: null,
            activeTeam: null,
            teamStats: new Map(),
            teamHistory: new Map(),
            loadingStats: false,
            statsInterval: null,
            POLL_INTERVAL: 30000, // Make polling interval configurable
            loadingTeams: new Set(),
            loadingAgents: new Set()
        }
    },

    computed: {
        hasActiveTeam() {
            return this.activeTeam !== null;
        }
    },
    watch: {
        currentMission: {
            immediate: true,
            handler(newMission) {
                if (newMission) {
                    this.loadTeams();
                }
            }
        }
    },
    mounted() {
        this.loadTeams();
    },
    beforeUnmount() {
        this.stopTeamMonitoring();
        this.statusCache.clear();
        this.teamStats.clear();
        this.teamHistory.clear();
    },
    methods: {
        async getTeamStatus(team) {
            const now = Date.now();
            const cached = this.statusCache.get(team.id);
            
            if (cached && (now - cached.timestamp) < this.statusCacheTTL) {
                return cached.status;
            }

            try {
                const response = await fetch(`/api/teams/${encodeURIComponent(team.id)}/status`);
                if (!response.ok) throw new Error('Failed to fetch team status');
                
                const status = await response.json();
                this.statusCache.set(team.id, {
                    status,
                    timestamp: now
                });
                
                return status;
            } catch (error) {
                console.error('Error fetching team status:', error);
                throw error;
            }
        },

        async retryOperation(operation, maxRetries = 3) {
            let attempts = 0;
            while (attempts < maxRetries) {
                try {
                    return await operation();
                } catch (error) {
                    attempts++;
                    if (attempts === maxRetries) throw error;
                    
                    // Exponential backoff
                    await new Promise(resolve => 
                        setTimeout(resolve, Math.pow(2, attempts) * 1000)
                    );
                }
            }
        },

        async toggleTeam(team) {
            if (this.loadingTeams.has(team.name)) return;
            
            try {
                this.loadingTeams.add(team.name);
                const allRunning = this.isTeamRunning(team);
                const action = allRunning ? 'stop' : 'start';

                const response = await fetch(`/api/teams/${encodeURIComponent(team.id)}/${action}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                });

                if (!response.ok) {
                    throw new Error(`Failed to ${action} team`);
                }

                const result = await response.json();
                
                // Update team status based on response
                const stats = this.teamStats.get(team.name) || {};
                if (!stats.agentStatus) stats.agentStatus = {};
                
                // Update agent statuses from response
                if (result.agents) {
                    Object.entries(result.agents).forEach(([agent, status]) => {
                        stats.agentStatus[agent] = status.running;
                    });
                }
            
                this.teamStats.set(team.name, stats);
                this.updateTeamHistory(team, `Team ${action}ed`);

            } catch (error) {
                this.handleError(`Failed to ${action} team`, error);
            } finally {
                this.loadingTeams.delete(team.name);
            }
        },

        isTeamRunning(team) {
            const stats = this.teamStats.get(team.name);
            if (!stats?.agentStatus) return false;
            return Object.values(stats.agentStatus).every(status => status === true);
        },

        getTeamStatusClass(team) {
            const isRunning = this.isTeamRunning(team);
            return {
                'bg-red-500': isRunning,
                'bg-green-500': !isRunning,
                'hover:bg-red-600': isRunning,
                'hover:bg-green-600': !isRunning,
                'text-white': true,
                'font-medium': true,
                'px-4': true,
                'py-2': true,
                'rounded': true,
                'transition-colors': true,
                'duration-200': true
            };
        },

        async loadTeams() {
            try {
                this.loading = true;
                this.error = null;
                
                const response = await fetch('/api/teams');
                if (!response.ok) {
                    throw new Error('Failed to load teams');
                }
                
                const teams = await response.json();
                this.teams = teams.map(team => ({
                    ...team,
                    agents: team.agents || []
                }));
            } catch (error) {
                console.error('Error loading teams:', error);
                this.error = error.message;
            } finally {
                this.loading = false;
            }
        },

        // API Interactions
        async activateTeam(team) {
            if (this.activeTeam?.name === team.name) return;

            try {
                await this.stopCurrentAgents();
                await this.activateTeamAgents(team);
                await this.startAgents();
                
                this.updateTeamHistory(team, 'activated');
                this.startTeamMonitoring(team);
            } catch (error) {
                this.handleError('Failed to activate team', error);
            }
        },

        async stopCurrentAgents() {
            const response = await fetch('/api/agents/stop', { method: 'POST' });
            if (!response.ok) {
                throw new Error('Failed to stop current agents');
            }
        },

        async activateTeamAgents(team) {
            const response = await fetch(
                `/api/missions/${this.currentMission.id}/teams/${encodeURIComponent(team.name)}/activate`, 
                { method: 'POST' }
            );

            if (!response.ok) {
                throw new Error('Failed to activate team agents');
            }

            this.activeTeam = team;
        },

        async startAgents() {
            const response = await fetch('/api/agents/start', { method: 'POST' });
            if (!response.ok) {
                throw new Error('Failed to start agents');
            }
        },

        // Team Monitoring
        async startTeamMonitoring(team) {
            this.initializeTeamStats(team);
            await this.pollTeamStats(team);
            
            this.statsInterval = setInterval(
                () => this.pollTeamStats(team), 
                this.POLL_INTERVAL
            );
        },

        initializeTeamStats(team) {
            if (!this.teamStats.has(team.name)) {
                this.teamStats.set(team.name, {
                    successRate: 0,
                    completedTasks: 0,
                    averageResponseTime: 0,
                    lastUpdate: null,
                    agentStatus: team.agents.reduce((acc, agent) => {
                        acc[agent] = false;
                        return acc;
                    }, {})
                });
            }
        },

        async toggleAgent(teamName, agentName) {
            const agentKey = `${teamName}-${agentName}`;
            if (this.loadingAgents.has(agentKey)) return;
            
            try {
                this.loadingAgents.add(agentKey);
                const team = this.teams.find(t => t.name === teamName);
                if (!team) return;

                const isRunning = this.getAgentStatus(teamName, agentName);
                const action = isRunning ? 'stop' : 'start';

                const response = await fetch(
                    `/api/teams/${encodeURIComponent(team.id)}/agents/${encodeURIComponent(agentName)}/${action}`, 
                    {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        }
                    }
                );

                if (!response.ok) {
                    throw new Error(`Failed to ${action} agent`);
                }

                const result = await response.json();

                // Update agent status based on response
                const stats = this.teamStats.get(teamName) || {};
                if (!stats.agentStatus) stats.agentStatus = {};
                stats.agentStatus[agentName] = !isRunning;
                this.teamStats.set(teamName, stats);

                this.updateTeamHistory(team, `Agent ${agentName} ${action}ed`);

            } catch (error) {
                this.handleError(`Failed to toggle agent ${agentName}`, error);
            } finally {
                this.loadingAgents.delete(agentKey);
            }
        },

        getAgentStatus(teamName, agentName) {
            const stats = this.teamStats.get(teamName);
            return stats?.agentStatus?.[agentName] || false;
        },

        getAgentStatusClass(teamName, agentName) {
            const isRunning = this.getAgentStatus(teamName, agentName);
            return {
                'bg-red-500': isRunning,
                'bg-green-500': !isRunning,
                'hover:bg-red-600': isRunning,
                'hover:bg-green-600': !isRunning,
                'text-white': true,
                'font-medium': true,
                'px-2': true,
                'py-1': true,
                'rounded': true,
                'text-xs': true,
                'transition-colors': true,
                'duration-200': true
            };
        },

        async pollTeamStats(team) {
            try {
                const stats = await this.getTeamStatus(team);
            
                this.teamStats.set(team.name, {
                    successRate: stats.metrics?.success_rate || 0,
                    completedTasks: stats.metrics?.completed_tasks || 0,
                    averageResponseTime: stats.metrics?.average_response_time || 0,
                    agentStatus: stats.agents || {},
                    lastUpdate: new Date()
                });
            } catch (error) {
                console.error('Error fetching team stats:', error);
            }
        },

        stopTeamMonitoring() {
            if (this.statsInterval) {
                clearInterval(this.statsInterval);
                this.statsInterval = null;
            }
        },

        // Metrics and Formatting
        formatMetric(value, type) {
            const formatters = {
                percentage: value => `${Math.round(value)}%`,
                time: value => `${value.toFixed(1)}s`,
                number: value => Math.round(value).toString(),
                default: value => value
            };

            return (formatters[type] || formatters.default)(value);
        },

        // Team History
        updateTeamHistory(team, action) {
            if (!this.teamHistory.has(team.name)) {
                this.teamHistory.set(team.name, []);
            }
            this.teamHistory.get(team.name).push({
                timestamp: new Date(),
                action
            });
        },

        // Error Handling
        handleError(message, error) {
            console.error(message, error);
            this.error = error.message;
        },

        getTeamStatusText(team) {
            if (this.loadingTeams.has(team.name)) {
                return 'Processing...';
            }
            const running = this.isTeamRunning(team);
            const count = team.agents.filter(agent => this.getAgentStatus(team.name, agent)).length;
            return `${running ? 'Stop' : 'Start'} Team (${count}/${team.agents.length} running)`;
        },

        getAgentStatusText(teamName, agentName) {
            const agentKey = `${teamName}-${agentName}`;
            if (this.loadingAgents.has(agentKey)) {
                return '...';
            }
            return this.getAgentStatus(teamName, agentName) ? 'Stop' : 'Start';
        },

        getTeamEfficiency(team) {
            const stats = this.teamStats.get(team.name);
            if (!stats) return 0;
            
            const successWeight = 0.4;
            const speedWeight = 0.3;
            const taskWeight = 0.3;

            // Ensure values are numbers and clamp between 0-100
            const successRate = Math.min(Math.max(stats.successRate || 0, 0), 100);
            const responseTime = Math.min(Math.max(stats.averageResponseTime || 0, 0), 1000);
            const tasks = Math.min(Math.max(stats.completedTasks || 0, 0), 100);

            const successScore = successRate * successWeight;
            const speedScore = (1000 - responseTime) / 1000 * speedWeight;
            const taskScore = tasks / 100 * taskWeight;

            // Ensure final score is between 0-100
            return Math.min(Math.max((successScore + speedScore + taskScore) * 100, 0), 100);
        },

        openAddAgentModal(team) {
            this.selectedTeamForEdit = team;
            this.selectedAgent = null;
            this.showAddAgentModal = true;
        },

        closeAddAgentModal() {
            this.showAddAgentModal = false;
            this.selectedTeamForEdit = null;
            this.selectedAgent = null;
        },

        getAvailableAgents() {
            if (!this.selectedTeamForEdit) return [];
            return this.availableAgents.filter(agent => 
                !this.selectedTeamForEdit.agents.includes(agent)
            );
        },

        async addAgentToTeam() {
            if (!this.selectedTeamForEdit || !this.selectedAgent) return;

            try {
                // Add the agent to the team's agents array
                const updatedAgents = [...this.selectedTeamForEdit.agents, this.selectedAgent];
                
                // Find the team in teams array and update it
                const teamIndex = this.teams.findIndex(t => t.name === this.selectedTeamForEdit.name);
                if (teamIndex !== -1) {
                    this.teams[teamIndex] = {
                        ...this.teams[teamIndex],
                        agents: updatedAgents
                    };
                }

                // Close the modal
                this.closeAddAgentModal();
            } catch (error) {
                console.error('Error adding agent to team:', error);
            }
        }
    },
    template: /* html */`
        <div class="p-6 relative h-full flex flex-col">
            <div v-if="loading" class="absolute inset-0 bg-white bg-opacity-75 flex items-center justify-center">
                <div class="text-center">
                    <i class="mdi mdi-loading mdi-spin text-4xl text-blue-500"></i>
                    <p class="mt-2 text-gray-600">Loading teams...</p>
                </div>
            </div>
            <div class="mb-6">
                <h2 class="text-2xl font-bold">Teams</h2>
            </div>
            
            <div class="overflow-auto flex-1 pr-2">
                <div v-if="loading" class="text-gray-600">
                    Loading teams...
                </div>
                
                <div v-else-if="error" class="text-red-500">
                    {{ error }}
                </div>
                
                <div v-else class="grid grid-cols-1 gap-6">
                <div v-for="team in teams" 
                     :key="team.name"
                     class="bg-white rounded-lg shadow-md p-6 team-card">
                    <div class="flex justify-between items-center mb-4">
                        <h3 class="text-xl font-semibold">${team.name}</h3>
                        <div class="flex items-center space-x-2">
                            <button @click="openAddAgentModal(team)"
                                    class="p-2 rounded-full hover:bg-gray-100"
                                    title="Add agent to team">
                                <i class="mdi mdi-plus text-gray-600"></i>
                            </button>
                            <button @click="toggleTeam(team)"
                                    :class="[
                                        getTeamStatusClass(team),
                                        {'opacity-75 cursor-wait': loadingTeams.has(team.name)}
                                    ]"
                                    :disabled="loadingTeams.has(team.name)">
                                <span class="flex items-center">
                                    <i v-if="loadingTeams.has(team.name)" 
                                       class="mdi mdi-loading mdi-spin mr-1"></i>
                                    ${loadingTeams.has(team.name) ? 'Processing...' : (isTeamRunning(team) ? 'Stop Team' : 'Start Team')}
                                </span>
                            </button>
                            <button @click="activateTeam(team)"
                                    :class="{'bg-green-500': activeTeam?.name === team.name}"
                                    class="px-3 py-1 rounded text-white"
                                    :disabled="activeTeam?.name === team.name">
                            ${activeTeam?.name === team.name ? 'Active' : 'Activate'}
                            </button>
                        </div>
                    </div>
                    
                    <div v-if="teamStats.has(team.name)" class="mb-4">
                        <div class="grid grid-cols-2 gap-4 mb-4">
                            <div class="bg-gray-50 rounded p-3">
                                <div class="text-sm text-gray-500">Success Rate</div>
                                <div class="text-lg font-semibold">
                                    ${formatMetric(teamStats.get(team.name).successRate, 'percentage')}
                                </div>
                            </div>
                            <div class="bg-gray-50 rounded p-3">
                                <div class="text-sm text-gray-500">Response Time</div>
                                <div class="text-lg font-semibold">
                                    ${formatMetric(teamStats.get(team.name).averageResponseTime, 'time')}
                                </div>
                            </div>
                        </div>
                        
                        <div class="relative pt-1">
                            <div class="text-sm text-gray-500 mb-1">Team Efficiency</div>
                            <div class="overflow-hidden h-2 text-xs flex rounded bg-gray-200">
                                <div :style="{ width: getTeamEfficiency(team) + '%' }"
                                     class="shadow-none flex flex-col text-center whitespace-nowrap text-white justify-center bg-blue-500">
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Agents Grid -->
                    <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                        <div v-for="agent in team.agents"
                             :key="agent"
                             class="bg-gray-50 rounded p-3 flex flex-col justify-between">
                            <span class="text-sm font-medium mb-2">${agent}</span>
                            <button @click="toggleAgent(team.name, agent)"
                                    :class="[
                                        getAgentStatusClass(team.name, agent),
                                        {'opacity-75 cursor-wait': loadingAgents.has(team.name + '-' + agent)}
                                    ]"
                                    :disabled="loadingAgents.has(team.name + '-' + agent)"
                                    class="w-full">
                                <span class="flex items-center justify-center">
                                    <i v-if="loadingAgents.has(team.name + '-' + agent)" 
                                       class="mdi mdi-loading mdi-spin mr-1"></i>
                                    ${getAgentStatusText(team.name, agent)}
                                </span>
                            </button>
                        </div>
                    </div>
                    
                    <div v-if="teamHistory.has(team.name)" class="mt-4 text-sm text-gray-500">
                        Last activity: {{ new Date(teamHistory.get(team.name).slice(-1)[0].timestamp).toLocaleString() }}
                    </div>
                    
                    <!-- Add status summary -->
                    <div class="mt-4 text-sm text-gray-500 border-t pt-4">
                        <div class="flex justify-between items-center">
                            <span>Active Agents:</span>
                            <span class="font-medium">
                                {{ team.agents.filter(agent => getAgentStatus(team.name, agent)).length }}/{{ team.agents.length }}
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Add Agent Modal -->
        <div v-if="showAddAgentModal" 
             class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div class="bg-white rounded-lg p-6 w-96 max-w-lg">
                <div class="flex justify-between items-center mb-4">
                    <h3 class="text-lg font-semibold">Add Agent to {{ selectedTeamForEdit?.name }}</h3>
                    <button @click="closeAddAgentModal" class="text-gray-500 hover:text-gray-700">
                        <i class="mdi mdi-close"></i>
                    </button>
                </div>
                
                <div class="mb-4">
                    <label class="block text-sm font-medium text-gray-700 mb-2">
                        Select Agent
                    </label>
                    <select v-model="selectedAgent"
                            class="w-full border rounded-md p-2">
                        <option value="">Choose an agent...</option>
                        <option v-for="agent in getAvailableAgents()"
                                :key="agent"
                                :value="agent">
                            {{ agent }}
                        </option>
                    </select>
                </div>
                
                <div class="flex justify-end space-x-2">
                    <button @click="closeAddAgentModal"
                            class="px-4 py-2 border rounded-md text-gray-600 hover:bg-gray-50">
                        Cancel
                    </button>
                    <button @click="addAgentToTeam"
                            :disabled="!selectedAgent"
                            :class="{'opacity-50 cursor-not-allowed': !selectedAgent}"
                            class="px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600">
                        Add to Team
                    </button>
                </div>
            </div>
        </div>
    `
};