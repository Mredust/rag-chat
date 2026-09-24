# RAG Chat

基于 FastAPI + React 的检索增强生成（RAG）系统，涵盖「知识库构建 → 向量模型管理 → 模型调优 → 模型测评 → 排行榜对比 → 智能问答」全链路。

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

- Python 3.11+
- Node.js 18+
- MySQL 5.7.6+（全文检索需 ngram 解析器，InnoDB）
- 本地向量模型依赖：`sentence-transformers`、`torch`（推荐 CPU 版，`torch` 体积较大）

## 快速启动

### 1. 配置环境变量

```bash
# 复制 .env.example 为 .env 并填写数据库 / LLM / Embedding 配置
cp .env.example .env
```

关键配置项：

| 配置 | 说明 |
| --- | --- |
| `MYSQL_HOST/PORT/USER/PASSWORD/DB` | MySQL 连接信息 |
| `LLM_API_BASE/KEY/MODEL` | 大模型（DeepSeek 等 OpenAI 兼容服务） |
| `EMBEDDING_DIM` | 默认 `1024`（bge-large-zh-v1.5 真实维度） |
| `CHROMA_PERSIST_DIR` | 向量库持久化目录，默认 `./data/chroma` |

### 2. 安装后端依赖

```bash
pip install -r requirements.txt
# 或使用 uv（项目已提供 uv.lock）
uv sync
```

本地向量模型建议安装 CPU 版 torch：

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### 3. 启动后端（端口 4040）

```bash
python main.py
# 或
uvicorn main:app --host 0.0.0.0 --port 4040 --reload
```

启动时会自动执行数据库迁移（`alembic upgrade head`）。如需手动迁移：

```bash
alembic upgrade head
```

### 4. 启动前端（端口 4041）

```bash
cd frontend
npm install
npm run dev
```

前端已配置 `/api` 代理到 `http://localhost:4040`。

## 常用操作

- **配置重排序**：进入「系统设置 → 重排序」，开启 `rerank_enabled` 并填入 `rerank_model`（项目根目录相对路径，正斜杠且不含盘符，如 `rerankers/bge-reranker-base`），重启后端后日志打印「加载交叉编码器」即生效。
- **导入向量模型**：「我的模型 → 导入模型文件夹」，将模型目录保存到 `models/` 并登记 `model_dir`。

## 注意事项

- `chunk.content` 的中文全文索引（ngram）通过 Alembic 迁移自动创建，需 MySQL 5.7.6+；若迁移报错可手动执行 `ALTER TABLE chunk ADD FULLTEXT INDEX ft_chunk_content (content) WITH PARSER ngram;`。
- 本地向量模型首次加载会下载/加载权重，耗时较长，加载后走进程内缓存。