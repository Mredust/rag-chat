// 模型训练平台通用常量：字段 label 与状态样式映射

export const DATASET_TYPE_LABELS: Record<string, string> = {
  train: '训练集',
  eval: '评测集',
}

export const PUBLISH_LABELS: Record<string, string> = {
  draft: '未发布',
  published: '已发布',
}

export const IMPORT_STATUS_LABELS: Record<string, string> = {
  importing: '导入中',
  done: '完成',
  failed: '失败',
}

export const TRAIN_METHOD_LABELS: Record<string, string> = {
  sft: 'SFT',
  dpo: 'DPO',
  cpt: 'CPT',
  rl: 'RL',
}

export const TRAIN_MODE_LABELS: Record<string, string> = {
  efficient: '高效训练',
  full: '全参训练',
}

export function trainMethodFull(train_method: string, config?: Record<string, unknown> | null): string {
  const method = TRAIN_METHOD_LABELS[train_method] ?? train_method.toUpperCase()
  const mode = TRAIN_MODE_LABELS[(config?.train_mode as string) ?? ''] ?? ''
  return mode ? `${method}-${mode}` : method
}

export const EVAL_TYPE_LABELS: Record<string, string> = {
  llm_classify: '大模型评估-分类型',
  llm_numeric: '大模型评估-数值型',
  rule_sim: '规则评估-文本相似度',
  retrieval: '检索评估',
  spearman: '统计评估-Spearman相关系数',
}

// 模型来源（按 model_dir 所在目录）
export const SOURCE_LABELS: Record<string, string> = {
  system: '系统内置模型',
  ftm: '微调模型',
  local: '本地模型',
}

export function sourceLabel(source: string | undefined): string {
  return SOURCE_LABELS[source ?? ''] ?? '本地模型'
}

// 下拉选择右侧的来源提示：供应商模型显示其供应商名称（如「阿里云」），其余按来源标签展示
export function sourceHint(model: { source_type?: string; provider_config?: { provider?: string } | null }): string {
  if (model.source_type === 'provider') {
    return model.provider_config?.provider || '供应商模型'
  }
  return sourceLabel(model.source_type)
}

// 状态徽章样式（bg + text）
export const BADGE: Record<string, string> = {
  // 发布状态
  draft: 'bg-slate-100 text-slate-600',
  published: 'bg-green-100 text-green-700',
  // 导入状态 / 任务状态
  done: 'bg-green-100 text-green-700',
  importing: 'bg-blue-100 text-blue-700',
  running: 'bg-blue-100 text-blue-700',
  pending: 'bg-amber-100 text-amber-700',
  failed: 'bg-red-100 text-red-700',
  stopped: 'bg-slate-100 text-slate-600',
  ready: 'bg-green-100 text-green-700',
}

export function badgeCls(status: string): string {
  return BADGE[status] ?? 'bg-slate-100 text-slate-600'
}

export function badgeLabel(status: string): string {
  return (
    STATUS_LABELS[status] ??
    status
  )
}

const STATUS_LABELS: Record<string, string> = {
  draft: '未发布',
  published: '已发布',
  done: '完成',
  importing: '导入中',
  running: '运行中',
  pending: '排队中',
  failed: '失败',
  stopped: '已停止',
  ready: '就绪',
}