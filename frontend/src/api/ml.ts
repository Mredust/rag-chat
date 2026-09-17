import { http, getToken, ApiError } from './client'
import type {
  MLDataset,
  MLDatasetList,
  MLDatasetVersion,
  MLDatasetVersionList,
  MLEvalDimension,
  MLEvalDimensionList,
  MLEvalTask,
  MLEvalTaskDetailList,
  MLEvalTaskList,
  MLLeaderboard,
  MLLeaderboardDetail,
  MLLeaderboardList,
  MLModel,
  MLModelList,
  MLOptions,
  MLTrainTask,
  MLTrainTaskList,
} from '../types/ml'
import type { ApiResponse } from '../types'

const API_BASE = '/api/v1'

export interface MLDatasetPayload {
  name: string
  description?: string
  dataset_type: string
  train_scene?: string | null
  train_method?: string | null
  storage_location: string
  import_method: string
}

export interface MLDatasetGeneratePayload {
  name: string
  description?: string
  dataset_type: string
  train_scene?: string | null
  train_method?: string | null
  space_id: string
  count: number
}

export interface MLTrainTaskPayload {
  name: string
  priority?: string
  train_method: string
  base_model: string
  dataset_id?: string | null
  dataset_ids?: string[]
  valid_ratio: number
  config?: Record<string, unknown>
  output_model_name?: string
}

export interface MLEvalTaskPayload {
  name: string
  model_id?: string | null
  model_type?: string
  llm_model_id?: string | null
  data_source: string
  data_id?: string
  data_mode?: string
  split_dataset_id?: string
  split_ratio?: number
  dimension_ids?: string[]
  sync_leaderboard: boolean
  leaderboard_id?: string | null
}

export interface MLEvalDimensionPayload {
  name: string
  description?: string
  eval_type?: string
  eval_config?: Record<string, unknown>
}

export interface MLLeaderboardPayload {
  name: string
  dimension_ids?: string[]
  task_ids?: string[]
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')
  if (entries.length === 0) return ''
  return '?' + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&')
}

// 多文件上传（multipart/form-data）
async function uploadFiles<T>(path: string, files: File[]): Promise<T> {
  const token = getToken()
  const form = new FormData()
  files.forEach((f) => form.append('files', f))

  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })

  let body: ApiResponse<T>
  try {
    body = (await res.json()) as ApiResponse<T>
  } catch {
    throw new ApiError('服务器返回格式错误', -1, res.status)
  }
  if (!res.ok || body.code !== 0) {
    throw new ApiError(body.message || '上传失败', body.code, res.status)
  }
  return body.data
}

// 创建数据集并上传文件（multipart：数据集元信息 + JSONL 文件）
async function createDatasetUpload(data: MLDatasetPayload, files: File[]): Promise<MLDataset> {
  const token = getToken()
  const form = new FormData()
  form.append('name', data.name)
  form.append('description', data.description ?? '')
  form.append('dataset_type', data.dataset_type)
  if (data.train_scene) form.append('train_scene', data.train_scene)
  if (data.train_method) form.append('train_method', data.train_method)
  files.forEach((f) => form.append('files', f))

  const res = await fetch(`${API_BASE}/ml/datasets/upload`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })

  let body: ApiResponse<MLDataset>
  try {
    body = (await res.json()) as ApiResponse<MLDataset>
  } catch {
    throw new ApiError('服务器返回格式错误', -1, res.status)
  }
  if (!res.ok || body.code !== 0) {
    throw new ApiError(body.message || '上传失败', body.code, res.status)
  }
  return body.data
}

export interface MLExportStatus {
  state: 'idle' | 'running' | 'done' | 'error'
  progress: number
  error?: string | null
  filename?: string | null
}

export interface MLSaveModelStatus {
  state: 'idle' | 'running' | 'done' | 'error'
  progress: number
  error?: string | null
  model_dir?: string | null
  model_name?: string | null
}

// 启动异步导出训练产出模型
function startExportTrainModel(id: string): Promise<MLExportStatus> {
  return http.post<MLExportStatus>(`/ml/train-tasks/${id}/export`)
}

// 查询导出进度
function getExportTrainModelStatus(id: string): Promise<MLExportStatus> {
  return http.get<MLExportStatus>(`/ml/train-tasks/${id}/export/status`)
}

