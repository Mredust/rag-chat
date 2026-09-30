"""法律检索模型微调脚本（独立运行版，不依赖数据库 / FastAPI / 前端）。

运行前仅需备齐：
  1. 基础模型：bge-large-zh-v1.5（目录内含 pytorch_model.bin / model.safetensors）
  2. 训练集：JSONL，每行 {"query", "positive", "negative"}
  3. 测试集（可选）：JSONL，格式同上，用于训练后检索评测

训练方式与系统「模型调优」一致：
  sentence-transformers + MultipleNegativesRankingLoss（对比学习全参数微调）。

训练完成后在 output 目录产出：
  1. 微调模型（权重 / config.json / tokenizer）
  2. train_manifest.json            —— 训练元数据
  3. README.md                      —— 模型说明
  4. import_ml_train_task.sql       —— 对齐 ml_train_task 表结构的 INSERT 语句，
      包含 config / log / metrics，可直接 mysql 导入，供前端「模型调优」可视化展示。

配置方式:
    所有配置项在 `fine-tuning/.env` 中维护，直接运行即可（无需命令行参数）:

        uv run python fine-tuning/fine_tune.py

    修改 .env 中的路径 / 超参 / 模型名后保存，下次运行即按新配置执行。
"""

from __future__ import annotations

import gc
import json
import random
import time
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


def _load_records(path: Path, limit: int | None = None) -> list[dict]:
    """读取 JSONL，保留 query / positive 均非空的行。"""
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if (rec.get("query") or "").strip() and (rec.get("positive") or "").strip():
                records.append(rec)
            if limit is not None and len(records) >= limit:
                break
    return records


def _texts(rec: dict, instruction: str = "") -> list[str]:
    """[query, positive] 基础上追加难负样本；instruction 非空时加在 query 前（bge 检索指令）。"""
    neg = (rec.get("negative") or "").strip()
    query = (instruction + rec["query"]) if instruction else rec["query"]
    return [query, rec["positive"]] + ([neg] if neg else [])


def _move_batch_to_model(sentence_features, labels, device):
    """把 collate 产出的批次搬到模型所在设备（smart_batching_collate 恒在 CPU）。"""
    import torch

    features = [
        {k: (v.to(device) if torch.is_tensor(v) else v) for k, v in f.items()}
        for f in sentence_features
    ]
    if torch.is_tensor(labels):
        labels = labels.to(device)
    return features, labels


def _eval_loss(model, loss_fn, val_examples, batch_size: int) -> float | None:
    """真实验证损失：eval 模式对验证集计算 MultipleNegativesRankingLoss 均值（逐 batch，不 OOM）。"""
    if not val_examples:
        return None
    from torch.utils.data import DataLoader

    model.eval()
    dataloader = DataLoader(
        val_examples, shuffle=False, batch_size=batch_size, collate_fn=model.smart_batching_collate
    )
    total, n = 0.0, 0
    with torch.no_grad():
        for sentence_features, labels in dataloader:
            sentence_features, labels = _move_batch_to_model(sentence_features, labels, model.device)
            total += float(loss_fn(sentence_features, labels).item())
            n += 1
    model.train()
    return total / n if n else None


def _retrieval_top1_acc(model, pairs: list[dict], seed: int = 42, max_samples: int | None = None, instruction: str = "") -> tuple[float, int]:
    """真实检索 top-1 准确率。pairs 过多时随机采样 max_samples 条，避免全量 cos_sim OOM。"""
    if max_samples is not None and max_samples > 0 and len(pairs) > max_samples:
        pairs = random.Random(seed).sample(pairs, max_samples)
    if len(pairs) < 2:
        return 0.0, len(pairs)
    from sentence_transformers.util import cos_sim

    queries = [(instruction + p["query"]) if instruction else p["query"] for p in pairs]
    passages = [p["positive"] for p in pairs]
    q_emb = model.encode(queries, normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=True)
    p_emb = model.encode(passages, normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=True)
    sim = cos_sim(q_emb, p_emb)
    correct = sum(1 for i in range(len(pairs)) if int(sim[i].argmax()) == i)
    return correct / len(pairs) * 100.0, len(pairs)


