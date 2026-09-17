import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

export interface MultiSelectOption {
  value: string
  label: string
}

interface MultiSelectProps {
  value: string[]
  options: MultiSelectOption[]
  onChange: (value: string[]) => void
  placeholder?: string
  className?: string
}

export default function MultiSelect({ value, options, onChange, placeholder = '请选择', className = '' }: MultiSelectProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [])

  // 已选项按 value（用户选择顺序）渲染，而非 options 顺序
  const selected = value
    .map((v) => options.find((o) => o.value === v))
    .filter((o): o is MultiSelectOption => o !== undefined)

  const toggle = (v: string) => {
    onChange(value.includes(v) ? value.filter((x) => x !== v) : [...value, v])
  }

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full items-center justify-between gap-2 rounded-lg border bg-white px-3 py-2 text-left text-sm outline-none transition-colors focus:border-indigo-500 ${open ? 'border-indigo-500 ring-2 ring-indigo-100' : 'border-slate-300'
          }`}
      >
        <span className="flex min-h-[20px] flex-wrap items-center gap-1">
          {selected.length === 0 ? (
            <span className="text-slate-400">{placeholder}</span>
          ) : (
            selected.map((o) => (
              <span key={o.value} className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs text-indigo-700">
                {o.label}
              </span>
            ))
          )}
        </span>
        <ChevronDown size={16} className={`shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && (
        <ul className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          {options.map((o) => {
            const active = value.includes(o.value)
            return (
              <li key={o.value}>
                <button
                  type="button"
                  onClick={() => toggle(o.value)}
                  className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors hover:bg-indigo-50 ${active ? 'bg-indigo-50 font-medium text-indigo-700' : 'text-slate-700'
                    }`}
                >
                  <span className="truncate">{o.label}</span>
                  <span className={`flex h-4 w-4 items-center justify-center rounded border ${active ? 'border-indigo-600 bg-indigo-600 text-white' : 'border-slate-300'}`}>
                    {active && <Check size={12} />}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}