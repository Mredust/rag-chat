// 模型训练平台（数据管理 / 我的模型 / 模型调优 / 模型评测）相关类型

export interface MLOptionItem {
  value: string
  label: string
}

export interface MLModelDirOption {
  name: string
  path: string
  source: string
}

export interface MLOptions {
  base_models: string[]
  buckets: string[]
  train_scenes: MLOptionItem[]
  train_methods: MLOptionItem[]
  tune_methods: MLOptionItem[]
  model_dirs: MLModelDirOption[]
}

export interface MLDataset {
  id: string
  name: string
  description: string
  dataset_type: string
  train_scene: string | null
  train_method: string | null
  storage_location: string
  import_method: string
  created_at: string
  updated_at: string
  latest_version: number | null
  latest_version_id: string | null
  data_count: number
  import_status: string
  publish_status: string
  version_updated_at: string | null
}

export interface MLDatasetList {
  datasets: MLDataset[]
  total: number
}

export interface MLDatasetVersion {
  id: string
  dataset_id: string
  version: number
  file_count: number
  data_count: number
  import_status: string
  publish_status: string
  file_id: string
  preview_content: string
  created_at: string
}

export interface MLDatasetVersionList {
  versions: MLDatasetVersion[]
  total: number
}

export interface MLModel {
  id: string
  name: string
  base_model: string
  train_method: string
  source: string
  bucket: string
  model_dir: string
  provider_config: { provider: string; url: string; api_key: string; model: string } | null
  status: string
  is_local: boolean
  source_type: string
  created_at: string
  updated_at: string
}

export interface MLModelList {
  models: MLModel[]
  total: number
}

export interface MLTrainMetrics {
  epochs?: number[]
  train_loss?: number[]
  val_loss?: number[]
  val_acc?: number[]
  learning_rate?: number[]
  total_steps?: number
  total_time_sec?: number
  token_usage?: number
  final_loss?: number
  final_acc?: number
}

export interface MLTrainTask {
  id: string
  name: string
  priority: string
  train_method: string
  base_model: string
  dataset_id: string | null
  dataset_ids: string[]
  valid_ratio: number
  config: Record<string, unknown>
  output_model_name: string
  status: string
  output_dir: string
  log: string
  metrics: MLTrainMetrics
  created_at: string
  updated_at: string
}

export interface MLTrainTaskList {
  tasks: MLTrainTask[]
  total: number
}

export interface MLEvalDimension {
  id: string
  name: string
  description: string
  eval_type: string
  eval_config: Record<string, unknown>
  created_at: string
}

export interface MLEvalDimensionList {
  dimensions: MLEvalDimension[]
  total: number
}

export interface MLEvalTask {
  id: string
  name: string
  model_id: string | null
  model_name: string
  model_type: string
  llm_model_id: string | null
  data_source: string
  data_id: string
  data_name: string
  data_mode: string
  split_dataset_id: string
  split_ratio: number
  dimension_ids: string[]
  dimension_names: string[]
  sync_leaderboard: boolean
  leaderboard_id: string | null
  leaderboard_name: string
  status: string
  total_count: number
  completed_count: number
  result: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface MLEvalTaskList {
  tasks: MLEvalTask[]
  total: number
}

export interface MLLeaderboard {
  id: string
  name: string
  dimension_ids: string[]
  dimension_names: string[]
  task_ids: string[]
  task_count: number
  created_at: string
}

export interface MLLeaderboardList {
  leaderboards: MLLeaderboard[]
  total: number
}

export interface MLLeaderboardTaskEntry {
  id: string
  name: string
  model_name: string
  score: number
  dimension_scores: Record<string, number>
  created_at: string
}

export interface MLLeaderboardDetail extends MLLeaderboard {
  tasks: MLLeaderboardTaskEntry[]
}

export interface EvalTraceDoc {
  rank: number
  content: string
  score: number
}

export interface EvalTraceCheck {
  name: string
  pass: boolean
  reason: string
}

export interface EvalTrace {
  top_k: number
  vector_rank: number | null
  fulltext_rank: number | null
  hybrid_rank: number | null
  rerank_rank: number | null
  vector_top5: EvalTraceDoc[]
  rag_answer?: string
  judge_model?: string
  tokens?: { input: number; output: number; total: number }
  checks?: EvalTraceCheck[]
  conclusion?: string
  hallucination?: number
  reason?: string
}

export interface MLEvalTaskDetailItem {
  index: number
  query: string
  positive: string
  negative: string
  label: string
  score: number
  dims: Record<string, { label?: string; value?: number }>
  trace?: EvalTrace
}

export interface MLEvalTaskDetailList {
  items: MLEvalTaskDetailItem[]
  total: number
  page: number
  page_size: number
}