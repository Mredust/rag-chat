import { ChevronRight, FileArchive, FolderOpen, Loader2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import Select from '../../components/Select'
import type { MLOptions } from '../../types/ml'

/** 递归读取目录句柄，收集文件并为每个文件附加相对路径 */
async function collectFiles(dirHandle: any, prefix: string, out: File[]) {
  for await (const entry of dirHandle.values()) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name
    if (entry.kind === 'file') {
      const file: File = await entry.getFile()
        ; (file as File & { relativePath?: string }).relativePath = rel
      out.push(file)
    } else if (entry.kind === 'directory') {
      await collectFiles(entry, rel, out)
    }
  }
}

/** 目录位置 -> 来源标签 */
const SOURCE_LABELS: Record<string, string> = {
  system: '系统内置模型',
  ftm: '微调模型',
  local: '本地模型',
}

export default function ModelImportPage() {
  const navigate = useNavigate()
  const [options, setOptions] = useState<MLOptions | null>(null)
  const [mode, setMode] = useState<'select' | 'import' | 'supplier'>('select')
  const [name, setName] = useState('')
  const [baseModel, setBaseModel] = useState('')
  const [provider, setProvider] = useState('阿里云')
  const [supplierUrl, setSupplierUrl] = useState('')
  const [supplierApiKey, setSupplierApiKey] = useState('')
  const [supplierModelName, setSupplierModelName] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [folderName, setFolderName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const folderInputRef = useRef<HTMLInputElement>(null)
  const zipInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    mlApi.options().then(setOptions).catch(() => { })
  }, [])

  const handleSelectBase = (v: string) => {
    setBaseModel(v)
    if (!name.trim()) {
      const opt = (options?.model_dirs ?? []).find((m) => m.path === v)
      setName(opt?.name ?? v)
    }
  }

  // 降级方案：不支持 showDirectoryPicker 时回退到 webkitdirectory 输入
  const handleNativeFolderChange = (e: ChangeEvent<HTMLInputElement>) => {
    const fs = Array.from(e.target.files ?? [])
    setFiles(fs)
    const folder = fs[0]?.webkitRelativePath?.split('/')[0] ?? ''
    setFolderName(folder)
    if (folder && !name.trim()) setName(folder)
  }

  // 选择 zip 压缩包：仅单个文件，交由后端解压到 models 目录
  const handleZipChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    setFiles([f])
    const base = f.name.replace(/\.zip$/i, '')
    setFolderName(base)
    if (base && !name.trim()) setName(base)
  }

  // 优先使用 File System Access API，避免 webkitdirectory 弹出的「是否上传文件到此网站」原生确认
  const handleChooseFolder = async () => {
    const picker = (window as unknown as { showDirectoryPicker?: () => Promise<any> }).showDirectoryPicker
    if (typeof picker === 'function') {
      try {
        const dirHandle = await picker()
        const fs: File[] = []
        await collectFiles(dirHandle, '', fs)
        setFiles(fs)
        setFolderName(dirHandle.name || '')
        if (dirHandle.name && !name.trim()) setName(dirHandle.name)
      } catch {
        // 用户取消选择，忽略
      }
    } else {
      folderInputRef.current?.click()
    }
  }

  const handleSubmit = async () => {
    if (!name.trim()) return setError('请输入模型名称')
    if (mode === 'select' && !baseModel) return setError('请选择基础模型')
    if (mode === 'import' && files.length === 0) return setError('请选择需要导入的模型文件夹或 zip 压缩包')
    if (mode === 'supplier') {
      if (!supplierUrl.trim()) return setError('请输入供应商 URL')
      if (!supplierApiKey.trim()) return setError('请输入供应商 API Key')
      if (!supplierModelName.trim()) return setError('请输入供应商模型名称')
    }
    setSubmitting(true)
    setError('')
    try {
      // 选择已有模型：仅传 base_model；导入文件夹/zip：仅传文件（基础模型由后端按模型名回填）
      if (mode === 'select') {
        await mlApi.importModel(name.trim(), baseModel, [])
      } else if (mode === 'supplier') {
        await mlApi.importSupplierModel(name.trim(), provider, supplierUrl, supplierApiKey, supplierModelName)
      } else {
        await mlApi.importModel(name.trim(), '', files)
      }
      navigate('/ml/models')
    } catch (err) {
      setError(err instanceof Error ? err.message : '导入失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-400">
        <button type="button" onClick={() => navigate('/ml/models')} className="hover:text-slate-600">
          我的模型
        </button>
        <ChevronRight size={14} />
        <span className="font-medium text-slate-900">导入模型</span>
      </div>

      <div className="mx-auto max-w-3xl space-y-5 rounded-xl border border-slate-200 bg-white p-6">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            模型名称 <span className="text-red-500">*</span>
          </label>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={50} placeholder="请输入模型名称" className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500" />
          <div className="mt-1 text-right text-xs text-slate-400">{name.length}/50</div>
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">
            基础模型 <span className="text-red-500">*</span>
          </label>
          {/* 三选一：从已有模型选择 / 导入模型 / 导入供应商 */}
          <div className="mb-3 flex rounded-lg bg-slate-100 p-1">
            <button
              type="button"
              onClick={() => setMode('select')}
              className={`flex-1 rounded-md px-4 py-1.5 text-sm ${mode === 'select' ? 'bg-white font-medium text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
            >
              从已有模型选择
            </button>
            <button
              type="button"
              onClick={() => setMode('import')}
              className={`flex-1 rounded-md px-4 py-1.5 text-sm ${mode === 'import' ? 'bg-white font-medium text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
            >
              导入模型
            </button>
            <button
              type="button"
              onClick={() => setMode('supplier')}
              className={`flex-1 rounded-md px-4 py-1.5 text-sm ${mode === 'supplier' ? 'bg-white font-medium text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-800'}`}
            >
              导入供应商
            </button>
          </div>

          {mode === 'select' ? (
            <div>
              <Select
                value={baseModel}
                onChange={handleSelectBase}
                placeholder="请选择基础模型"
                options={(options?.model_dirs ?? []).map((m) => ({ value: m.path, label: m.name, hint: SOURCE_LABELS[m.source] ?? '本地模型' }))}
                className="w-full"
              />
              <p className="mt-1 text-xs text-slate-400">基础模型来自 models 目录下的模型文件夹。</p>
            </div>
          ) : mode === 'supplier' ? (
            <div className="space-y-3">
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  供应商 <span className="text-red-500">*</span>
                </label>
                <input
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  placeholder="供应商名称"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
                <p className="mt-1 text-xs text-slate-400">供应商名称会作为模型来源展示在「我的模型」列表中。</p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  URL <span className="text-red-500">*</span>
                </label>
                <input
                  value={supplierUrl}
                  onChange={(e) => setSupplierUrl(e.target.value)}
                  placeholder="供应商向量模型 API 地址"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  API Key <span className="text-red-500">*</span>
                </label>
                <input
                  value={supplierApiKey}
                  onChange={(e) => setSupplierApiKey(e.target.value)}
                  placeholder="供应商 API Key"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  模型名称 <span className="text-red-500">*</span>
                </label>
                <input
                  value={supplierModelName}
                  onChange={(e) => setSupplierModelName(e.target.value)}
                  placeholder="供应商向量模型名称"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
                />
                <p className="mt-1 text-xs text-slate-400">保存后将访问该供应商的向量模型，而非本地模型。</p>
              </div>
            </div>
          ) : (
            <div>
              <div className="flex gap-3">
                <button
                  type="button"
                  onClick={handleChooseFolder}
                  className="flex flex-1 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-6 hover:bg-slate-100"
                >
                  <FolderOpen size={26} className="text-slate-400" />
                  <span className="text-sm text-slate-500">选择模型文件夹</span>
                </button>
                <button
                  type="button"
                  onClick={() => zipInputRef.current?.click()}
                  className="flex flex-1 cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-slate-50 px-4 py-6 hover:bg-slate-100"
                >
                  <FileArchive size={26} className="text-slate-400" />
                  <span className="text-sm text-slate-500">选择 zip 压缩包</span>
                </button>
              </div>

              {files.length > 0 && (
                <div className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-sm">
                  <span className="font-medium text-slate-700">{folderName || '已选择'}</span>
                  <span className="ml-2 text-xs text-slate-400">共 {files.length} 个文件</span>
                </div>
              )}

              <input
                ref={(el) => {
                  folderInputRef.current = el
                  if (el) {
                    el.setAttribute('webkitdirectory', '')
                    el.setAttribute('directory', '')
                  }
                }}
                type="file"
                multiple
                className="hidden"
                onChange={handleNativeFolderChange}
              />
              <input
                ref={zipInputRef}
                type="file"
                accept=".zip,application/zip"
                className="hidden"
                onChange={handleZipChange}
              />
              <p className="mt-1 text-xs text-slate-400">导入后将保存到 models 目录，并录入系统路径供后续调用；支持导入 zip 压缩包并自动解压。</p>
            </div>
          )}
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <div className="flex justify-end gap-3 pt-2">
          <button type="button" onClick={() => navigate('/ml/models')} className="rounded-lg border border-slate-200 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
            取消
          </button>
          <button type="button" onClick={handleSubmit} disabled={submitting} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60">
            {submitting && <Loader2 size={14} className="animate-spin" />}
            确定
          </button>
        </div>
      </div>
    </div>
  )
}