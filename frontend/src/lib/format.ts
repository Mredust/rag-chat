export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function formatDate(value: string): string {
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

const STATUS_COLORS: Record<string, string> = {
  待处理: 'bg-slate-100 text-slate-600',
  解析中: 'bg-blue-100 text-blue-700',
  切片中: 'bg-amber-100 text-amber-700',
  向量化中: 'bg-violet-100 text-violet-700',
  已完成: 'bg-green-100 text-green-700',
  失败: 'bg-red-100 text-red-700',
}

export function statusClass(status: string): string {
  return STATUS_COLORS[status] ?? 'bg-slate-100 text-slate-600'
}