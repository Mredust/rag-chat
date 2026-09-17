import { ChevronRight, Loader2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { mlApi } from '../../api/ml'
import { providerApi } from '../../api/provider'
import type { Provider } from '../../types'
import Select from '../../components/Select'

const EVAL_TYPES = [
  { value: 'llm_classify', label: '大模型评估-分类型' },
  { value: 'llm_numeric', label: '大模型评估-数值型' },
  { value: 'rule_sim', label: '规则评估-文本相似度' },
  { value: 'retrieval', label: '检索评估' },
  { value: 'spearman', label: '统计评估-Spearman相关系数' },
]

/* 检索评估指标清单（评测维度 / 指标 / 说明） */
const RETRIEVAL_METRICS = [
  { key: 'recall_at_5', name: '召回率', metric: 'Recall@K', desc: '正确答案是否排在前K位（K为下方Recall值）' },
  { key: 'mrr', name: '平均倒数排名', metric: 'MRR', desc: '第一个正确答案排名的倒数平均值' },
  { key: 'vector_qa_accuracy', name: '向量检索', metric: '准确率', desc: '仅用向量检索的问答准确率' },
  { key: 'fulltext_qa_accuracy', name: '全文检索', metric: '准确率', desc: '仅用全文检索的问答准确率' },
  { key: 'hybrid_qa_accuracy', name: '混合检索', metric: '准确率', desc: '向量+全文融合检索的问答准确率' },
  { key: 'rerank_qa_accuracy', name: '重排序检索', metric: '准确率', desc: '混合检索+交叉编码器重排序的问答准确率' },
]

/* 相似度规则（规则评估-文本相似度） */
const SIM_METRICS = [
  'FUZZY_MATCH',
  'BLEU_4',
  'COSINE',
  'ROUGE_1',
  'ROUGE_2',
  'ROUGE_3',
  'ROUGE_4',
  'ROUGE_5',
  'ROUGE_L',
  'F1',
  'GLEU',
  'JACCARD',
  'LEVENSHTEIN',
  'ACCURACY',
]

/* 统计评估-Spearman相关系数 相似度计算方法 */
const SPEARMAN_SIM_METHODS = [
  { value: 'cosine', label: 'COSINE（余弦相似度）' },
  { value: 'euclidean', label: '欧氏距离（相似度 = -距离）' },
  { value: 'dot', label: '点积' },
]

/* 大模型评估-分类型 评分器模板 */
const CLASSIFY_TEMPLATES: Record<string, { label: string; prompt: string; labels: { pass: string; fail: string } }> = {
  standard: {
    label: '标准匹配',
    labels: { pass: 'Pass', fail: 'Fail' },
    prompt: `# 角色
你是一位专业的对话评估专家，擅长根据提供的标准对助理在对话中的最终反应进行评估，并确定其是否[[Pass]]或[[Fail]]。

## 技能
### 技能 1: 对话回顾
- 通读整个对话以理解上下文和背景信息。
- 确保全面理解对话的意图和用户的需求。

### 技能 2: 最终回答识别
- 从对话中准确识别出助理给出的最后一个回答。
- 确保关注的是最终的回答，而不是中间的部分。

### 技能 3: 标准应用
- 仔细审查每个评价标准。
- 将助理的最终回答与标准的各个方面进行详细比较。

### 技能 4: 逐步推理
- 记录每个标准以及最终响应如何满足或不满足该标准。
- 提供详细的证据，并解释为什么最终答复满足或不满足期望。

### 技能 5: 结果判定
- 根据逐步推理的结果，判断最终回答是[[Pass]]或[[Fail]]
- 提供明确的结论并解释理由。

## 输出格式
以下列格式提供结果：
- **分步推理：**[详细推理在这里]
- **最终结果：**[[Pass]]或[[Fail]]

## 限制
- 只针对对话中的最终回答进行评估。
- 在评估过程中，确保遵循提供的标准，避免主观判断。
- 如果标准含糊不清，尽最大努力解释并记录所做的假设。
- 保持评估过程的客观性和公正性。

# 示例

* *示例1:* *

- **对话:** 
  - 用户：“你能告诉我明天的天气吗？”
  - 助手：“是的，预计今天是晴天，最高气温25°C。”
  - 用户：“下午会下雨吗？”
  - 助手：“不，预报说今天下午不会下雨。”

- **最后回应：**“不，今天下午预报没有雨。”
- **标准:**
  1. 提供晴朗的天气预报。
  2. 直接回答用户的问题。

- **分步推理：**
  - 直接回答用户关于下午下雨的问题。
  - 它提供了一个明确的预报，说不会下雨。

- **最终结果：**[[Pass]]

* *示例2:* *

- **对话:** 
  - 用户：“明天办公室什么时候开门？”
  - 助手：“办公时间通常是上午9点到下午5点。”

- **最后回应：**“办公时间通常是上午9点到下午5点。”
- **标准:**
  1. 明确写明明天的营业时间。
  2. 避免含糊不清的信息。

- **分步推理：**
  - 回答中没有说明明天的具体开放时间；它使用了“通常”，这是模糊的。
  - 不符合具体的标准。

- **最终结果：**[[Fail]]

# 注意
- 考虑在以前的评估中可能没有遇到的新的或更新的标准。
- 如果标准含糊不清，尽最大努力解释并记录所做的假设。

# 问题
\${query}

# 参考答案（正样本）
\${positive}


# 标准

1: 评估正确性: 检查文本中的信息是否准确无误。确认事实、数据和引用的准确性。校验语法、拼写和标点符号的正确性。
2: 评估完整性:确保文本涵盖了所有必要的信息。检查是否有遗漏的关键内容或细节。确认文本是否完整地回答了问题或满足了需求。
3.评估流畅性:评价文本的阅读体验。检查句子结构是否合理，段落是否连贯。确保文本易于理解，没有冗余或重复的部分。
4.评估逻辑性:检查文本的逻辑结构和推理过程。确认论点和论证之间的逻辑关系。检查是否存在逻辑漏洞或不一致之处。
5: 评估相关性:确保文本与主题或目标紧密相关。检查内容是否紧扣主题，没有偏离。确认文本中的信息是否对用户的需求有实际帮助。
6: 评估安全性:检查文本中是否存在潜在的安全风险。确认文本中没有包含敏感信息或个人隐私。检查是否存在可能引发法律或道德问题的内容。`,
  },
  sentiment: {
    label: '情感分析',
    labels: { pass: '积极', fail: '中性、消极' },
    prompt: `# 角色
你是一位情感分析专家，擅长识别和评估文本中的情感基调。你能够通过分析用户输入的信息内容和上下文，确定其语气是消极的、中性的还是积极的。

## 技能
### 技能1：情感关键字识别
- 识别表明情感或情绪的关键字或短语。
- 注意任何可能影响情绪基调的上下文线索。

### 技能2：详细推理
- 清楚地说明信息中的证据。
- 解释为什么每个证据都有助于结论。
- 确保推理彻底，以验证结论的正确性。

### 技能3：整体语境评估
- 考虑整体语境和用词来评估情绪。
- 将信息的情绪语气分为以下几个等级：消极、中性或积极。

## 限制
- 仅基于提供的文本内容进行情感分析。
- 不引入个人偏见或主观判断。
- 确保推理过程详细且逻辑严密。

## 输出格式
- 推理：[详细推理在这里]
- 结果：“消极”、“中性”或“积极”

## 示例
**输入：**“我对服务不满意。”
* *输出:* *
- 推理：“不开心”这个短语表示不满。在这条信息中没有任何积极的元素，而且上下文明确暗示了一种消极的体验。
- 结果：消极

**输入：**“这顿饭还行，没什么特别的，但也不错。”
* *输出:* *
- 推理：“还行”这个词表示一种中性的感觉。像“没什么特别的”和“还不错”这样的短语既没有强烈的积极情绪，也没有强烈的消极情绪。
- 结果：中性

**输入：**“我在活动中度过了一段美好的时光！”
* *输出:* *
- 推理：“美好”这个词是一个强有力的积极指标。上下文暗示了一次愉快的经历。
- 结果：积极

## 数据
问题: \${query}
参考答案: \${positive}`,
  },
}

/* 大模型评估-数值型 评分器模板 */
const NUMERIC_TEMPLATES: Record<string, { label: string; prompt: string; threshold: number; name?: string; description?: string }> = {
  overall: {
    label: '综合评测',
    threshold: 3,
    prompt: `# 角色
你是一位资深的答案评估专家，擅长对大模型生成的结果进行细致的评分和反馈。你的角色是确保答案的质量符合高标准，并且能够提供具体的改进建议。

## 技能
### 技能1：评估相关性
- **任务**：根据用户提出的问题，评估回答的相关性。
  - 确保回答内容直接针对用户的问题，避免无关信息。
  - 评估回答是否全面覆盖了用户问题的所有方面。

### 技能2：评估文化敏感与无害
- **任务**：检查回答是否尊重用户的文化背景和差异。
  - 确保回答内容合乎伦理道德，避免文化偏见和不敏感的表达。
  - 检查回答中是否包含任何可能冒犯的内容，并提出改进建议。

### 技能3：评估信息丰富性
- **任务**：评估回答的信息丰富程度。
  - 确保回答在保证准确性的同时提供详尽的信息。
  - 评估回答是否包含了用户可能未明确要求但对理解问题有帮助的背景信息。

### 技能4：评估清晰性
- **任务**：评估回答的清晰度。
  - 确保回答使用了清晰、易懂的语言。
  - 避免使用可能引起误解的专业术语或复杂构造。
  - 提供改进建议以提高回答的可读性和易理解性。

### 技能5：评估用户参与度
- **任务**：评估回答是否能够吸引用户的兴趣并保持其参与度。
  - 确保回答具有吸引力，能够激发用户的兴趣。
  - 评估回答是否提供了互动的机会，如提问或进一步讨论的建议。

## 限制
- 评估过程中必须严格遵守上述五个评判标准。
- 评估结果应客观公正，不得带有个人偏见。
- 在提供改进建议时，应具体明确，便于改进。
- 评估过程中需尊重用户的文化背景和差异，确保回答内容无害且合适。
- 评估结果应基于最新的行业标准和最佳实践。

## 要求
请输出评分原因和评分分数，分数在1-5之间，分数越高表示大模型的回答质量越高。

## 数据
问题:\${query}
参考答案:\${positive}`,
  },
  similarity: {
    label: '语义相似度',
    threshold: 4,
    prompt: `# 角色
你是一名专业的评估专家，擅长在1到5的范围内评估给定输出与基本事实之间的相似程度。你的评估基于详细的思维链推理，确保逐步推理和透明度。

## 技能
### 技能 1: 识别关键要素
- **任务**：识别并列出在输出和基本事实中存在的关键要素。
  - 确定句子中的主要信息和核心概念。
  - 识别句子中的关键名词、动词和形容词。

### 技能 2: 比较关键要素
- **任务**：比较这些关键元素，从内容和结构两方面来评估它们的异同。
  - 分析句子的内容，包括描述的对象、动作和属性。
  - 比较句子的结构，包括句法和语序。

### 技能 3: 语义分析
- **任务**：分析输出和真实值所传达的语义，注意任何显著的偏差。
  - 评估句子的整体意义和意图。
  - 识别任何可能导致误解或歧义的部分。

### 技能 4: 相似度分类
- **任务**：基于这些比较，根据定义的标准对相似程度进行分类。
  - 使用以下标准进行分类：
    - 5：高度相似-输出值和实际值几乎相同，只有微小的、不显著的差异。
    - 4：有些相似-输出在很大程度上与ground truth相似，但几乎没有明显的差异。
    - 3：适度相似-有一些明显的差异，但核心本质是在输出中捕获的。
    - 2：稍微相似-输出只捕获地面真相的几个元素，并包含一些差异。
    - 1：不相似-输出与地面真实值明显不同，很少或没有匹配元素。

### 技能 5: 评分解释
- **任务**：写出为什么选择一个特定分数的原因，以确保透明度和正确性。
  - 提供详细的推理过程，解释每个步骤的依据。
  - 说明选择特定分数的理由，确保评估的公正性和一致性。

### 技能 6: 最终评分
- **任务**：根据定义的标准分配相似度分数。
  - 以整数（1、2、3、4或5）的形式提供最终的相似性得分。

## 限制
- 始终致力于提供公平和平衡的评估。
- 在评估中同时考虑句法和语义的差异。
- 对相似对评分的一致性对于准确测量至关重要。
- 评估过程中保持透明度，详细记录每一步的推理过程。
- 不引入个人观点或偏见，确保评估的客观性。

## 数据
问题:\${query}
参考答案:\${positive}
错误答案:\${negative}`,
  },
  hallucination: {
    label: '幻觉率',
    threshold: 4,
    name: '幻觉率',
    description: '评估回答是否存在事实错误或幻觉，1~5分，得分越高表示幻觉越少',
    prompt: `# 角色
你是一位严谨的答案事实核查专家，擅长识别大模型生成内容中是否存在事实错误、虚构信息或与参考答案不一致的表述，并对幻觉程度进行分级。

## 技能
### 技能 1：提取关键事实
- 从参考答案（正样本）中逐条提取关键事实、数据、专有名词与结论。
- 将生成回答按句拆分，标注每句话对应的论述点。

### 技能 2：逐条比对
- 将生成回答的每个论点与参考答案的关键事实逐一比对。
- 检查是否存在捏造、张冠李戴、数据错误或与参考相悖的表述。

### 技能 3：幻觉程度分级
根据幻觉的数量与严重程度给出 1~5 分：
- 5 分：回答完全准确，与参考答案一致，无任何虚构或事实错误。
- 4 分：回答基本准确，仅有不影响理解的轻微不精确或次要细节偏差。
- 3 分：回答部分准确，存在若干事实偏差或次要幻觉。
- 2 分：回答存在较多事实错误或明显幻觉，可能误导读者。
- 1 分：回答大量错误或严重幻觉，核心事实与参考答案相悖。

## 限制
- 仅以【参考答案】为依据判定事实，不引入外部知识。
- 评分应客观一致，聚焦事实准确性与幻觉程度，不评价措辞与文采。

## 输出格式
- 分步推理：[详细说明发现的幻觉点与依据]
- 评分：[1~5 的整数]

## 数据
问题: \${query}
参考答案: \${positive}`,
  },
  relevance: {
    label: '答案相关性',
    threshold: 3,
    name: '答案相关性',
    description: '评估回答与问题的相关程度，1~5分，得分越高表示越切题',
    prompt: `# 角色
你是一位答案相关性评审专家，擅长判断一段回答在多大程度上紧扣用户问题，甄别其中跑题、冗余或无关的内容。

## 技能
### 技能 1：识别问题核心
- 提炼用户问题所问的核心对象、约束条件与期望的回答要点。

### 技能 2：分析回答内容
- 将回答拆解为若干信息单元，逐一判断其与问题核心的关联程度。
- 识别回答中偏离主题、泛泛而谈或答非所问的部分。

### 技能 3：相关性分级
根据回答的切题程度给出 1~5 分：
- 5 分：回答完全切题，所有内容都紧密围绕问题核心。
- 4 分：回答大部分切题，仅有少量可忽略的无关信息。
- 3 分：回答基本切题，但存在部分偏离或冗余。
- 2 分：回答明显偏离主题，仅少量内容与问题相关。
- 1 分：回答完全不切题，与问题几乎无关。

## 限制
- 仅评估回答与问题的相关性，不评判回答本身的正确性。
- 评分应客观一致，避免个人偏好。

## 输出格式
- 分步推理：[详细说明回答与问题的关联情况]
- 评分：[1~5 的整数]

## 数据
问题: \${query}
参考答案: \${positive}`,
  },
  completeness: {
    label: '答案完整性',
    threshold: 3,
    name: '答案完整性',
    description: '评估回答是否覆盖问题所需的所有必要信息，1~5分，得分越高表示越完整',
    prompt: `# 角色
你是一位答案完整性评审专家，擅长判断回答是否全面覆盖了问题所要求的所有必要信息，识别遗漏的关键要点。

## 技能
### 技能 1：厘清必要信息点
- 从问题与参考答案中归纳出回答必须覆盖的核心信息点与关键细节。

### 技能 2：逐点核查覆盖情况
- 将回答与参考答案的必要信息点逐一比对。
- 记录回答中已覆盖、部分覆盖与完全遗漏的要点。

### 技能 3：完整性分级
根据信息覆盖程度给出 1~5 分：
- 5 分：回答全面覆盖所有必要信息，无关键遗漏。
- 4 分：回答覆盖绝大部分必要信息，仅缺少次要细节。
- 3 分：回答覆盖核心信息，但缺少若干重要细节。
- 2 分：回答遗漏了多个关键信息点。
- 1 分：回答几乎没有覆盖问题所需的核心信息。

## 限制
- 仅评估回答的信息完整性，不评判信息是否正确。
- 评分应客观一致，聚焦遗漏程度。

## 输出格式
- 分步推理：[列出已覆盖与遗漏的要点]
- 评分：[1~5 的整数]

## 数据
问题: \${query}
参考答案: \${positive}`,
  },
}

export default function EvalDimensionCreatePage() {
  const navigate = useNavigate()

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [evalType, setEvalType] = useState('llm_classify')
  const [providers, setProviders] = useState<Provider[]>([])

  // 大模型评估-分类型
  const [judgeModel, setJudgeModel] = useState('')
  const [classifyTemplate, setClassifyTemplate] = useState('standard')
  const [classifyPrompt, setClassifyPrompt] = useState(CLASSIFY_TEMPLATES.standard.prompt)
  const [labels, setLabels] = useState(CLASSIFY_TEMPLATES.standard.labels)

  // 大模型评估-数值型
  const [numJudgeModel, setNumJudgeModel] = useState('')
  const [numericTemplate, setNumericTemplate] = useState('overall')
  const [numericPrompt, setNumericPrompt] = useState(NUMERIC_TEMPLATES.overall.prompt)
  const [numericThreshold, setNumericThreshold] = useState(NUMERIC_TEMPLATES.overall.threshold)

  // 规则评估-文本相似度
  const [simMetric, setSimMetric] = useState('FUZZY_MATCH')
  const [simThreshold, setSimThreshold] = useState(0.8)
  const [simFieldA, setSimFieldA] = useState('${positive}')
  const [simFieldB, setSimFieldB] = useState('${negative}')

  // 检索评估
  const [topK, setTopK] = useState(5)
  const [recallK, setRecallK] = useState(5)
  const [retrievalMetric, setRetrievalMetric] = useState('recall_at_5')

  // 统计评估-Spearman相关系数
  const [spearmanSimMethod, setSpearmanSimMethod] = useState('cosine')
  const [spearmanThreshold, setSpearmanThreshold] = useState(0.5)
  const [spearmanOutputType, setSpearmanOutputType] = useState('numeric')

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    providerApi.list().then((r) => setProviders(r.providers)).catch(() => { })
  }, [])

  const chooseClassifyTemplate = (key: string) => {
    const t = CLASSIFY_TEMPLATES[key]
    if (!t) return
    setClassifyTemplate(key)
    setClassifyPrompt(t.prompt)
    setLabels(t.labels)
  }

  const chooseNumericTemplate = (key: string) => {
    const t = NUMERIC_TEMPLATES[key]
    if (!t) return
    setNumericTemplate(key)
    setNumericPrompt(t.prompt)
    setNumericThreshold(t.threshold)
    if (t.name) setName(t.name)
    if (t.description) setDescription(t.description)
  }

  const buildConfig = (): Record<string, unknown> => {
    if (evalType === 'llm_classify') {
      return {
        judge_model: judgeModel,
        template: classifyTemplate,
        prompt: classifyPrompt,
        labels: { Pass: labels.pass, Fail: labels.fail },
      }
    }
    if (evalType === 'llm_numeric') {
      return {
        judge_model: numJudgeModel,
        template: numericTemplate,
        prompt: numericPrompt,
        score_min: 0,
        score_max: 5,
        threshold: numericThreshold,
      }
    }
    if (evalType === 'rule_sim') {
      return {
        field_a: simFieldA,
        field_b: simFieldB,
        metric: simMetric,
        threshold: simThreshold,
      }
    }
    if (evalType === 'retrieval') {
      const cfg: Record<string, unknown> = { metric: retrievalMetric }
      if (retrievalMetric === 'recall_at_5') {
        cfg.recall_k = recallK
      } else {
        cfg.top_k = topK
      }
      return cfg
    }
    if (evalType === 'spearman') {
      return {
        similarity_method: spearmanSimMethod,
        threshold: spearmanThreshold,
        output_type: spearmanOutputType,
      }
    }
    return {}
  }

  const handleSubmit = async () => {
    if (!name.trim()) return setError('请输入维度名称')
    setSubmitting(true)
    setError('')
    try {
      await mlApi.createDimension({
        name: name.trim(),
        description: description.trim(),
        eval_type: evalType,
        eval_config: buildConfig(),
      })
      navigate('/ml/eval?tab=dimensions')
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  const inputCls = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-indigo-500'

  const providerOptions = providers.map((p) => ({
    value: p.id,
    label: p.model_name && p.name !== p.model_name ? `${p.name}（${p.model_name}）` : p.name,
  }))

  const providerSelect = (value: string, onChange: (v: string) => void) => (
    <Select
      value={value}
      onChange={onChange}
      placeholder="请选择裁判模型"
      options={providerOptions}
      className="w-full"
    />
  )

  return (
    <div>
      <div className="mb-4 flex items-center gap-2 text-sm text-slate-400">
        <button type="button" onClick={() => navigate('/ml/eval?tab=dimensions')} className="hover:text-slate-600">模型评测</button>
        <ChevronRight size={14} />
        <span className="font-medium text-slate-900">创建评测维度</span>
      </div>

      <div className="mx-auto max-w-3xl space-y-6">
        {/* 基础信息：默认显示名称 / 描述 / 类型 */}
        <section className="rounded-xl border border-slate-200 bg-white p-6">
          <h3 className="mb-4 text-base font-semibold text-slate-900">基础信息</h3>
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                维度名称 <span className="text-red-500">*</span>
              </label>
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={50} placeholder="请输入维度名称" className={inputCls} />
              <div className="mt-1 text-right text-xs text-slate-400">{name.length}/50</div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">描述</label>
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} rows={2} placeholder="评测标准说明（选填）" className={inputCls} />
              <div className="mt-1 text-right text-xs text-slate-400">{description.length}/200</div>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-slate-700">
                类型 <span className="text-red-500">*</span>
              </label>
              <div className="flex flex-wrap gap-2">
                {EVAL_TYPES.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    onClick={() => setEvalType(t.value)}
                    className={`rounded-lg border px-4 py-2 text-sm transition-colors ${evalType === t.value
                      ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                      : 'border-slate-200 text-slate-600 hover:border-slate-300'
                      }`}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* 大模型评估-分类型 */}
        {evalType === 'llm_classify' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">大模型评估配置</h3>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">裁判模型</label>
                {providerSelect(judgeModel, setJudgeModel)}
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">评分器模板</label>
                <div className="flex gap-2">
                  {Object.entries(CLASSIFY_TEMPLATES).map(([key, t]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => chooseClassifyTemplate(key)}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${classifyTemplate === key
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="block text-sm font-medium text-slate-700">Prompt</label>
                  <button
                    type="button"
                    onClick={() => setClassifyPrompt(CLASSIFY_TEMPLATES[classifyTemplate].prompt)}
                    className="text-xs text-indigo-600 hover:underline"
                  >
                    恢复默认 Prompt
                  </button>
                </div>
                <textarea value={classifyPrompt} onChange={(e) => setClassifyPrompt(e.target.value)} rows={12} className={`${inputCls} font-mono text-xs leading-relaxed`} />
                <p className="mt-1 text-xs text-slate-400">
                  支持变量：<code className="rounded bg-indigo-50 px-1 text-indigo-600">{'${query}'}</code>
                  <code className="ml-1 rounded bg-indigo-50 px-1 text-indigo-600">{'${positive}'}</code>
                  <code className="ml-1 rounded bg-indigo-50 px-1 text-indigo-600">{'${negative}'}</code>
                </p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">标签选项</label>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <span className="mb-1 block text-sm font-medium text-slate-700">Pass</span>
                    <p className="mb-2 text-xs leading-relaxed text-slate-400">评测数据通过评估，计算评估维度得分时，该分类下所有标签情况均会被视作Pass。</p>
                    <input value={labels.pass} onChange={(e) => setLabels((p) => ({ ...p, pass: e.target.value }))} className={inputCls} />
                  </div>
                  <div>
                    <span className="mb-1 block text-sm font-medium text-slate-700">Fail</span>
                    <p className="mb-2 text-xs leading-relaxed text-slate-400">评测数据不通过评估，计算评估维度得分时，该分类下所有标签情况均会被视作Fail。</p>
                    <input value={labels.fail} onChange={(e) => setLabels((p) => ({ ...p, fail: e.target.value }))} className={inputCls} />
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 大模型评估-数值型 */}
        {evalType === 'llm_numeric' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">大模型评估配置</h3>
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">裁判模型</label>
                {providerSelect(numJudgeModel, setNumJudgeModel)}
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">评分器模板</label>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(NUMERIC_TEMPLATES).map(([key, t]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => chooseNumericTemplate(key)}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${numericTemplate === key
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="block text-sm font-medium text-slate-700">Prompt</label>
                  <button
                    type="button"
                    onClick={() => setNumericPrompt(NUMERIC_TEMPLATES[numericTemplate].prompt)}
                    className="text-xs text-indigo-600 hover:underline"
                  >
                    恢复默认 Prompt
                  </button>
                </div>
                <textarea value={numericPrompt} onChange={(e) => setNumericPrompt(e.target.value)} rows={12} className={`${inputCls} font-mono text-xs leading-relaxed`} />
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">评分范围</label>
                <p className="text-sm text-slate-600">0 - 5</p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  通过阈值：<span className="font-mono text-indigo-600">{numericThreshold}</span>
                  <span className="ml-2 text-xs font-normal text-slate-400">（大于等于该阈值为 Pass）</span>
                </label>
                <input
                  type="range"
                  min={0}
                  max={5}
                  step={0.5}
                  value={numericThreshold}
                  onChange={(e) => setNumericThreshold(Number(e.target.value))}
                  className="w-full accent-indigo-600"
                />
                <div className="flex justify-between text-xs text-slate-400">
                  <span>0</span>
                  <span>5</span>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 规则评估-文本相似度 */}
        {evalType === 'rule_sim' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">文本相似度配置</h3>
            <div className="space-y-4">
              <div className="grid grid-cols-[1fr_auto_1fr] items-start gap-3">
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">文本 A</label>
                  <textarea value={simFieldA} onChange={(e) => setSimFieldA(e.target.value)} rows={4} className={`${inputCls} font-mono text-xs`} />
                  <div className="mt-1 flex gap-1">
                    {['query', 'positive', 'negative'].map((v) => (
                      <button key={v} type="button" onClick={() => setSimFieldA((s) => s + `\${${v}}`)} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 hover:bg-slate-200">
                        {`\${${v}}`}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="py-6">
                  <label className="mb-1 block text-center text-sm font-medium text-slate-700">相似度规则</label>
                  <Select
                    value={simMetric}
                    onChange={setSimMetric}
                    options={SIM_METRICS.map((m) => ({ value: m, label: m }))}
                    className="w-44"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">文本 B</label>
                  <textarea value={simFieldB} onChange={(e) => setSimFieldB(e.target.value)} rows={4} className={`${inputCls} font-mono text-xs`} />
                  <div className="mt-1 flex gap-1">
                    {['query', 'positive', 'negative'].map((v) => (
                      <button key={v} type="button" onClick={() => setSimFieldB((s) => s + `\${${v}}`)} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600 hover:bg-slate-200">
                        {`\${${v}}`}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  通过阈值：<span className="font-mono text-indigo-600">{simThreshold.toFixed(2)}</span>
                </label>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={simThreshold}
                  onChange={(e) => setSimThreshold(Number(e.target.value))}
                  className="w-full accent-indigo-600"
                />
                <div className="flex justify-between text-xs text-slate-400">
                  <span>0.00</span>
                  <span>1.00</span>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 检索评估 */}
        {evalType === 'retrieval' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">检索评估配置</h3>
            <div className="space-y-4">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">检索类型</label>
                <div className="flex flex-wrap gap-2">
                  {RETRIEVAL_METRICS.map((m) => (
                    <button
                      key={m.key}
                      type="button"
                      onClick={() => {
                        setRetrievalMetric(m.key)
                        setName(m.name)
                        setDescription(m.desc)
                      }}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${retrievalMetric === m.key
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {m.name}
                    </button>
                  ))}
                </div>
              </div>
              {retrievalMetric === 'recall_at_5' ? (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">Recall</label>
                  <input
                    type="number"
                    min={1}
                    max={10}
                    value={recallK}
                    onChange={(e) => setRecallK(Math.min(10, Math.max(1, Number(e.target.value) || 1)))}
                    className={`${inputCls} w-40`}
                  />
                </div>
              ) : (
                <div>
                  <label className="mb-1 block text-sm font-medium text-slate-700">Top-K设置</label>
                  <input
                    type="number"
                    min={1}
                    value={topK}
                    onChange={(e) => setTopK(Math.max(1, Number(e.target.value) || 1))}
                    className={`${inputCls} w-40`}
                  />
                </div>
              )}
            </div>
          </section>
        )}

        {/* 统计评估-Spearman相关系数 */}
        {evalType === 'spearman' && (
          <section className="rounded-xl border border-slate-200 bg-white p-6">
            <h3 className="mb-4 text-base font-semibold text-slate-900">统计评估配置</h3>
            <div className="space-y-4">
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">相似度计算方法</label>
                <div className="flex flex-wrap gap-2">
                  {SPEARMAN_SIM_METHODS.map((m) => (
                    <button
                      key={m.value}
                      type="button"
                      onClick={() => setSpearmanSimMethod(m.value)}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${spearmanSimMethod === m.value
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
                <p className="mt-2 text-xs leading-relaxed text-slate-400">
                  用于将模型输出与参考答案向量化后计算相似度，得到模型打分序列。
                </p>
              </div>
              <div>
                <label className="mb-1 block text-sm font-medium text-slate-700">
                  通过阈值：<span className="font-mono text-indigo-600">{spearmanThreshold.toFixed(2)}</span>
                  <span className="ml-2 text-xs font-normal text-slate-400">（Spearman 相关系数的通过阈值，范围 -1 ~ 1）</span>
                </label>
                <input
                  type="range"
                  min={-1}
                  max={1}
                  step={0.01}
                  value={spearmanThreshold}
                  onChange={(e) => setSpearmanThreshold(Number(e.target.value))}
                  className="w-full accent-indigo-600"
                />
                <div className="flex justify-between text-xs text-slate-400">
                  <span>-1.00</span>
                  <span>0.00</span>
                  <span>1.00</span>
                </div>
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium text-slate-700">输出类型</label>
                <div className="flex gap-2">
                  {[
                    { value: 'numeric', label: '数值型（-1 到 1）' },
                    { value: 'classify', label: '分类型（Pass/Fail）' },
                  ].map((o) => (
                    <button
                      key={o.value}
                      type="button"
                      onClick={() => setSpearmanOutputType(o.value)}
                      className={`rounded-lg border px-4 py-2 text-sm transition-colors ${spearmanOutputType === o.value
                        ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                        : 'border-slate-200 text-slate-600 hover:border-slate-300'
                        }`}
                    >
                      {o.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        {error && <p className="text-sm text-red-600">{error}</p>}

        {/* 底部操作 */}
        <div className="flex justify-end gap-3">
          <button type="button" onClick={() => navigate('/ml/eval?tab=dimensions')} className="rounded-lg border border-slate-200 px-5 py-2 text-sm text-slate-600 hover:bg-slate-50">
            取消
          </button>
          <button type="button" onClick={handleSubmit} disabled={submitting} className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm text-white hover:bg-indigo-700 disabled:opacity-60">
            {submitting && <Loader2 size={14} className="animate-spin" />}
            保存
          </button>
        </div>
      </div>
    </div>
  )
}