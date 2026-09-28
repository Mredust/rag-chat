# RAG Chat

基于 FastAPI + React 的检索增强生成（RAG）系统，涵盖「知识库构建 → 向量模型管理 → 模型调优 → 模型测评 → 排行榜对比 → 智能问答」全链路。本文档是项目的完整使用说明，内容包括：环境依赖、从空目录把前后端跑起来的完整步骤、日常运维操作，以及微调训练的硬件配置建议。

## 技术栈

- 后端：FastAPI + SQLAlchemy（async）+ Alembic + MySQL + ChromaDB
- 前端：React 19 + Vite + TypeScript + Tailwind CSS + ECharts
- 模型：sentence-transformers（Embedding 微调）、bge-large-zh-v1.5（本地向量模型）、bge-reranker-base（交叉编码器重排序）、DeepSeek（OpenAI 兼容 LLM）

## 目录结构

```
rag-chat/
├── app/            # 后端（api / services / rag / ai / models / schemas）
├── frontend/       # 前端 React 项目
├── alembic/        # 数据库迁移
├── models/         # 本地模型（基座向量模型 + 微调产物）
├── rerankers/      # 重排序模型（bge-reranker-base）
├── knowledges/     # 知识库样例文档
├── data/           # Chroma 向量库、训练产物
├── main.py         # 后端入口
├── .env            # 环境配置（复制 .env.example 生成）
└── requirements.txt
```

## 环境依赖

| 依赖 | 版本要求 | 说明 |
|---|---|---|
| Python | **3.12+** | `pyproject.toml` 中 `requires-python = ">=3.12"`，以此为准 |
| Node.js | **20 LTS+** | 前端 Vite 8 建议较新版本；npm 随 Node 自带 |
| MySQL | **5.7.6+**（推荐 8.x） | 全文检索依赖 InnoDB 的 ngram 解析器 |
| Git | 任意 | 拉取代码 |

本地向量模型依赖 `sentence-transformers` 与 `torch`，`torch` 体积较大，无独立显卡时建议安装 CPU 版（见下文）。

---

## 快速启动

### 1. 拉取后先确认：缺什么、补什么

项目的 `.gitignore` 忽略了不少运行必需的内容，**空目录 `git clone` 之后这些文件并不在仓库里，必须手动补齐**：

| 被 `.gitignore` 忽略的项 | 含义 | 是否必须 | 需要做什么 |
|---|---|---|---|
| `.env` | 环境配置（数据库密码、计算设备等） | ✅ 必须 | 复制 `.env.example` 并填写 |
| `.venv/`、`venv/` | Python 虚拟环境 | ✅ 必须 | 新建虚拟环境并安装依赖 |
| `models/` | 本地向量模型（基座 + 微调产物） | ✅ 必须 | 下载 `bge-large-zh-v1.5` 到 `models/system/` |
| `rerankers/` | 重排序交叉编码器 | ⚠️ 可选 | 下载 `bge-reranker-base`；不配则自动回退词法重排 |
| `data/*`（保留 `data/sample/`） | Chroma 向量库 / 数据集 / 上传文件 | ➖ 运行时生成 | 应用启动与使用时自动创建 |
| `logs/`、`uploads/` | 日志与上传目录 | ➖ 运行时生成 | 应用自动创建 |
| `frontend/node_modules/` | 前端依赖 | ✅ 必须 | `npm install` |
| `temp/`、`/docs` | 论文/文档 | ❌ 无关 | 不涉及启动 |

也就是说，**必须手动补 4 类东西**——① `.env`、② Python 依赖环境、③ 本地模型 `bge-large-zh-v1.5`、④ 前端 `node_modules`，另外还要在 MySQL 里建好数据库。下面按顺序逐项完成。

### 2. 配置环境变量

```bash
cp .env.example .env
```

然后编辑 `.env`。**真正必须在 `.env` 里填的只有数据库连接**，大模型与 Embedding 的地址/Key 在系统内配置即可：

| 配置 | 是否必填 | 说明 |
| --- | --- | --- |
| `MYSQL_HOST/PORT/USER/PASSWORD/DB` | ✅ 必填 | MySQL 连接信息，密码必填，库名需与第 5 步建库一致 |
| `EMBEDDING_DEVICE` | ✅ 建议保留 | 计算设备：`cpu` / `cuda` / `auto`（`.env.example` 为 `auto`）。代码默认值是 `cpu`，删掉此行会静默禁用 GPU |
| `CHROMA_PERSIST_DIR` | ➖ 可选 | 向量库持久化目录，默认 `./data/chroma` |
| `JWT_SECRET`、`CORS_ORIGINS` | ➖ 可选 | 生产环境建议改掉默认 `JWT_SECRET` |

大模型与 Embedding 相关配置**优先在系统界面里维护**：

