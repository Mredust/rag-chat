"""法律三元组微调测试 - 独立脚本，不依赖本项目业务模块。

数据格式与系统一致：每行 JSON，字段 query / positive / negative。
训练方式与系统对齐：sentence-transformers + MultipleNegativesRankingLoss。

用法:
    uv run python test/train_law_triplet.py
"""

import json
import time
from pathlib import Path

import torch
from sentence_transformers import InputExample, SentenceTransformer
from sentence_transformers.sentence_transformer.losses import MultipleNegativesRankingLoss
from torch.utils.data import DataLoader
from transformers import get_linear_schedule_with_warmup

DATA_FILE = Path(__file__).parent / "law_triplet_50.jsonl"
BASE_MODEL_DIR = Path(__file__).parent.parent / "models" / "system" / "bge-large-zh-v1.5"
OUTPUT_DIR = Path(__file__).parent / "output" / "law-ft-test"

EPOCHS = 3
BATCH_SIZE = 8
LR = 2e-5
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01
VALID_RATIO = 0.1
MAX_LEN = 128
SEED = 42


def load_records(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if (rec.get("query") or "").strip() and (rec.get("positive") or "").strip():
                records.append(rec)
    return records


def to_example(rec: dict) -> InputExample:
    texts = [rec["query"], rec["positive"]]
    neg = (rec.get("negative") or "").strip()
    if neg:
        texts.append(neg)
    return InputExample(texts=texts)


def eval_loss(model, loss_fn, examples, batch_size) -> float | None:
    if not examples:
        return None
    model.eval()
    dl = DataLoader(examples, shuffle=False, batch_size=batch_size, collate_fn=model.smart_batching_collate)
    total, n = 0.0, 0
    with torch.no_grad():
        for sentence_features, labels in dl:
            total += float(loss_fn(sentence_features, labels).item())
            n += 1
    model.train()
    return total / n if n else None


def top1_acc(model, pairs) -> float:
    if len(pairs) < 2:
        return 0.0
    from sentence_transformers.util import cos_sim

    q = model.encode([p["query"] for p in pairs], normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=False)
    p = model.encode([p["positive"] for p in pairs], normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=False)
    sim = cos_sim(q, p)
    correct = sum(1 for i in range(len(pairs)) if int(sim[i].argmax()) == i)
    return correct / len(pairs) * 100.0


def run() -> None:
    torch.manual_seed(SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"

    records = load_records(DATA_FILE)
    val_count = max(1, int(len(records) * VALID_RATIO))
    val_records = records[:val_count]
    train_records = records[val_count:]

    print("=" * 60)
    print("法律三元组微调测试")
    print("=" * 60)
    print(f"数据文件    : {DATA_FILE.name}")
    print(f"总条数      : {len(records)} (训练 {len(train_records)} / 验证 {len(val_records)})")
    print(f"基础模型    : {BASE_MODEL_DIR.name}")
    print(f"训练设备    : {device}")
    print(f"超参数      : epochs={EPOCHS} batch={BATCH_SIZE} lr={LR} max_len={MAX_LEN}")
    print("=" * 60)

    model = SentenceTransformer(str(BASE_MODEL_DIR), device=device)
    model.max_seq_length = MAX_LEN
    loss_fn = MultipleNegativesRankingLoss(model)

    train_examples = [to_example(r) for r in train_records]
    val_examples = [to_example(r) for r in val_records]
    train_dl = DataLoader(train_examples, shuffle=True, batch_size=BATCH_SIZE, collate_fn=model.smart_batching_collate)

    optimizer = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    steps_per_epoch = max(1, len(train_dl))
    total_steps = EPOCHS * steps_per_epoch
    warmup_steps = max(0, int(total_steps * WARMUP_RATIO))
    scheduler = get_linear_schedule_with_warmup(optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps)

    metrics = {"epochs": [], "train_loss": [], "val_loss": [], "val_acc": [], "time": []}
    train_start = time.perf_counter()

    for epoch in range(1, EPOCHS + 1):
        model.train()
        running, epoch_start = 0.0, time.perf_counter()
        for batch_idx, (sentence_features, labels) in enumerate(train_dl, 1):
            optimizer.zero_grad()
            loss = loss_fn(sentence_features, labels)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            scheduler.step()
            running += float(loss.item())
            print(
                f"[Epoch {epoch}/{EPOCHS}] step {batch_idx}/{steps_per_epoch} "
                f"loss={running / batch_idx:.4f}",
                flush=True,
            )

        avg_loss = running / steps_per_epoch
        v_loss = eval_loss(model, loss_fn, val_examples, BATCH_SIZE)
        v_acc = top1_acc(model, val_records)
        elapsed = time.perf_counter() - epoch_start

        metrics["epochs"].append(epoch)
        metrics["train_loss"].append(round(avg_loss, 4))
        metrics["val_loss"].append(round(v_loss, 4) if v_loss is not None else None)
        metrics["val_acc"].append(round(v_acc, 2))
        metrics["time"].append(round(elapsed, 2))

        print(
            f"Epoch {epoch}/{EPOCHS} | train_loss={avg_loss:.4f} "
            f"val_loss={v_loss if v_loss is not None else 'N/A'} "
            f"top1={v_acc:.2f}% | 耗时 {elapsed:.1f}s",
            flush=True,
        )

    total_time = time.perf_counter() - train_start
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    model.save(str(OUTPUT_DIR))
    metrics_path = OUTPUT_DIR / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=" * 60)
    print("训练完成")
    print("=" * 60)
    print(f"总耗时      : {total_time:.1f}s")
    print(f"每轮平均    : {total_time / EPOCHS:.1f}s")
    print(f"样本吞吐    : {len(train_examples) * EPOCHS / total_time:.1f} 样本/秒")
    print(f"最终指标    : train_loss={metrics['train_loss'][-1]} "
          f"val_loss={metrics['val_loss'][-1]} top1={metrics['val_acc'][-1]}%")
    print(f"模型输出    : {OUTPUT_DIR}")
    print(f"指标文件    : {metrics_path}")


if __name__ == "__main__":
    run()
