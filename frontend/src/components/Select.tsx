import { Check, ChevronDown } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

export interface SelectOption {
  value: string
  label: string
  hint?: string
}

interface SelectProps {
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}

// 原生 <select>/<option> 的下拉弹层无法被 CSS 覆盖样式，故使用自定义下拉组件
export default function Select({ value, options, onChange, placeholder, className = '' }: SelectProps) {
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

  const selected = options.find((o) => o.value === value)

  return (
    <div ref={ref} className={`relative ${className}`}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={`flex w-full items-center justify-between gap-2 rounded-lg border bg-white px-3 py-2 text-left text-sm outline-none transition-colors focus:border-indigo-500 ${open ? 'border-indigo-500 ring-2 ring-indigo-100' : 'border-slate-300'
          } ${selected ? 'text-slate-700' : 'text-slate-400'}`}
      >
        <span className="truncate">{selected ? selected.label : placeholder ?? '请选择'}</span>
        <ChevronDown
          size={16}
          className={`shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <ul className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-lg">
          {options.map((o) => {
            const active = o.value === value
            return (
              <li key={o.value}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(o.value)
                    setOpen(false)
                  }}
                  className={`flex w-full items-center justify-between px-3 py-2 text-left text-sm transition-colors hover:bg-indigo-50 ${active ? 'bg-indigo-50 font-medium text-indigo-700' : 'text-slate-700'
                    }`}
                >
                  <span className="truncate">{o.label}</span>
                  <span className="flex shrink-0 items-center gap-1.5">
                    {o.hint && <span className="text-xs text-slate-400">{o.hint}</span>}
                    {active && <Check size={16} className="shrink-0" />}
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