- **大模型**：进入「供应商管理」添加并**激活**供应商（OpenAI 兼容地址 + Key + 模型，如 DeepSeek、阿里云百炼）。运行时激活的供应商会覆盖一切 LLM 配置（`config_service.get_runtime`），因此不需要在 `.env` 写 `LLM_*`——兜底默认值定义在 `app/core/config.py`。
- **Embedding**：本地已下载 `models/system/bge-large-zh-v1.5` 时无需任何配置，系统自动走本地模型；如需改用远程 Embedding 或调整模型名/向量维度，在「系统设置 → Embedding」中填写 `embedding_api_base/key/model/dim` 即可，留空即本地模式，同样无需在 `.env` 写 `EMBEDDING_*`。

### 3. 安装后端依赖

```bash
python -m venv .venv
# Windows PowerShell：
.venv\Scripts\Activate.ps1
# Linux/macOS：
source .venv/bin/activate

pip install -r requirements.txt
# 或使用 uv（项目已提供 uv.lock）：
uv sync
```

本地向量模型建议安装 **CPU 版 torch** 以减小体积（无 GPU 时必选）：

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

有 NVIDIA 显卡需要 GPU 加速时，按 PyTorch 官方指引安装对应 CUDA 版本即可，同时确保 `.env` 中 `EMBEDDING_DEVICE` 为 `auto` 或 `cuda`（该项由 `.env` 控制，代码已统一走设备自动解析，无需改源码）。

### 4. 下载本地模型

**向量模型（必需）**：`.gitignore` 忽略了整个 `models/`，基座模型需手动下载到 `models/system/bge-large-zh-v1.5`：

```bash
huggingface-cli download BAAI/bge-large-zh-v1.5 --local-dir models/system/bge-large-zh-v1.5
```

国内网络慢时先设置 HF 镜像（PowerShell：`$env:HF_ENDPOINT="https://hf-mirror.com"`；bash：`export HF_ENDPOINT=https://hf-mirror.com`），下载后约 1.3GB。不下载也能启动，但向量化会降级为「哈希特征向量」，检索质量无法用于正式实验。

**重排序模型（可选）**：`rerankers/` 同样被忽略，如需真实交叉编码器精排：

```bash
huggingface-cli download BAAI/bge-reranker-base --local-dir rerankers/bge-reranker-base
```

不下载也不影响启动：加载失败时 `app/rag/reranker.py` 的 `build_reranker` 会自动回退词法代理重排。

### 5. 创建 MySQL 数据库

依赖安装完后，配置里指定的数据库（默认 `ragchat`）需要提前建好，表结构由 Alembic 迁移自动创建：

```sql
CREATE DATABASE ragchat CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

### 6. 安装前端依赖

```bash
cd frontend
npm install
```

### 7. 启动后端（端口 4040）

```bash
# 激活虚拟环境后
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 4040 --reload
```

启动时 `lifespan` 会自动执行 `alembic upgrade head` 建表；如需手动迁移：

```bash
alembic upgrade head
```

验证：访问 `http://localhost:4040/health` 返回 `{"status":"ok"}` 即成功。

**内置数据（首次启动自动导入）**：全新空库的第一次启动会自动导入根目录的 `ragchat.sql`——含内置「法律」知识空间（6 篇文档 / 398 个切片）、admin 账号（admin@qq.com）、数据集与微调/测评任务、以及 LLM 供应商配置。导入在单个事务中完成；库中已有数据的后续启动会自动跳过，删除数据库后重启则会重新导入。导入后启动时的向量自检会把切片向量在后台补齐到 Chroma，补齐完成前向量检索可能命中不全，全文检索立即可用。注意：文档的上传原文件（`data/uploads/`）不在仓库中，文档列表与检索不受影响，但原文查看需重新上传对应文件。

### 8. 启动前端（端口 4041）

```bash
cd frontend
npm run dev
```

访问 `http://localhost:4041`。前端 `/api` 代理默认指向 `http://127.0.0.1:4040`，登录等接口经代理转发到后端；后端路由本身已带 `/api/v1` 前缀，代理原样转发、**无需 rewrite**。若要把后端改成其他端口，需同步修改两处：`main.py` 的 `uvicorn.run` 端口与 `frontend/vite.config.ts` 的代理 `target`，否则前端会报 `ECONNREFUSED`。

---

## 常用操作

- **配置重排序**：进入「系统设置 → 重排序」，开启 `rerank_enabled` 并填入 `rerank_model`（项目根目录相对路径，正斜杠且不含盘符，如 `rerankers/bge-reranker-base`），重启后端后日志打印「加载交叉编码器」即生效。
- **导入向量模型**：「我的模型 → 导入模型文件夹」，将模型目录保存到 `models/` 并登记 `model_dir`。

---

## 模型微调与硬件配置

本项目微调的是 **Embedding（向量）模型**，不是大语言模型（LLM），硬件门槛远低于大模型微调，租卡前值得先看清训练的真实形态。