// 下载已导出的模型文件（zip）：携带鉴权请求后触发浏览器下载
async function downloadExportTrainModel(id: string): Promise<void> {
  const token = getToken()
  const res = await fetch(`${API_BASE}/ml/train-tasks/${id}/export/download`, {
    method: 'GET',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (!res.ok) {
    let message = '下载失败'
    try {
      const body = (await res.json()) as ApiResponse<unknown>
      message = body.message || message
    } catch {
      /* ignore */
    }
    throw new ApiError(message, -1, res.status)
  }

  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const filename = star ? decodeURIComponent(star) : disposition.match(/filename="?([^";]+)"?/)?.[1] ?? 'model.zip'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// 下载评测结果（xlsx）：携带鉴权请求后触发浏览器下载
async function downloadEvalTask(id: string): Promise<void> {
  const token = getToken()
  const res = await fetch(`${API_BASE}/ml/eval-tasks/${id}/export`, {
    method: 'GET',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })

  if (!res.ok) {
    let message = '下载失败'
    try {
      const body = (await res.json()) as ApiResponse<unknown>
      message = body.message || message
    } catch {
      /* ignore */
    }
    throw new ApiError(message, -1, res.status)
  }

  const blob = await res.blob()
  const disposition = res.headers.get('Content-Disposition') ?? ''
  const star = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const filename = star ? decodeURIComponent(star) : 'eval-task.xlsx'
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

// 导入模型文件夹（multipart：name/base_model 元信息 + 文件夹内文件）
async function importModelFolder(name: string, baseModel: string, files: File[]): Promise<MLModel> {
  const token = getToken()
  const form = new FormData()
  form.append('name', name)
  form.append('base_model', baseModel)
  files.forEach((f) =>
    form.append('files', f, (f as File & { relativePath?: string }).relativePath || f.webkitRelativePath || f.name),
  )

  const res = await fetch(`${API_BASE}/ml/models/import`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })

  let body: ApiResponse<MLModel>
  try {
    body = (await res.json()) as ApiResponse<MLModel>
  } catch {
    throw new ApiError('服务器返回格式错误', -1, res.status)
  }
  if (!res.ok || body.code !== 0) {
    throw new ApiError(body.message || '导入失败', body.code, res.status)
  }
  return body.data
}

// 导入供应商向量模型（multipart form：供应商名称/URL/API Key/模型名称）
async function importProviderModel(
  name: string,
  provider: string,
  url: string,
  apiKey: string,
  modelName: string,
): Promise<MLModel> {
  const token = getToken()
  const form = new FormData()
  form.append('name', name)
  form.append('provider', provider)
  form.append('url', url)
  form.append('api_key', apiKey)
  form.append('model_name', modelName)

  const res = await fetch(`${API_BASE}/ml/models/import-provider`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  })

  let body: ApiResponse<MLModel>
  try {
    body = (await res.json()) as ApiResponse<MLModel>
  } catch {
    throw new ApiError('服务器返回格式错误', -1, res.status)
  }
  if (!res.ok || body.code !== 0) {
    throw new ApiError(body.message || '导入失败', body.code, res.status)
  }
  return body.data
}

export const mlApi = {
  // 选项
  options: () => http.get<MLOptions>('/ml/options'),

  // 数据集
  listDatasets: (params: { dataset_type?: string; storage?: string; import_method?: string; search?: string }) =>
    http.get<MLDatasetList>(`/ml/datasets${qs(params)}`),
  createDatasetUpload: (data: MLDatasetPayload, files: File[]) => createDatasetUpload(data, files),
  generateDataset: (data: MLDatasetGeneratePayload) => http.post<MLDataset>('/ml/datasets/generate', data),
  getDataset: (id: string) => http.get<MLDataset>(`/ml/datasets/${id}`),
  deleteDataset: (id: string) => http.delete<null>(`/ml/datasets/${id}`),

  // 数据集版本
  listVersions: (id: string) => http.get<MLDatasetVersionList>(`/ml/datasets/${id}/versions`),
  createVersion: (id: string, files: File[]) => uploadFiles<MLDatasetVersion>(`/ml/datasets/${id}/versions`, files),
  publishVersion: (id: string, versionId: string) =>
    http.post<MLDatasetVersion>(`/ml/datasets/${id}/versions/${versionId}/publish`),
  deleteVersion: (id: string, versionId: string) =>
    http.delete<null>(`/ml/datasets/${id}/versions/${versionId}`),

  // 模型
  listModels: (search?: string) => http.get<MLModelList>(`/ml/models${qs({ search })}`),
  importModel: (name: string, baseModel: string, files: File[]) => importModelFolder(name, baseModel, files),
  importSupplierModel: (name: string, provider: string, url: string, apiKey: string, modelName: string) =>
    importProviderModel(name, provider, url, apiKey, modelName),
  saveModelLocal: (id: string) => http.post<MLModel>(`/ml/models/${id}/save-local`),
  deleteModel: (id: string, deleteLocal?: boolean) =>
    http.delete<null>(`/ml/models/${id}${deleteLocal ? '?delete_local=true' : ''}`),

  // 训练任务
  listTrainTasks: (params: { priority?: string; base_model?: string; search?: string }) =>
    http.get<MLTrainTaskList>(`/ml/train-tasks${qs(params)}`),
  createTrainTask: (data: MLTrainTaskPayload) => http.post<MLTrainTask>('/ml/train-tasks', data),
  getTrainTask: (id: string) => http.get<MLTrainTask>(`/ml/train-tasks/${id}`),
  stopTrainTask: (id: string) => http.post<MLTrainTask>(`/ml/train-tasks/${id}/stop`),
  resumeTrainTask: (id: string) => http.post<MLTrainTask>(`/ml/train-tasks/${id}/resume`),
  exportTrainTask: (id: string) => startExportTrainModel(id),
  getExportStatus: (id: string) => getExportTrainModelStatus(id),
  downloadExport: (id: string) => downloadExportTrainModel(id),
  saveTrainTaskModel: (id: string) => http.post<MLSaveModelStatus>(`/ml/train-tasks/${id}/save-model`),
  getSaveModelStatus: (id: string) => http.get<MLSaveModelStatus>(`/ml/train-tasks/${id}/save-model/status`),
  deleteTrainTask: (id: string) => http.delete<null>(`/ml/train-tasks/${id}`),

  // 评测维度
  listDimensions: () => http.get<MLEvalDimensionList>('/ml/dimensions'),
  createDimension: (data: MLEvalDimensionPayload) => http.post<MLEvalDimension>('/ml/dimensions', data),
  deleteDimension: (id: string) => http.delete<null>(`/ml/dimensions/${id}`),

  // 评测任务
  listEvalTasks: () => http.get<MLEvalTaskList>('/ml/eval-tasks'),
  createEvalTask: (data: MLEvalTaskPayload) => http.post<MLEvalTask>('/ml/eval-tasks', data),
  getEvalTask: (id: string) => http.get<MLEvalTask>(`/ml/eval-tasks/${id}`),
  stopEvalTask: (id: string) => http.post<MLEvalTask>(`/ml/eval-tasks/${id}/stop`),
  listEvalTaskDetails: (
    id: string,
    params: { page?: number; page_size?: number; field?: string; keyword?: string },
  ) => http.get<MLEvalTaskDetailList>(`/ml/eval-tasks/${id}/details${qs(params)}`),
  deleteEvalTask: (id: string) => http.delete<null>(`/ml/eval-tasks/${id}`),
  downloadEvalTask: (id: string) => downloadEvalTask(id),

  // 排行榜
  listLeaderboards: () => http.get<MLLeaderboardList>('/ml/leaderboards'),
  createLeaderboard: (data: MLLeaderboardPayload) => http.post<MLLeaderboard>('/ml/leaderboards', data),
  updateLeaderboard: (id: string, data: MLLeaderboardPayload) => http.put<MLLeaderboard>(`/ml/leaderboards/${id}`, data),
  deleteLeaderboard: (id: string) => http.delete<null>(`/ml/leaderboards/${id}`),
  getLeaderboard: (id: string) => http.get<MLLeaderboardDetail>(`/ml/leaderboards/${id}`),
  removeLeaderboardTask: (id: string, taskId: string) => http.delete<null>(`/ml/leaderboards/${id}/tasks/${taskId}`),
}