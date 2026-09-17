import { ArrowLeft, ChevronRight, Copy, Download, Loader2, Plus, Trash2, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import JsonViewer from '../../components/JsonViewer'
import Modal from '../../components/Modal'
import { formatDate } from '../../lib/format'
import type { MLDataset, MLDatasetVersion } from '../../types/ml'
import { FileDropzone } from './components'
import { DATASET_TYPE_LABELS, IMPORT_STATUS_LABELS, PUBLISH_LABELS, badgeCls } from './constants'

export default function DatasetDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()

  const [dataset, setDataset] = useState<MLDataset | null>(null)
  const [versions, setVersions] = useState<MLDatasetVersion[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const [uploading, setUploading] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [files, setFiles] = useState<File[]>([])
  const [copied, setCopied] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const load = async () => {
    try {
      const [ds, ver] = await Promise.all([mlApi.getDataset(id), mlApi.listVersions(id)])
      setDataset(ds)
      setVersions(ver.versions)
      setSelectedId((prev) => prev ?? ver.versions[0]?.id ?? null)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  // 版本存在「导入中」状态时轮询刷新，实时展示后端生成进度
  useEffect(() => {
    const hasImporting = versions.some((v) => v.import_status === 'importing')
    if (!hasImporting) return
    const timer = setInterval(async () => {
      try {
        const ver = await mlApi.listVersions(id)
        setVersions(ver.versions)
      } catch {
        // 轮询失败忽略，等待下一轮重试
      }
    }, 5000)
    return () => clearInterval(timer)
  }, [versions, id])

  const selected = versions.find((v) => v.id === selectedId) ?? null

  const copyFileId = async () => {
    if (!selected?.file_id) return
    await navigator.clipboard.writeText(selected.file_id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const handleUpload = async () => {
    if (files.length === 0) {
      window.alert('请选择需要上传的文件')
      return
    }
    setUploading(true)
    try {
      const v = await mlApi.createVersion(id, files)
      setUploadOpen(false)
      setFiles([])
      setSelectedId(v.id)
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  const handleExport = () => {
    if (!selected?.preview_content) {
      window.alert('该版本没有可导出的文本内容')
      return
    }
    const blob = new Blob([selected.preview_content], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${dataset?.name ?? 'dataset'}-v${selected.version}.jsonl`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleConfirmDelete = async () => {
    if (!selected) return
    setDeleting(true)
    try {
      await mlApi.deleteVersion(id, selected.id)
      setDeleteOpen(false)
      setSelectedId(null)
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-24 text-slate-400">
        <Loader2 size={24} className="animate-spin" />
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm">
        <button type="button" onClick={() => navigate('/ml/datasets')} className="flex items-center gap-1 text-slate-400 hover:text-slate-600">
          <ArrowLeft size={15} />
          数据管理
        </button>
        <ChevronRight size={14} className="text-slate-300" />
        <span className="font-medium text-slate-900">{dataset?.name}</span>
      </div>

      <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
        {/* 版本列表 */}
        <aside className="h-fit rounded-xl border border-slate-200 bg-white">
          <div className="flex items-center justify-between border-b border-slate-100 p-4">
            <h3 className="text-sm font-semibold text-slate-700">数据版本</h3>
            <button type="button" onClick={() => { setUploadOpen(true); setFiles([]) }} className="flex items-center gap-1 rounded-md px-2 py-1 text-xs text-indigo-600 hover:bg-indigo-50">
              <Plus size={14} />
              新增
            </button>
          </div>
          <div className="space-y-1.5 p-2">
            {versions.length === 0 ? (
              <p className="py-8 text-center text-xs text-slate-400">暂无版本</p>
            ) : (
              versions.map((v) => (
                <button
                  key={v.id}
                  type="button"
                  onClick={() => setSelectedId(v.id)}
                  className={`w-full rounded-lg border p-3 text-left transition-colors ${selectedId === v.id ? 'border-indigo-300 bg-indigo-50' : 'border-slate-200 hover:bg-slate-50'
                    }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-900">v{v.version}</span>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${badgeCls(v.publish_status)}`}>{PUBLISH_LABELS[v.publish_status] ?? v.publish_status}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-500">{v.data_count} 条数据</div>
                  <div className="mt-0.5 text-xs text-slate-400">{formatDate(v.created_at)}</div>
                </button>
              ))
            )}
          </div>
        </aside>

        {/* 主体 */}
        <section className="flex h-[calc(100vh-12rem)] flex-col overflow-hidden rounded-xl border border-slate-200 bg-white p-5">
          {!selected ? (
            <p className="py-20 text-center text-sm text-slate-400">暂无版本，请点击「新增」上传文件</p>
          ) : (
            <>
              {/* 顶部信息 */}
              <div className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-100 pb-4">
                <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
                  <div>
                    <span className="text-slate-400">发布状态：</span>
                    <span className={`rounded-full px-2 py-0.5 text-xs ${badgeCls(selected.publish_status)}`}>{PUBLISH_LABELS[selected.publish_status] ?? selected.publish_status}</span>
                  </div>
                  <div><span className="text-slate-400">数据量：</span><span className="text-slate-700">{selected.data_count}</span></div>
                  <div><span className="text-slate-400">数据类型：</span><span className="text-slate-700">{dataset ? (DATASET_TYPE_LABELS[dataset.dataset_type] ?? dataset.dataset_type) : '-'}</span></div>
                  <div><span className="text-slate-400">创建时间：</span><span className="text-slate-700">{dataset ? formatDate(dataset.created_at) : '-'}</span></div>
                  <div><span className="text-slate-400">导入状态：</span><span className={`rounded-full px-2 py-0.5 text-xs ${badgeCls(selected.import_status)}`}>{IMPORT_STATUS_LABELS[selected.import_status] ?? selected.import_status}</span></div>
                  <div className="flex items-center gap-1">
                    <span className="text-slate-400">File ID：</span>
                    <span className="font-mono text-xs text-slate-700">{selected.file_id}</span>
                    <button type="button" onClick={copyFileId} className="rounded p-0.5 text-slate-400 hover:text-indigo-600" title="复制">
                      <Copy size={13} />
                    </button>
                    {copied && <span className="text-xs text-green-600">已复制</span>}
                  </div>
                </div>
                <div className="flex gap-2">
                  <button type="button" onClick={handleExport} disabled={!selected} className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50">
                    <Download size={14} />
                    导出
                  </button>
                  <button type="button" onClick={() => setDeleteOpen(true)} disabled={!selected} className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-1.5 text-sm text-red-500 hover:bg-red-50 disabled:opacity-50">
                    <Trash2 size={14} />
                    删除
                  </button>
                </div>
              </div>

              {/* 预览（JSON 高亮 + 折叠 + 行号） */}
              <div className="mt-4 flex min-h-0 flex-1 flex-col">
                <p className="mb-3 text-xs text-slate-400">仅支持预览 100KB 内容，完整内容需导出查看</p>
                <div className="min-h-0 flex-1 overflow-auto rounded-xl bg-slate-50">
                  <JsonViewer content={selected.preview_content} />
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      {/* 新增版本 */}
      <Modal open={uploadOpen} title="新增数据版本" onClose={() => setUploadOpen(false)}>
        <div className="space-y-4">
          <FileDropzone files={files} onChange={setFiles} />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setUploadOpen(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
              取消
            </button>
            <button type="button" onClick={handleUpload} disabled={uploading} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60">
              {uploading && <Loader2 size={14} className="animate-spin" />}
              <Upload size={14} />
              上传
            </button>
          </div>
        </div>
      </Modal>

      {/* 删除版本确认 */}
      <Modal open={deleteOpen} title="删除版本" onClose={() => setDeleteOpen(false)}>
        <div className="space-y-4">
          <p className="text-sm text-slate-700">
            确定删除数据集「{dataset?.name}」的版本 v{selected?.version} 吗？此操作不可恢复。
          </p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setDeleteOpen(false)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
              取消
            </button>
            <button type="button" onClick={handleConfirmDelete} disabled={deleting} className="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700 disabled:opacity-60">
              {deleting && <Loader2 size={14} className="animate-spin" />}
              确认删除
            </button>
          </div>
        </div>
      </Modal>
    </div>
  )
}