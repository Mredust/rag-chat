import { ChevronRight, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { knowledgeApi } from '../../api/knowledge'
import { mlApi } from '../../api/ml'
import Select from '../../components/Select'
import type { KnowledgeSpace } from '../../types'
import { CardRadio, FileDropzone, type CardOption } from './components'

const TYPE_OPTIONS: CardOption[] = [
  { value: 'train', label: '训练集', desc: '模型训练的数据集，训练任务提交时可切分验证集' },
  { value: 'eval', label: '评测集', desc: '模型评测的数据集，需满足数据集规范' },
]

export default function DatasetCreatePage() {
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [datasetType, setDatasetType] = useState('train')
  const [files, setFiles] = useState<File[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const [sourceMode, setSourceMode] = useState<'upload' | 'generate'>('generate')
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([])
  const [spaceId, setSpaceId] = useState('')
  const [count, setCount] = useState(500)

  useEffect(() => {
    knowledgeApi
      .listSpaces()
      .then((res) => setSpaces(res.spaces))
      .catch(() => setSpaces([]))
  }, [])

  const downloadSample = () => {
    const content = [
      '{"query": "什么是RESTful API？", "positive": "RESTful API是一种基于HTTP协议的接口设计风格，通过GET、POST、PUT、DELETE四种方法操作数据，具有无状态、统一接口的特点。", "negative": "Python装饰器可以在不修改原函数的情况下为函数添加额外功能。"}',
      '{"query": "Git如何撤销commit？", "positive": "Git撤销commit可以使用git reset --soft HEAD~1撤销提交但保留修改，或使用git reset --hard HEAD~1彻底撤销提交并删除修改。", "negative": "Nginx的location指令用于匹配URL路径，支持多种匹配方式。"}',
      '{"query": "进程和线程有什么区别？", "positive": "进程拥有独立的内存空间，切换开销大；线程共享进程内存空间，切换开销小。进程崩溃不影响其他进程，线程崩溃可能导致整个进程退出。", "negative": "MySQL索引用于加速查询，常见类型有B+树索引和哈希索引。"}',
    ].join('\n')
    const blob = new Blob(['\ufeff' + content], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '样例数据.jsonl'
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleSubmit = async () => {
    if (!name.trim()) {
      setError('请输入数据集名称')
      return
    }
    const isTrain = datasetType === 'train'
    if (sourceMode === 'generate' && !spaceId) {
      setError('请选择知识库')
      return
    }
    if (sourceMode === 'upload' && files.length === 0) {
      setError('请选择需要上传的文件')
      return
    }
    setSubmitting(true)
    setError('')
    try {
      if (sourceMode === 'generate') {
        const ds = await mlApi.generateDataset({
          name: name.trim(),
          description: description.trim(),
          dataset_type: datasetType,
          train_scene: isTrain ? 'text_gen' : null,
          train_method: isTrain ? 'sft' : null,
          space_id: spaceId,
          count,
        })
        navigate(`/ml/datasets/${ds.id}`)
      } else {
        const ds = await mlApi.createDatasetUpload(
          {
            name: name.trim(),
            description: description.trim(),
            dataset_type: datasetType,
            train_scene: isTrain ? 'text_gen' : null,
            train_method: isTrain ? 'sft' : null,
            storage_location: 'oss',
            import_method: 'upload',
          },
          files,
        )
        navigate(`/ml/datasets/${ds.id}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-400">
        <span>数据管理</span>
        <ChevronRight size={14} />
        <span className="font-medium text-slate-900">新增数据集</span>
      </div>

      <div className="space-y-6">
        {/* 基础信息 */}
        <section id="basic" className="scroll-mt-6 rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">基础信息</h3>
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                数据集名称 <span className="text-red-500">*</span>
              </label>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={50}
                placeholder="请输入数据集名称"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <div className="mt-1 text-right text-xs text-slate-400">{name.length}/50</div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">数据集描述</label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={200}
                rows={4}
                placeholder="请输入数据集描述（选填）"
                className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <div className="mt-1 text-right text-xs text-slate-400">{description.length}/200</div>
            </div>
          </div>
        </section>

        {/* 类型与格式 */}
        <section id="format" className="scroll-mt-6 rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">类型与格式</h3>
          <div className="space-y-6">
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">数据集类型</label>
              <CardRadio options={TYPE_OPTIONS} value={datasetType} onChange={setDatasetType} columns={2} />
            </div>
          </div>
        </section>

        {/* 数据上传 */}
        <section id="upload" className="scroll-mt-6 rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">数据上传</h3>

          {/* 来源方式切换 */}
          <div className="mb-4 inline-flex rounded-lg bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setSourceMode('generate')}
              className={`rounded-md px-4 py-1.5 text-sm ${sourceMode === 'generate' ? 'bg-white font-medium text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
            >
              知识库
            </button>
            <button
              type="button"
              onClick={() => setSourceMode('upload')}
              className={`rounded-md px-4 py-1.5 text-sm ${sourceMode === 'upload' ? 'bg-white font-medium text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
            >
              本地上传
            </button>
          </div>

          {sourceMode === 'upload' ? (
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">文件上传</label>
              <FileDropzone files={files} onChange={setFiles} />
              <div className="mt-4 flex items-center gap-4 rounded-lg bg-slate-50 px-4 py-3 text-sm">
                <span className="text-slate-600">数据格式说明</span>
                <button type="button" className="text-indigo-600 hover:underline" onClick={downloadSample}>
                  下载 Jsonl 格式样例
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">
                  选择知识库 <span className="text-red-500">*</span>
                </label>
                <Select
                  value={spaceId}
                  onChange={setSpaceId}
                  placeholder="请选择知识库"
                  options={spaces.map((s) => ({ value: s.id, label: s.name }))}
                  className="w-full"
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">
                  需要多少条数据 <span className="text-red-500">*</span>
                </label>
                <input
                  type="number"
                  min={1}
                  max={5000}
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value) || 1)}
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </div>
              <p className="text-xs leading-relaxed text-slate-400">
                将基于所选知识库中的文档内容，分批并发调用大模型按 query/positive/negative 格式生成数据集并保存。
              </p>
            </div>
          )}
        </section>

        {error && <p className="text-sm text-red-600">{error}</p>}

        {/* 底部操作 */}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={() => navigate('/ml/datasets')} className="rounded-lg border border-slate-200 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
            取消
          </button>
          <button type="button" onClick={handleSubmit} disabled={submitting} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60">
            {submitting && <Loader2 size={14} className="animate-spin" />}
            确认
          </button>
        </div>
      </div>
    </div>
  )
}