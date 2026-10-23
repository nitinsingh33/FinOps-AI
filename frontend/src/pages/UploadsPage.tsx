import { useState, useRef, type DragEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Upload, FileSpreadsheet, CheckCircle2, XCircle, Clock, RefreshCw } from 'lucide-react'
import { fetchUploads, uploadDataset } from '../api/client'
import { formatBytes, formatDate, jobStatusClass } from '../lib/format'
import type { UploadedDataset } from '../types'

const DATASET_TYPES = [
  { value: 'gwa_payments', label: 'Gateway A — Payments' },
  { value: 'gwa_transactions', label: 'Gateway A — Transactions' },
  { value: 'gwa_refunds', label: 'Gateway A — Refunds' },
  { value: 'gwb_balance', label: 'Gateway B — Balance' },
]

export default function UploadsPage() {
  const queryClient = useQueryClient()
  const [datasetType, setDatasetType] = useState('gwa_payments')
  const [file, setFile] = useState<File | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const [uploadResult, setUploadResult] = useState<{ success: boolean; message: string } | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const { data: uploads, isLoading } = useQuery({
    queryKey: ['uploads'],
    queryFn: fetchUploads,
    refetchInterval: 10_000,
  })

  const mutation = useMutation({
    mutationFn: (fd: FormData) => uploadDataset(fd),
    onSuccess: (data) => {
      setUploadResult({ success: true, message: data.message ?? 'Upload successful' })
      setFile(null)
      queryClient.invalidateQueries({ queryKey: ['uploads'] })
    },
    onError: (err: unknown) => {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? 'Upload failed'
      setUploadResult({ success: false, message: msg })
    },
  })

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    const dropped = e.dataTransfer.files[0]
    if (dropped) setFile(dropped)
  }

  const handleSubmit = () => {
    if (!file) return
    const fd = new FormData()
    fd.append('file', file)
    fd.append('dataset_type', datasetType)
    setUploadResult(null)
    mutation.mutate(fd)
  }

  const datasets: UploadedDataset[] = uploads ?? []

  return (
    <div className="page-wrapper">
      <div className="page-header">
        <h1 className="page-title">Data Uploads</h1>
        <p className="page-subtitle">Import gateway Excel files for reconciliation processing</p>
      </div>

      {/* Upload panel */}
      <div className="card mb-8">
        <div className="card-header">
          <span className="card-title">
            <Upload size={16} color="var(--color-accent)" />
            Upload Dataset
          </span>
        </div>
        <div className="card-body">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 32 }}>
            {/* Dropzone */}
            <div>
              <div
                className={`upload-dropzone${dragOver ? ' dragover' : ''}`}
                onClick={() => inputRef.current?.click()}
                onDragOver={e => { e.preventDefault(); setDragOver(true) }}
                onDragLeave={() => setDragOver(false)}
                onDrop={handleDrop}
              >
                <input
                  ref={inputRef}
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  style={{ display: 'none' }}
                  onChange={e => setFile(e.target.files?.[0] ?? null)}
                />
                <div className="upload-dropzone-icon">
                  {file ? '📎' : '📂'}
                </div>
                {file ? (
                  <>
                    <div className="upload-dropzone-text">{file.name}</div>
                    <div className="upload-dropzone-sub">{formatBytes(file.size)}</div>
                  </>
                ) : (
                  <>
                    <div className="upload-dropzone-text">Drop file here or click to browse</div>
                    <div className="upload-dropzone-sub">Supports .xlsx, .xls, .csv — max 50 MB</div>
                  </>
                )}
              </div>
            </div>

            {/* Config */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
              <div className="form-group">
                <label className="form-label">Dataset Type</label>
                <select
                  className="form-select"
                  value={datasetType}
                  onChange={e => setDatasetType(e.target.value)}
                >
                  {DATASET_TYPES.map(dt => (
                    <option key={dt.value} value={dt.value}>{dt.label}</option>
                  ))}
                </select>
              </div>

              {uploadResult && (
                <div style={{
                  padding: '12px 16px',
                  borderRadius: 10,
                  background: uploadResult.success ? 'var(--color-success-dim)' : 'var(--color-danger-dim)',
                  border: `1px solid ${uploadResult.success ? 'rgba(16,185,129,0.2)' : 'rgba(239,68,68,0.2)'}`,
                  color: uploadResult.success ? 'var(--color-success)' : 'var(--color-danger)',
                  fontSize: 13,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                }}>
                  {uploadResult.success ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
                  {uploadResult.message}
                </div>
              )}

              <button
                className="btn btn-primary btn-lg"
                onClick={handleSubmit}
                disabled={!file || mutation.isPending}
              >
                {mutation.isPending
                  ? <><span className="spinner" />Uploading…</>
                  : <><Upload size={16} />Upload &amp; Import</>
                }
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Uploaded datasets table */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">
            <FileSpreadsheet size={16} color="var(--color-accent-2)" />
            Uploaded Datasets
          </span>
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => queryClient.invalidateQueries({ queryKey: ['uploads'] })}
          >
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
        <div className="table-container" style={{ border: 'none', borderRadius: 0 }}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Filename</th>
                <th>Type</th>
                <th>Gateway</th>
                <th>Size</th>
                <th>Jobs</th>
                <th>Last Import Status</th>
                <th>Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={7} style={{ textAlign: 'center', padding: 40 }}><span className="spinner" /></td></tr>
              ) : datasets.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <div className="empty-state" style={{ padding: '40px 0' }}>
                      <div className="empty-state-icon">📁</div>
                      <p className="empty-state-title">No datasets yet</p>
                      <p className="empty-state-desc">Upload a gateway file to get started.</p>
                    </div>
                  </td>
                </tr>
              ) : datasets.map(ds => {
                const lastJob = ds.import_jobs?.[0]
                return (
                  <tr key={ds.id}>
                    <td style={{ maxWidth: 220 }}>
                      <div className="truncate" title={ds.filename}>{ds.filename}</div>
                    </td>
                    <td>
                      <span className="badge badge-info">{ds.dataset_type}</span>
                    </td>
                    <td className="text-sm text-muted">{ds.gateway}</td>
                    <td className="td-mono">{formatBytes(ds.file_size_bytes)}</td>
                    <td className="text-sm">{ds.import_jobs?.length ?? 0}</td>
                    <td>
                      {lastJob
                        ? <span className={`badge ${jobStatusClass(lastJob.status)}`}>{lastJob.status}</span>
                        : '—'
                      }
                    </td>
                    <td className="text-sm text-muted">{formatDate(ds.created_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
