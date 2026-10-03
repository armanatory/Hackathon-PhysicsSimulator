/**
 * Keeps the opened scan in this browser, so a page reload shows it again.
 *
 * The file itself goes into IndexedDB, which takes large files; how it is placed on the plan
 * goes into localStorage. Every call fails quietly: without storage the scan is just not kept.
 */

import type { Orientation } from './glb'

export interface ScanView {
  name: string
  orientation: Orientation
  angle: number
  sliceHeight: number
}

const DB_NAME = 'quietoffice'
const STORE = 'scan'
const FILE_KEY = 'file'
const VIEW_KEY = 'quietoffice.scan.v1'

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1)
    request.onupgradeneeded = () => request.result.createObjectStore(STORE)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error)
  })
}

async function withStore<T>(mode: IDBTransactionMode, work: (store: IDBObjectStore) => IDBRequest<T>): Promise<T | null> {
  try {
    const db = await open()
    return await new Promise<T>((resolve, reject) => {
      const request = work(db.transaction(STORE, mode).objectStore(STORE))
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  } catch {
    return null
  }
}

export function saveScanFile(buffer: ArrayBuffer): void {
  void withStore('readwrite', (store) => store.put(buffer, FILE_KEY))
}

export async function loadScanFile(): Promise<ArrayBuffer | null> {
  const buffer = await withStore<unknown>('readonly', (store) => store.get(FILE_KEY))
  return buffer instanceof ArrayBuffer ? buffer : null
}

export function saveScanView(view: ScanView): void {
  try {
    localStorage.setItem(VIEW_KEY, JSON.stringify(view))
  } catch {
    // storage blocked
  }
}

export function loadScanView(): ScanView | null {
  try {
    const view = JSON.parse(localStorage.getItem(VIEW_KEY) ?? 'null')
    return view && view.orientation && typeof view.angle === 'number' ? (view as ScanView) : null
  } catch {
    return null
  }
}

export function forgetScan(): void {
  void withStore('readwrite', (store) => store.delete(FILE_KEY))
  try {
    localStorage.removeItem(VIEW_KEY)
  } catch {
    // storage blocked
  }
}
