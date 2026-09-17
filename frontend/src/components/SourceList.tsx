import { useState } from 'react'
import type { Citation } from '../types'

interface SourceListProps {
  citations?: Citation[]
}

// 回答下方的引用来源折叠列表：默认收起，点击展开
export default function SourceList({ citations }: SourceListProps) {
  const [open, setOpen] = useState(false)

  if (!citations || citations.length === 0) return null

  return (
    <div className="mt-1.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-xs text-slate-500 transition-colors hover:text-indigo-600"
      >
        <span className="inline-block w-3">{open ? '▾' : '>'}</span>
        来源片段（{citations.length}）
      </button>
      {open && (
        <div className="mt-1.5 space-y-1">
          {citations.map((c, i) => (
            <div
              key={i}
              className="rounded-lg border border-slate-200 bg-white px-2 py-1 text-xs text-slate-500"
            >
              <span className="font-medium text-slate-700">来源：{c.filename || '文档#' + i}</span>
              <span className="ml-1 opacity-70">（相关度 {(c.score * 100).toFixed(0)}%）</span>
              <p className="mt-0.5 line-clamp-2 text-slate-500">{c.content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}