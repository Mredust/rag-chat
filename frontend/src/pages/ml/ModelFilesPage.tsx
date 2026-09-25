import { ArrowLeft, ChevronRight, Eye, FileText, FolderOpen, Loader2, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import Modal from '../../components/Modal'
import { formatSize } from '../../lib/format'
import type { MLModelFile, MLModelFileContent, MLModelFileList } from '../../types/ml'

export default function ModelFilesPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const modelName = (location.state as { name?: string } | null)?.name ?? ''

  const [data, setData] = useState<MLModelFileList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [previewFile, setPreviewFile] = useState<MLModelFile | null>(null)
  const [preview, setPreview] = useState<MLModelFileContent | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [previewError, setPreviewError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await mlApi.listModelFiles(id)
      setData(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载文件列表失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const openPreview = async (file: MLModelFile) => {
    setPreviewFile(file)
    setPreview(null)
    setPreviewError('')
    setPreviewLoading(true)
    try {
      const res = await mlApi.readModelFile(id, file.path)
      setPreview(res)
    } catch (err) {
      setPreviewError(err instanceof Error ? err.message : '读取文件失败')
    } finally {
      setPreviewLoading(false)
    }
  }

  return (
    <div>
      {/* 面包屑 */}
      <div className="mb-4 flex items-center gap-2 text-sm">
        <button
          type="button"
          onClick={() => navigate('/ml/models')}
          className="flex items-center gap-1 text-slate-400 hover:text-slate-600"
        >
          <ArrowLeft size={15} />
          我的模型
        </button>
        <ChevronRight size={14} className="text-slate-300" />
        <span className="font-medium text-slate-900">{modelName || '模型文件'}</span>
      </div>

      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold text-slate-900">模型文件</h2>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            {data?.file_count ?? 0} 个文件
          </span>
        </div>
        <button
          type="button"
          onClick={load}
          className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
        >
          <RefreshCw size={14} />
          刷新
        </button>
      </div>

      {/* 目录与总大小 */}
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs text-slate-400">文件数量</p>
          <p className="mt-1 text-xl font-semibold text-slate-900">{data?.file_count ?? 0}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs text-slate-400">总大小</p>
          <p className="mt-1 text-xl font-semibold text-slate-900">
            {data ? `${data.total_size_mb} MB` : '-'}
            {data && data.total_size > 0 && (
              <span className="ml-2 text-xs font-normal text-slate-400">（{formatSize(data.total_size)}）</span>
            )}
          </p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs text-slate-400">目录</p>
          <p className="mt-1 break-all font-mono text-xs text-slate-600" title={data?.dir ?? ''}>
            {data?.dir ?? '-'}
          </p>
        </div>
      </div>

      {/* 文件列表 */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        {loading ? (
          <div className="flex justify-center py-16 text-slate-400">
            <Loader2 size={22} className="animate-spin" />
          </div>
        ) : error ? (
          <div className="py-16 text-center text-sm text-red-500">{error}</div>
        ) : !data?.dir ? (
          <div className="flex flex-col items-center justify-center py-20">
            <FolderOpen size={36} className="mb-3 text-slate-200" />
            <p className="text-sm text-slate-500">该模型没有本地文件目录</p>
            <p className="mt-1 text-xs text-slate-400">供应商远程模型或尚未落盘的模型无本地文件</p>
          </div>
        ) : data.files.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20">
            <FolderOpen size={36} className="mb-3 text-slate-200" />
            <p className="text-sm text-slate-500">目录为空，没有任何文件</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                <th className="px-4 py-3 font-medium">文件名</th>
                <th className="px-4 py-3 font-medium">相对路径</th>
                <th className="px-4 py-3 font-medium">大小</th>
                <th className="px-4 py-3 font-medium">类型</th>
                <th className="px-4 py-3 font-medium">状态</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {data.files.map((f) => (
                <tr key={f.path} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                        <FileText size={14} />
                      </span>
                      <span className="truncate font-medium text-slate-900">{f.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500" title={f.path}>
                    <span className="block max-w-xs truncate">{f.path}</span>
                  </td>
                  <td className="px-4 py-3 text-slate-600" title={`${f.size} 字节`}>
                    {formatSize(f.size)}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{f.ext ? `.${f.ext}` : '-'}</td>
                  <td className="px-4 py-3">
                    {f.empty ? (
                      <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-600">空文件</span>
                    ) : (
                      <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs text-emerald-600">正常</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {f.viewable ? (
                      <button
                        type="button"
                        onClick={() => openPreview(f)}
                        className="flex items-center gap-1 text-xs text-indigo-600 hover:underline"
                      >
                        <Eye size={13} />
                        查看内容
                      </button>
                    ) : (
                      <span className="text-xs text-slate-300">不支持预览</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 文件内容弹窗 */}
      <Modal
        open={previewFile !== null}
        title={`文件内容 - ${previewFile?.name ?? ''}`}
        onClose={() => {
          setPreviewFile(null)
          setPreview(null)
          setPreviewError('')
        }}
        maxWidth="max-w-4xl"
      >
        {previewLoading ? (
          <div className="flex justify-center py-10 text-slate-400">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : previewError ? (
          <p className="py-6 text-center text-sm text-red-500">{previewError}</p>
        ) : preview?.empty ? (
          <div className="py-8 text-center">
            <p className="text-sm font-medium text-amber-600">该文件是空文件（0 字节），没有任何内容</p>
            <p className="mt-1 text-xs text-slate-400">{preview.path}</p>
          </div>
        ) : preview ? (
          <div>
            <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
              <span className="font-mono">{preview.path}</span>
              <span>
                {formatSize(preview.size)}
                {preview.truncated && <span className="ml-2 text-amber-600">文件较大，仅显示前 512KB</span>}
              </span>
            </div>
            <pre className="max-h-[36rem] overflow-auto whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 font-mono text-xs leading-5 text-slate-700">
              {preview.content}
            </pre>
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
