import { useMemo, useState } from 'react'

type Line =
  | { kind: 'opening'; depth: number; id: string; key: string | null; bracket: '[' | '{' }
  | { kind: 'collapsed'; depth: number; id: string; key: string | null; bracket: '[' | '{' }
  | { kind: 'closing'; depth: number; id: string; bracket: ']' | '}'; comma: boolean }
  | { kind: 'primitive'; depth: number; id: string; key: string | null; text: string; comma: boolean }
  | { kind: 'empty'; depth: number; id: string; key: string | null; text: string }

interface Root {
  ok: boolean
  data?: unknown
  raw?: string
}

function stringify(value: unknown): string {
  if (typeof value === 'string') return JSON.stringify(value)
  if (value === null || value === undefined) return 'null'
  return String(value)
}

function buildLines(roots: Root[], collapsed: Set<string>): Line[] {
  const lines: Line[] = []

  const walk = (value: unknown, key: string | null, depth: number, id: string) => {
    if (value !== null && typeof value === 'object') {
      const isArray = Array.isArray(value)
      const entries: Array<[string, unknown]> = isArray
        ? (value as unknown[]).map((v, i) => [String(i), v])
        : Object.entries(value as Record<string, unknown>)
      const openBracket: '[' | '{' = isArray ? '[' : '{'
      const closeBracket: ']' | '}' = isArray ? ']' : '}'

      if (entries.length === 0) {
        lines.push({ kind: 'empty', depth, id, key, text: openBracket + closeBracket })
        return
      }
      if (collapsed.has(id)) {
        lines.push({ kind: 'collapsed', depth, id, key, bracket: openBracket })
        return
      }
      lines.push({ kind: 'opening', depth, id, key, bracket: openBracket })
      entries.forEach(([k, v], i) => {
        walk(v, isArray ? null : k, depth + 1, `${id}.${k}`)
        if (i < entries.length - 1) {
          const last = lines[lines.length - 1]
          if (last.kind === 'primitive' || last.kind === 'closing') last.comma = true
        }
      })
      lines.push({ kind: 'closing', depth, id, bracket: closeBracket, comma: false })
    } else {
      lines.push({ kind: 'primitive', depth, id, key, text: stringify(value), comma: false })
    }
  }

  roots.forEach((root, i) => {
    if (root.ok) walk(root.data, null, 0, `$${i}`)
    else lines.push({ kind: 'primitive', depth: 0, id: `$${i}`, key: null, text: root.raw ?? '', comma: false })
  })

  return lines
}

function renderKey(key: string | null) {
  if (key === null) return null
  return (
    <>
      <span className="text-blue-400">{JSON.stringify(key)}</span>
      <span className="text-slate-500">: </span>
    </>
  )
}

export default function JsonViewer({ content }: { content: string }) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const roots: Root[] = useMemo(
    () =>
      (content || '')
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line.length > 0)
        .map((line) => {
          try {
            return { ok: true, data: JSON.parse(line) } as Root
          } catch {
            return { ok: false, raw: line } as Root
          }
        }),
    [content],
  )

  const lines = useMemo(() => buildLines(roots, collapsed), [roots, collapsed])

  const toggle = (id: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="py-3 font-mono text-xs leading-6">
      {lines.map((line, idx) => {
        const pad = { paddingLeft: line.depth * 16 }
        const gutter = (
          <span className="w-10 shrink-0 select-none pr-3 text-right text-slate-400">
            {idx + 1}
          </span>
        )

        if (line.kind === 'opening' || line.kind === 'collapsed') {
          const isCollapsed = line.kind === 'collapsed'
          return (
            <div key={line.id + ':' + line.kind} className="flex hover:bg-slate-100">
              {gutter}
              <div style={pad} className="min-w-0 flex-1 break-all">
                <button
                  type="button"
                  onClick={() => toggle(line.id)}
                  className="mr-1 inline-block select-none align-middle text-slate-500 hover:text-indigo-600"
                >
                  {isCollapsed ? '▸' : '▾'}
                </button>
                {renderKey(line.key)}
                <span className="text-slate-500">{line.bracket}</span>
                {isCollapsed && (
                  <>
                    <span className="mx-1 text-slate-400">…</span>
                    <span className="text-slate-500">{line.bracket === '[' ? ']' : '}'}</span>
                  </>
                )}
              </div>
            </div>
          )
        }

        if (line.kind === 'closing') {
          return (
            <div key={line.id + ':closing'} className="flex hover:bg-slate-100">
              {gutter}
              <div style={pad} className="min-w-0 flex-1 break-all">
                <span className="text-slate-500">{line.bracket}</span>
                {line.comma && <span className="text-slate-500">,</span>}
              </div>
            </div>
          )
        }

        if (line.kind === 'empty') {
          return (
            <div key={line.id + ':empty'} className="flex hover:bg-slate-100">
              {gutter}
              <div style={pad} className="min-w-0 flex-1 break-all">
                {renderKey(line.key)}
                <span className="text-slate-500">{line.text}</span>
              </div>
            </div>
          )
        }

        return (
          <div key={line.id + ':primitive'} className="flex hover:bg-slate-100">
            {gutter}
            <div style={pad} className="min-w-0 flex-1 break-all">
              {renderKey(line.key)}
              <span className="text-red-700">{line.text}</span>
              {line.comma && <span className="text-slate-500">,</span>}
            </div>
          </div>
        )
      })}
    </div>
  )
}