def _fmt_lr(value: float) -> str:
    """学习率格式化为普通十进制（如 0.00002），去除多余尾零。"""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _do_train(args, base_dir: str, train_records: list[dict], val_records: list[dict], lines: list[str]) -> dict:
    """执行真实 Embedding 对比学习微调，返回指标 dict（metrics 字段）与附加信息。"""
    from sentence_transformers import InputExample, SentenceTransformer
    from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss
    from torch.utils.data import DataLoader
    from transformers import get_linear_schedule_with_warmup

    import torch

    if not base_dir:
        raise RuntimeError("基础模型目录不存在，无法执行真实微调")

    train_pairs = [r for r in train_records if (r.get("query") or "").strip() and (r.get("positive") or "").strip()]
    if not train_pairs:
        raise RuntimeError("训练数据集中暂无有效三元组（query/positive 为空）")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(base_dir, device=device)
    model.max_seq_length = args.passage_max_len
    scale = round(1.0 / args.temperature, 6) if args.temperature and args.temperature > 0 else 20.0
    loss_fn = MultipleNegativesRankingLoss(model, scale=scale)
    instruction = args.instruction if args.add_instruction else ""
    print(f"[INFO] 基础模型加载完成 device={device} scale={scale} instruction={bool(instruction)}", flush=True)

    train_examples = [InputExample(texts=_texts(r, instruction)) for r in train_pairs]
    train_dataloader = DataLoader(
        train_examples, shuffle=True, batch_size=args.batch_size, collate_fn=model.smart_batching_collate
    )
    val_pairs = [r for r in val_records if (r.get("query") or "").strip() and (r.get("positive") or "").strip()]
    val_examples = [InputExample(texts=_texts(r, instruction)) for r in val_pairs]

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    steps_per_epoch = max(1, len(train_dataloader))
    total_steps = args.num_epochs * steps_per_epoch
    warmup_steps = max(0, int(total_steps * args.warmup_ratio))
    scheduler = get_linear_schedule_with_warmup(
        optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps
    )

    epochs: list[int] = []
    train_losses: list[float] = []
    val_losses: list[float] = []
    val_accs: list[float] = []
    lrs: list[float] = []

    model.train()
    report_interval = max(1, steps_per_epoch // 10)
    for epoch in range(1, args.num_epochs + 1):
        running = 0.0
        epoch_start = time.time()
        for batch_idx, (sentence_features, labels) in enumerate(train_dataloader, start=1):
            optimizer.zero_grad(set_to_none=True)
            sentence_features, labels = _move_batch_to_model(sentence_features, labels, model.device)
            loss = loss_fn(sentence_features, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            running += float(loss.item())
            if batch_idx == 1 or batch_idx % report_interval == 0 or batch_idx == steps_per_epoch:
                global_step = (epoch - 1) * steps_per_epoch + batch_idx
                elapsed = time.time() - epoch_start
                msg = (
                    f"[STEP] Epoch {epoch}/{args.num_epochs} 批次 {batch_idx}/{steps_per_epoch} "
                    f"全局 {global_step}/{total_steps} 平均损失 {running / batch_idx:.4f} 用时 {elapsed:.1f}s"
                )
                lines.append(msg)
                print(msg, flush=True)

        avg_loss = running / steps_per_epoch
        val_loss = _eval_loss(model, loss_fn, val_examples, args.batch_size)
        val_acc, val_acc_count = _retrieval_top1_acc(model, val_pairs, seed=args.seed, max_samples=args.val_eval_samples, instruction=instruction)

        epochs.append(epoch)
        train_losses.append(round(avg_loss, 4))
        lrs.append(round(float(scheduler.get_last_lr()[0]), 8))
        if val_loss is not None:
            val_losses.append(round(val_loss, 4))
        val_accs.append(round(val_acc, 2))

        msg = (
            f"[EPOCH {epoch}/{args.num_epochs}] 训练损失: {avg_loss:.4f} | "
            f"验证损失: {val_loss if val_loss is not None else 'N/A'} | "
            f"准确率: {val_acc:.2f}%（{val_acc_count} 条）"
        )
        lines.append(msg)
        print(msg, flush=True)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save(str(output_dir))
    print(f"[INFO] 模型已保存 output_dir={output_dir}", flush=True)

    del loss_fn, optimizer, scheduler, train_dataloader, model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return {
        "epochs": epochs,
        "train_loss": train_losses,
        "val_loss": val_losses,
        "val_acc": val_accs,
        "learning_rate": lrs,
        "total_steps": total_steps,
        "num_examples": len(train_examples),
        "steps_per_epoch": steps_per_epoch,
    }


def _sql_escape(s: str) -> str:
    """SQL 单引号字符串转义。"""
    return s.replace("\\", "\\\\").replace("'", "''")


def _write_import_sql(args, lines: list[str], result: dict, elapsed_total: float, token_usage: int) -> Path:
    """生成对齐 ml_train_task 表结构的 INSERT 语句，供 mysql 导入。"""
    final_loss = result["train_loss"][-1] if result["train_loss"] else 0.0
    final_acc = result["val_acc"][-1] if result["val_acc"] else 0.0
    best_acc = max(result["val_acc"]) if result["val_acc"] else 0.0
    best_epoch = (result["val_acc"].index(best_acc) + 1) if result["val_acc"] else 0

    # 总结信息追加进日志
    summary = [
        "=" * 70,
        f"[SUMMARY] 训练完成 | 训练样本: {result['num_examples']} | 总步数: {result['total_steps']} | "
        f"最佳准确率: {best_acc:.2f}% (Epoch {best_epoch}) | 总耗时: {elapsed_total:.1f}s",
        f"[SUMMARY] 模型保存路径: {args.db_output_dir}",
    ]
    if getattr(args, "test_acc", None) is not None:
        summary.append(f"[SUMMARY] 测试集检索准确率: {args.test_acc:.2f}%（{args.test_count} 条）")
    lines += summary

    config = {
        "batch_size": args.batch_size,
        "eval_steps": args.eval_steps,
        "num_epochs": args.num_epochs,
        "save_steps": args.save_steps,
        "train_mode": args.train_mode,
        "dataset_ids": [],
        "temperature": args.temperature,
        "warmup_ratio": args.warmup_ratio,
        "weight_decay": args.weight_decay,
        "learning_rate": str(args.lr),
        "query_max_len": args.query_max_len,
        "add_instruction": args.add_instruction,
        "passage_max_len": args.passage_max_len,
    }
    metrics = {
        "epochs": result["epochs"],
        "train_loss": result["train_loss"],
        "val_loss": result["val_loss"],
        "val_acc": result["val_acc"],
        "learning_rate": result["learning_rate"],
        "total_steps": result["total_steps"],
        "total_time_sec": round(elapsed_total, 1),
        "token_usage": token_usage,
        "final_loss": final_loss,
        "final_acc": final_acc,
    }

    task_id = str(uuid.uuid4())
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    sql_path = Path(args.output_dir) / "import_ml_train_task.sql"
    sql_path.write_text(
        "INSERT INTO `ml_train_task`\n"
        "  (`id`, `name`, `priority`, `train_method`, `base_model`, `dataset_id`, `valid_ratio`,\n"
        "   `config`, `output_model_name`, `status`, `output_dir`, `log`, `metrics`, `created_at`, `updated_at`)\n"
        "VALUES\n"
        f"  ('{task_id}', '{_sql_escape(args.task_name)}', 'L2', 'sft', '{_sql_escape(args.base_model_name)}', "
        f"NULL, {args.valid_ratio},\n"
        f"   '{_sql_escape(json.dumps(config, ensure_ascii=False))}', '{_sql_escape(args.output_name)}', 'done', "
        f"'{_sql_escape(args.db_output_dir)}', '{_sql_escape('\\n'.join(lines))}', "
        f"'{_sql_escape(json.dumps(metrics, ensure_ascii=False))}', '{created_at}', '{created_at}');\n",
        encoding="utf-8",
    )
    return sql_path


def _write_manifest(args, result: dict) -> Path:
    """写 train_manifest.json（对齐系统 _build_output_model_config）。"""
    manifest = {
        "output_model_name": args.output_name,
        "base_model": args.base_model_name,
        "reranker_model": args.reranker_model,
        "train_method": "sft",
        "valid_ratio": args.valid_ratio,
        "config": {
            "batch_size": args.batch_size,
            "num_epochs": args.num_epochs,
            "learning_rate": str(args.lr),
            "temperature": args.temperature,
            "warmup_ratio": args.warmup_ratio,
            "weight_decay": args.weight_decay,
            "query_max_len": args.query_max_len,
            "passage_max_len": args.passage_max_len,
            "add_instruction": args.add_instruction,
            "eval_steps": args.eval_steps,
            "save_steps": args.save_steps,
            "train_mode": args.train_mode,
        },
        "test_acc": getattr(args, "test_acc", None),
        "test_count": getattr(args, "test_count", None),
    }
    manifest_path = Path(args.output_dir) / "train_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _load_env(path: Path) -> dict[str, str]:
    """解析 .env（KEY=VALUE，支持 # 注释、空行与单/双引号包裹）。"""
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key.strip()] = value
    return env


def _get_str(env: dict[str, str], key: str, default: str = "") -> str:
    v = env.get(key)
    return v if v not in (None, "") else default


def _get_int(env: dict[str, str], key: str, default: int) -> int:
    v = env.get(key)
    try:
        return int(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _get_float(env: dict[str, str], key: str, default: float) -> float:
    v = env.get(key)
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _get_bool(env: dict[str, str], key: str, default: bool) -> bool:
    v = (env.get(key) or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


def _load_config() -> SimpleNamespace:
    """从 fine-tuning/.env 读取全部配置，返回含默认值的命名空间。"""
    env = _load_env(_ENV_PATH)
    return SimpleNamespace(
        base=_get_str(env, "VECTOR_MODEL", "models/system/bge-large-zh-v1.5"),
        reranker_model=_get_str(env, "RERANKER_MODEL", "rerankers/bge-reranker-base"),
        train=_get_str(env, "TRAIN_DATA", "data/datasets/法律数据集200000.jsonl"),
        test=_get_str(env, "TEST_DATA", "data/datasets/法律测试集20000.jsonl"),
        valid_ratio=_get_float(env, "VALID_RATIO", 0.1),
        num_epochs=_get_int(env, "NUM_EPOCHS", 2),
        batch_size=_get_int(env, "BATCH_SIZE", 16),
        lr=_get_float(env, "LR", 2e-5),
        warmup_ratio=_get_float(env, "WARMUP_RATIO", 0.1),
        weight_decay=_get_float(env, "WEIGHT_DECAY", 0.01),
        query_max_len=_get_int(env, "QUERY_MAX_LEN", 128),
        passage_max_len=_get_int(env, "PASSAGE_MAX_LEN", 512),
        temperature=_get_float(env, "TEMPERATURE", 0.05),
        add_instruction=_get_bool(env, "ADD_INSTRUCTION", True),
        instruction=_get_str(env, "INSTRUCTION", "为这个句子生成表示以用于检索相关文章："),
        eval_steps=_get_int(env, "EVAL_STEPS", 50),
        save_steps=_get_int(env, "SAVE_STEPS", 100),
        train_mode=_get_str(env, "TRAIN_MODE", "efficient"),
        output_name=_get_str(env, "OUTPUT_NAME", "legal-v1.0"),
        task_name=_get_str(env, "TASK_NAME", "法律知识微调训练"),
        eval_samples=_get_int(env, "EVAL_SAMPLES", 2000),
        val_eval_samples=_get_int(env, "VAL_EVAL_SAMPLES", 2000),
        seed=_get_int(env, "SEED", 42),
    )


def main() -> None:
    args = _load_config()

    base_path = Path(args.base)
    if not base_path.is_dir():
        raise RuntimeError(f"基础模型目录不存在: {args.base}")

    train_path = Path(args.train)
    train_records = _load_records(train_path)
    if not train_records:
        raise RuntimeError(f"训练集为空或不存在: {args.train}")

    # 默认将产出放到 fine-tuning/output/<模型名> 下
    if not hasattr(args, "output_dir") or not args.output_dir:
        args.output_dir = str(Path("fine-tuning") / "output" / args.output_name)
    args.db_output_dir = f"models/ftm/{args.output_name}"
    args.base_model_name = base_path.name  # 记录基础模型名（默认 bge-large-zh-v1.5）
    args.test_acc = None
    args.test_count = 0

    # 切分验证集（前 valid_ratio 条）
    valid_ratio = args.valid_ratio if 0.0 <= args.valid_ratio < 1.0 else 0.0
    val_count = int(len(train_records) * valid_ratio) if valid_ratio > 0 else 0
    val_records = train_records[:val_count] if val_count > 0 else []
    train_records_used = train_records[val_count:] if val_count > 0 else train_records

    device = "cuda" if _cuda_available() else "cpu"
    device_kind = "GPU（cuda）" if device == "cuda" else "CPU（cpu）"

    # 数据统计
    train_lens = [len(str(r.get("query") or "")) + len(str(r.get("positive") or "")) for r in train_records_used]
    mean_len = round(sum(train_lens) / len(train_lens), 1) if train_lens else 0
    min_len = min(train_lens) if train_lens else 0
    max_len = max(train_lens) if train_lens else 0

    sep = "=" * 70
    lines: list[str] = [
        "[DATA] 训练数据加载完成",
        f"[DATA] 训练集: {len(train_records_used)} 条",
        f"[DATA] 验证集: {len(val_records)} 条",
        f"[DATA] 总计: {len(train_records)} 条",
        f"[DATA] 样本平均长度: {mean_len} 字符",
        f"[DATA] 长度范围: {min_len} ~ {max_len} 字符",
        sep,
        "[CONFIG] 开始微调训练：sentence-transformers + MultipleNegativesRankingLoss",
        f"[CONFIG] 训练设备: {device_kind}",
        f"[CONFIG] 基础模型: {args.base_model_name}",
        f"[CONFIG] 训练轮数: {args.num_epochs}",
        f"[CONFIG] 批次大小: {args.batch_size}",
        f"[CONFIG] 学习率: {_fmt_lr(args.lr)}",
        f"[CONFIG] query_max_len: {args.query_max_len}",
        f"[CONFIG] passage_max_len: {args.passage_max_len}",
        f"[CONFIG] 预热比例: {args.warmup_ratio}",
        f"[CONFIG] 权重衰减: {args.weight_decay}",
        sep,
    ]
    # 实时打印数据/配置阶段
    print("\n".join(lines), flush=True)

    start = time.time()
    result = _do_train(args, str(base_path), train_records_used, val_records, lines)
    elapsed_total = time.time() - start
    token_usage = (sum(train_lens) * args.num_epochs) if train_lens else 0

    # 测试集最终评测（采样，避免 2w 全量 cos_sim OOM）
    if args.test:
        test_records = _load_records(Path(args.test))
        if test_records:
            max_samples = None if args.eval_samples == -1 else (args.eval_samples or None)
            instruction = args.instruction if args.add_instruction else ""
            test_acc, test_count = _retrieval_top1_acc(
                _load_model_for_eval(Path(args.output_dir)), test_records, seed=args.seed, max_samples=max_samples, instruction=instruction
            )
            args.test_acc = round(test_acc, 2)
            args.test_count = test_count
            print(f"[SUMMARY] 测试集检索准确率: {args.test_acc:.2f}%（{test_count} 条）", flush=True)

    manifest_path = _write_manifest(args, result)
    sql_path = _write_import_sql(args, lines, result, elapsed_total, token_usage)

    print()
    print("=" * 70)
    print("训练完成，产物如下：", flush=True)
    print(f"  模型目录      : {args.output_dir}")
    print(f"  元数据        : {manifest_path}")
    print(f"  SQL 导入文件  : {sql_path}")
    print("=" * 70)


def _cuda_available() -> bool:
    try:
        import torch

        return torch.cuda.is_available()
    except Exception:  # noqa: BLE001
        return False


def _load_model_for_eval(model_dir: Path):
    from sentence_transformers import SentenceTransformer

    device = "cuda" if _cuda_available() else "cpu"
    return SentenceTransformer(str(model_dir), device=device)


if __name__ == "__main__":
    main()