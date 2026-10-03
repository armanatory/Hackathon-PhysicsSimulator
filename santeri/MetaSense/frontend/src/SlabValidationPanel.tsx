import { useEffect, useState } from 'react'
import { getSlabValidation } from './api'
import type { SlabValidation } from './types'

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function format(value: unknown, digits = 4): string {
  const numeric = number(value)
  return numeric === null ? '—' : numeric.toFixed(digits)
}

function projectLink(value: unknown): string | null {
  if (typeof value !== 'string') return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null
  } catch {
    return null
  }
}

function caseName(value: string): string {
  return value === 'vacuum_control' ? 'Vacuum control' : value === 'dielectric_slab' ? 'Dielectric slab' : value.replace(/_/g, ' ')
}

export default function SlabValidationPanel() {
  const [report, setReport] = useState<SlabValidation | null>(null)
  const [refreshError, setRefreshError] = useState('')

  useEffect(() => {
    let active = true
    let inFlight = false
    let controller: AbortController | null = null
    async function refresh() {
      if (inFlight) return
      inFlight = true
      controller = new AbortController()
      try {
        const updated = await getSlabValidation(controller.signal)
        if (active) { setReport(updated); setRefreshError('') }
      } catch (cause) {
        if (active) setRefreshError(cause instanceof Error ? cause.message : 'Could not refresh the optical validation report.')
      } finally {
        inFlight = false
      }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 10_000)
    return () => { active = false; window.clearInterval(timer); controller?.abort() }
  }, [])

  const passed = report?.validated === true
  const failed = report?.status === 'failed' || (report?.status === 'completed' && !passed)
  const badge = passed ? 'Passed' : failed ? 'Failed' : report?.status === 'unverified' ? 'Unverified' : report ? 'Pending' : refreshError ? 'Unavailable' : 'Checking'
  const provenance = record(report?.state_provenance)
  const inputs = record(report?.inputs ?? provenance.inputs)
  const references = record(report?.analytical_reference)
  const slabReference = record(references.dielectric_slab)
  const wavelength = number(report?.wavelength_nm) ?? (number(inputs.wavelength_m) === null ? null : Number(inputs.wavelength_m) * 1e9)
  const thickness = number(report?.slab_thickness_nm) ?? (number(inputs.slab_thickness_m) === null ? null : Number(inputs.slab_thickness_m) * 1e9)
  const slabIndex = number(report?.slab_index) ?? number(slabReference.n_slab)
  const indices = Array.isArray(inputs.indices) ? inputs.indices.filter((value): value is number => number(value) !== null) : []
  const link = projectLink(report?.project_url) ?? projectLink(provenance.project_url)
  const runs = report?.runs ?? []
  const rows = runs.flatMap((run, runIndex) => Object.entries(record(run.cases)).map(([key, rawCase]) => {
    const result = record(rawCase)
    return {
      key: `${runIndex}-${key}`,
      run: text(run.name) ?? `Run ${runIndex + 1}`,
      case: caseName(key),
      numerical: record(result.numerical),
      analytical: record(references[key]),
      passed: result.passed === true,
      evaluated: Object.values(record(result.checks)).some(value => typeof value === 'boolean'),
    }
  }))
  const reportError = text(report?.error) ?? (Array.isArray(report?.errors) ? report.errors.map(text).find((value): value is string => value !== null) : null)
  const statusText = passed
    ? 'The slab benchmark passed its recorded checks. Metasurface sensing and protein detection still require their own validation.'
    : failed
      ? 'The slab benchmark did not pass. Review the cloud results and validation checks before using the optical workflow.'
      : report?.status === 'not_run'
        ? 'No slab benchmark report is available yet. Cloud provenance and power outputs will appear here after a benchmark run.'
        : report?.status === 'unverified'
          ? 'The slab report could not be verified. Validation remains pending.'
          : !report
            ? refreshError ? 'The validation report is currently unavailable. No benchmark result can be verified.' : 'Loading the slab benchmark status.'
            : 'Checking normal-incidence excitation and reflected/transmitted power against a dielectric slab Fresnel reference.'

  return <section className="panel slab-panel" aria-labelledby="slab-validation-title">
    <div className="slab-heading"><div><span className="eyebrow">ALLSOLVE · DIELECTRIC SLAB</span><h3 id="slab-validation-title">Optical validation</h3></div><span className={`slab-status ${passed ? 'passed' : failed ? 'failed' : 'pending'}`}>{badge}</span></div>
    <p className="slab-description">{statusText}</p>
    <dl className="slab-inputs">
      <div><dt>Wavelength</dt><dd>{format(wavelength, 1)} <span>nm</span></dd></div>
      <div><dt>{slabIndex === null ? 'Refractive indices' : 'Slab index'}</dt><dd>{slabIndex === null ? indices.length ? indices.join(' / ') : '—' : format(slabIndex, 2)}</dd></div>
      <div><dt>Slab thickness</dt><dd>{format(thickness, 1)} <span>nm</span></dd></div>
    </dl>
    {rows.length > 0 ? <div className="slab-table-wrap"><table className="slab-table"><caption>Power fractions from cloud jobs compared with the analytical reference</caption><thead><tr><th scope="col">Run / case</th><th scope="col">R · Allsolve</th><th scope="col">R · Fresnel</th><th scope="col">T · Allsolve</th><th scope="col">T · Fresnel</th><th scope="col">Checks</th></tr></thead><tbody>{rows.map(row => <tr key={row.key}><th scope="row"><span>{row.run}</span>{row.case}</th><td>{format(row.numerical.R)}</td><td>{format(row.analytical.R)}</td><td>{format(row.numerical.T)}</td><td>{format(row.analytical.T)}</td><td>{row.passed ? 'Passed' : row.evaluated ? 'Failed' : 'Pending'}</td></tr>)}</tbody></table></div> : <p className="slab-awaiting">No verified power outputs are available.</p>}
    {runs.length > 0 && <div className="slab-runs">{runs.map((run, index) => {
      const metadata = { ...run, ...record(run.metadata) }
      const ids = [['Mesh', metadata.mesh_id], ['Mesh job', metadata.mesh_job_id], ['Simulation', metadata.simulation_id], ['Simulation job', metadata.simulation_job_id ?? metadata.job_id]]
      return <div className="slab-run" key={`${text(run.name) ?? 'run'}-${index}`}><div><strong>{text(run.name) ?? `Run ${index + 1}`}</strong><span>{text(run.simulation_status) ?? text(run.status) ?? text(metadata.simulation_status) ?? 'Pending'}</span></div>{ids.map(([label, value]) => text(value) && <p key={String(label)}><span>{String(label)}</span><code>{String(value)}</code></p>)}</div>
    })}</div>}
    {reportError && <div className="slab-error" role="status">{reportError.slice(0, 300)}</div>}
    {refreshError && <div className="slab-error" role="status">Refresh failed{report ? ' · Showing the last available report' : ''}. {refreshError}</div>}
    <div className="slab-footer"><span>Slab benchmark only · refreshes every 10 seconds</span>{link && <a href={link} target="_blank" rel="noreferrer">Open Allsolve project ↗</a>}</div>
  </section>
}
