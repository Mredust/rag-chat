import { FileText, Upload, X } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'

// 单选卡片
export interface CardOption {
  value: string
  label: string
  desc?: string
}

export function CardRadio({
  options,
  value,
  onChange,
  columns = 3,
}: {
  options: CardOption[]
  value: string
  onChange: (v: string) => void
  columns?: number
}) {
  return (
    <div className={`grid gap-3 ${columns === 3 ? 'sm:grid-cols-3' : columns === 4 ? 'sm:grid-cols-4' : 'sm:grid-cols-2'}`}>
      {options.map((o) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={`rounded-xl border p-4 text-left transition-colors ${active ? 'border-indigo-500 bg-indigo-50 ring-1 ring-indigo-200' : 'border-slate-200 bg-white hover:border-slate-300'
              }`}
          >
            <div className={`text-sm font-medium ${active ? 'text-indigo-700' : 'text-slate-800'}`}>{o.label}</div>
            {o.desc && <div className="mt-1 text-xs leading-relaxed text-slate-500">{o.desc}</div>}
          </button>
        )
      })}
    </div>
  )
}

// 文件拖拽上传区（多文件）
export function FileDropzone({
  files,
  onChange,
  accept = '.jsonl',
  maxFiles = 10,
}: {
  files: File[]
  onChange: (files: File[]) => void
  accept?: string
  maxFiles?: number
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const addFiles = useCallback(
    (incoming: FileList | null) => {
      if (!incoming) return
      const next = [...files]
      for (const f of Array.from(incoming)) {
        if (next.length >= maxFiles) break
        if (!next.some((x) => x.name === f.name && x.size === f.size)) next.push(f)
      }
      onChange(next)
    },
    [files, maxFiles, onChange],
  )

  const removeFile = (name: string) => onChange(files.filter((f) => f.name !== name))

  return (
    <div>
      <div
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          addFiles(e.dataTransfer.files)
        }}
        className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors ${dragging ? 'border-indigo-400 bg-indigo-50' : 'border-slate-300 bg-slate-50 hover:border-indigo-300'
          }`}
      >
        <Upload size={28} className="mb-2 text-slate-400" />
        <p className="text-sm text-slate-600">拖拽文件到此处，或点击上传</p>
        <p className="mt-1 text-xs text-slate-400">
          支持 {accept} · 最多 {maxFiles} 个文件 · 单个文件最大 200MB
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={accept}
          className="hidden"
          onChange={(e) => {
            addFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-3 space-y-2">
          {files.map((f) => (
            <li key={f.name} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
              <FileText size={16} className="shrink-0 text-indigo-500" />
              <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{f.name}</span>
              <span className="shrink-0 text-xs text-slate-400">{(f.size / 1024).toFixed(1)} KB</span>
              <button type="button" onClick={() => removeFile(f.name)} className="shrink-0 rounded p-1 text-slate-400 hover:text-red-600">
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}