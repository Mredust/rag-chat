import { Loader2, Plus, RefreshCw, Search, Trash2, Upload } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import Modal from '../../components/Modal'
import Select from '../../components/Select'
import { formatDate } from '../../lib/format'
import type { MLDataset } from '../../types/ml'
import { FileDropzone } from './components'
import { badgeCls, badgeLabel, DATASET_TYPE_LABELS, PUBLISH_LABELS } from './constants'

export default function DatasetListPage() {
  const navigate = useNavigate()
  const [datasets, setDatasets] = useState<MLDataset[]>([])
  const [loading, setLoading] = useState(true)

  const [type, setType] = useState('')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  const [uploadFor, setUploadFor] = useState<MLDataset | null>(null)
  const [uploadFiles, setUploadFiles] = useState<File[]>([])
  const [uploading, setUploading] = useState(false)

  const [deleteItem, setDeleteItem] = useState<MLDataset | null>(null)
  const [deleting, setDeleting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await mlApi.listDatasets({
        dataset_type: type || undefined,
        search: debouncedSearch || undefined,
      })
      setDatasets(res.datasets)
    } catch {
      /* ignore */
    } finally {
      setLoading(false)
    }
  }, [type, debouncedSearch])

  useEffect(() => {
    load()
  }, [load])

  // 数据集名称搜索防抖：停止输入 300ms 后再发起请求
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(timer)
  }, [search])

  const handleConfirmDelete = async () => {
    if (!deleteItem) return
    setDeleting(true)
    try {
      await mlApi.deleteDataset(deleteItem.id)
      setDeleteItem(null)
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '删除失败')
    } finally {
      setDeleting(false)
    }
  }

  const handlePublish = async (d: MLDataset) => {
    if (!d.latest_version_id) {
      window.alert('该数据集暂无版本，请先新增版本')
      return
    }
    await mlApi.publishVersion(d.id, d.latest_version_id)
    await load()
  }

  const handleUpload = async () => {
    if (!uploadFor) return
    if (uploadFiles.length === 0) {
      window.alert('请选择需要上传的文件')
      return
    }
    setUploading(true)
    try {
      await mlApi.createVersion(uploadFor.id, uploadFiles)
      setUploadFor(null)
      setUploadFiles([])
      await load()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : '上传失败')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div>
      {/* 顶部：Tab + 操作 */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-900">数据管理</h2>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={load}
            className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
          >
            <RefreshCw size={14} />
            刷新
          </button>
          <button
            type="button"
            onClick={() => navigate('/ml/datasets/new')}
            className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-sm text-white hover:bg-indigo-700"
          >
            <Plus size={16} />
            新增数据集
          </button>
        </div>
      </div>

      <>
        {/* 筛选栏 */}
        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
          <label className="flex items-center gap-1.5 text-sm text-slate-600">
            数据集类型
            <Select
              value={type}
              onChange={setType}
              options={[
                { value: '', label: '全部' },
                { value: 'train', label: '训练集' },
                { value: 'eval', label: '评测集' },
              ]}
              className="w-32"
            />
          </label>
          <div className="relative ml-auto">
            <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="输入数据集名称"
              className="w-56 rounded-lg border border-slate-300 py-1.5 pl-8 pr-3 text-sm outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        {/* 数据表格 */}
        <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs text-slate-500">
                <th className="px-4 py-3 font-medium">数据集名称</th>
                <th className="px-4 py-3 font-medium">数据集类型</th>
                <th className="px-4 py-3 font-medium">最新版本</th>
                <th className="px-4 py-3 font-medium">数据量</th>
                <th className="px-4 py-3 font-medium">导入状态</th>
                <th className="px-4 py-3 font-medium">发布状态</th>
                <th className="px-4 py-3 font-medium">版本更新时间</th>
                <th className="px-4 py-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={8}>
                    <div className="flex justify-center py-16 text-slate-400">
                      <Loader2 size={22} className="animate-spin" />
                    </div>
                  </td>
                </tr>
              ) : datasets.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-16 text-center text-sm text-slate-400">
                    暂无数据集，点击右上角「新增数据集」创建
                  </td>
                </tr>
              ) : (
                datasets.map((d) => (
                  <tr key={d.id} className="border-b border-slate-50 last:border-0 hover:bg-slate-50">
                    <td
                      className="cursor-pointer px-4 py-3 font-medium text-indigo-600 hover:underline"
                      onClick={() => navigate(`/ml/datasets/${d.id}`)}
                    >
                      {d.name}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{DATASET_TYPE_LABELS[d.dataset_type] ?? d.dataset_type}</td>
                    <td className="px-4 py-3 text-slate-600">{d.latest_version != null ? `v${d.latest_version}` : '-'}</td>
                    <td className="px-4 py-3 text-slate-600">{d.latest_version != null ? d.data_count : '-'}</td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${badgeCls(d.import_status)}`}>{badgeLabel(d.import_status) || '-'}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${badgeCls(d.publish_status)}`}>{PUBLISH_LABELS[d.publish_status] ?? d.publish_status}</span>
                    </td>
                    <td className="px-4 py-3 text-slate-500">{d.version_updated_at ? formatDate(d.version_updated_at) : '-'}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-3 text-xs">
                        <button type="button" onClick={() => { setUploadFor(d); setUploadFiles([]) }} className="text-indigo-600 hover:underline">
                          新增版本
                        </button>
                        <button
                          type="button"
                          onClick={() => handlePublish(d)}
                          disabled={d.publish_status === 'published'}
                          className={`${d.publish_status === 'published' ? 'cursor-not-allowed text-slate-400' : 'text-indigo-600 hover:underline'}`}
                        >
                          发布
                        </button>
                        <button type="button" onClick={() => setDeleteItem(d)} className="flex items-center gap-1 text-red-500 hover:underline">
                          <Trash2 size={13} />
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </>

      {/* 新增版本上传 */}
      <Modal open={uploadFor !== null} title={`新增版本 - ${uploadFor?.name ?? ''}`} onClose={() => setUploadFor(null)}>
        <div className="space-y-4">
          <FileDropzone files={uploadFiles} onChange={setUploadFiles} />
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setUploadFor(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
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

      {/* 删除确认 */}
      <Modal open={deleteItem !== null} title="删除确认" onClose={() => setDeleteItem(null)}>
        <div className="space-y-4">
          <p className="text-sm text-slate-700">确定删除数据集「{deleteItem?.name}」吗？此操作不可恢复。</p>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setDeleteItem(null)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
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