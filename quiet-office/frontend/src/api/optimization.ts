/**
 * API client for the QuietOffice backend
 */

import type {
  Capabilities,
  LogEntry,
  Office,
  OptimizationParams,
  OptimizationResponse,
  OptimizationResults,
  OptimizationStatus,
} from '@/types'

const API_BASE = '/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      // keep the status text
    }
    throw new Error(detail)
  }
  return response.json()
}

class OptimizationAPI {
  /** Whether the backend can run real Allsolve simulations */
  getCapabilities(): Promise<Capabilities> {
    return request('/capabilities')
  }

  /** The demo office layout */
  getDefaultOffice(): Promise<Office> {
    return request('/office/default')
  }

  /** Start a layout search on Allsolve */
  start(params: OptimizationParams): Promise<OptimizationResponse> {
    return request('/optimization/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    })
  }

  getStatus(id: string): Promise<OptimizationStatus> {
    return request(`/optimization/${id}/status`)
  }

  getResults(id: string): Promise<OptimizationResults> {
    return request(`/optimization/${id}/results`)
  }

  /** Run log entries from `since` on: what was sent to Allsolve and what came back */
  getLog(id: string, since: number): Promise<{ entries: LogEntry[] }> {
    return request(`/optimization/${id}/log?since=${since}`)
  }

  /** Plain-language explanation written by an AI model from the facts given */
  explain(context: Record<string, unknown>, optimizationId: string | null): Promise<{ text: string; model: string }> {
    return request('/explain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ optimization_id: optimizationId, context }),
    })
  }

  abort(id: string): Promise<{ status: string; message: string }> {
    return request(`/optimization/${id}/abort`, { method: 'POST' })
  }
}

export const optimizationApi = new OptimizationAPI()