**训练特点**：

1. 微调对象是 `bge-large-zh-v1.5`（约 **3.35 亿参数 / 0.33B**，24 层、1024 隐藏维度），也可导入 `Octen-Embedding-0.6B`（约 6 亿参数）。
2. 训练方式为 `sentence-transformers` 对比学习（`MultipleNegativesRankingLoss` + 难负样本），**全参数 AdamW 微调**（非 LoRA、非冻结骨干）。
3. 默认超参与训练时的计算设备由配置项控制（见 `app/core/config.py` 与 `app/services/ml_service.py`），常用默认值为 `num_epochs=3`、`batch_size=16`、`lr=2e-5`、`passage_max_len=512`。

**显存估算**（以 0.33B 全参数 AdamW 微调为例）：

| 项目 | FP32（当前代码） | FP16 / 混合精度 |
|---|---|---|
| 模型权重 | 1.34 GB | 0.67 GB |
| 梯度 | 1.34 GB | 0.67 GB |
| AdamW 优化器状态（m+v） | 2.68 GB | 2.68 GB（保持 FP32） |
| 激活值（batch=16、seq=512） | 2~4 GB | 1~2 GB |
| **合计** | **约 8~10 GB** | **约 5~7 GB** |

> 口诀：`0.33B 全参微调 ≈ 8~10GB 显存（FP32）`；换用 0.6B 级模型显存需求约翻倍（16~20GB）。**数据量对显存的边际影响很小**——显存主要由模型大小 + batch_size + seq_len 决定，5 万条相对 1000 条主要增加的是训练时长而非显存。

**配置速览**：

| 场景 | 数据量 | 笔记本配置 | 云服务器配置 |
|---|---|---|---|
| 功能测试 | 1000 条 | 可纯 CPU 跑（约 30 分钟~1 小时）；建议带 6GB+ 独显 + 32GB 内存 | T4 16GB / 8 vCPU 32GB 内存 |
| 正式实验 | 5 万条 | 独立显卡 12GB+ 显存（如 RTX 4080/4090 Laptop）、32GB 内存 | A10/RTX 4090 24GB 单卡，16 vCPU 64GB 内存 |

- **笔记本**：1000 条场景最低 16GB 内存的任意现代笔记本即可纯 CPU 跑通；5 万条场景约 9400 步，8GB 卡总时长数小时到十几小时，长时间满负载需注意散热与供电。
- **云服务器**：功能测试用 T4 16GB 性价比最高（100GB SSD）；正式实验单卡 A10/RTX 4090 24GB 已非常充裕（16 vCPU + 64GB 内存、200GB SSD）。预算有限时 T4 16GB 把 `batch_size` 降到 8 也能跑 0.33B 模型，时长约十几小时，按量付费即可；0.6B 级模型建议显存上到 16~24GB。

**重要提醒**：

1. **先确认设备再用 GPU**：训练与推理设备由 `.env` 的 `EMBEDDING_DEVICE` 决定（默认 `auto`，CUDA 可用则用 cuda），若该值为 `cpu` 则即使租了 GPU 也只跑 CPU——租卡后先核对配置再启动。
2. **不需要 A100/H100**：0.33B 向量模型门槛很低，被“微调”二字误导去租 80GB 大卡是浪费。
3. **混合精度**：当前训练未开启 AMP（无 `autocast`/`GradScaler`），启用 FP16 可把显存从 8~10GB 降到 5~7GB，让 6GB 显卡更稳妥，可作为后续优化。

---

## 注意事项

- `chunk.content` 的中文全文索引（ngram）通过 Alembic 迁移自动创建，需 MySQL 5.7.6+；若迁移报错可手动执行 `ALTER TABLE chunk ADD FULLTEXT INDEX ft_chunk_content (content) WITH PARSER ngram;`。
- 本地向量模型首次加载会下载/加载权重，耗时较长，加载后走进程内缓存，属正常现象。

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 登录报 `ECONNREFUSED` | vite 代理端口与后端实际端口不一致 | 核对 `frontend/vite.config.ts` 的代理 `target` 是否为 4040 |
| 启动报 MySQL 连接失败 | 数据库未建 / `.env` 密码不对 | 建库并核对 `.env` |
| 迁移报 FULLTEXT/ngram 错误 | MySQL 版本过低 | 升级到 5.7.6+ 或 8.x |
| 向量检索质量差 | 本地模型未下载，已降级哈希向量 | 下载 `bge-large-zh-v1.5` 并重启 |
| 重排序未生效 | `rerankers/` 未下载或开关未开启 | 下载 `bge-reranker-base`，在系统设置中开启后重启 |
| 后端报 `_SimpleFormatter` pickle 错误 | uvicorn reload 多进程问题 | 本项目已修复（类移到 `main` 块外） |
| 首次启动慢 | 本地向量模型加载较久 | 加载后走进程内缓存，属正常现象 |
