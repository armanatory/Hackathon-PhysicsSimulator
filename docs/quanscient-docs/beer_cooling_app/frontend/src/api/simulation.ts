/**
 * API client for the Beer Cooling Simulation backend
 */

import type {
  SimulationParams,
  SimulationResponse,
  SimulationStatus,
  SimulationResults,
} from '@/types'

const API_BASE = '/api/simulation'

class SimulationAPI {
  /**
   * Start a new simulation with the given parameters
   */
  async start(params: SimulationParams): Promise<SimulationResponse> {
    const response = await fetch(`${API_BASE}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })

    if (!response.ok) {
      throw new Error(`Failed to start simulation: ${response.statusText}`)
    }

    return response.json()
  }

  /**
   * Get the current status of a simulation
   */
  async getStatus(simulationId: string): Promise<SimulationStatus> {
    const response = await fetch(`${API_BASE}/${simulationId}/status`)

    if (!response.ok) {
      throw new Error(`Failed to get status: ${response.statusText}`)
    }

    return response.json()
  }

  /**
   * Get the results of a completed simulation
   */
  async getResults(simulationId: string): Promise<SimulationResults> {
    const response = await fetch(`${API_BASE}/${simulationId}/results`)

    if (!response.ok) {
      throw new Error(`Failed to get results: ${response.statusText}`)
    }

    return response.json()
  }

  /**
   * Abort a running simulation
   */
  async abort(simulationId: string): Promise<{ status: string; message: string }> {
    const response = await fetch(`${API_BASE}/${simulationId}/abort`, {
      method: 'POST',
    })

    if (!response.ok) {
      throw new Error(`Failed to abort simulation: ${response.statusText}`)
    }

    return response.json()
  }

  /**
   * Run a demo simulation (no backend required)
   */
  async runDemo(params: SimulationParams): Promise<SimulationResults> {
    const response = await fetch(`${API_BASE}/demo/demo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })

    if (!response.ok) {
      throw new Error(`Failed to run demo: ${response.statusText}`)
    }

    return response.json()
  }

  /**
   * Create a WebSocket connection for real-time updates
   */
  connectWebSocket(
    simulationId: string,
    onMessage: (data: Record<string, unknown>) => void,
    onError?: (error: Event) => void
  ): WebSocket {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    const ws = new WebSocket(`${protocol}//${host}${API_BASE}/${simulationId}/ws`)

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        onMessage(data)
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
      onError?.(error)
    }

    // Send ping every 25 seconds to keep connection alive
    const pingInterval = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send('ping')
      }
    }, 25000)

    ws.onclose = () => {
      clearInterval(pingInterval)
    }

    return ws
  }
}

export const simulationApi = new SimulationAPI()

