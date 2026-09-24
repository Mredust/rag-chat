"""本机训练速度测试 - 完全独立，不依赖本项目任何模块。

用法:
    uv run python test/train_speed_test.py
"""

import platform
import random
import time

import torch
import torch.nn as nn

SEED = 42
EPOCHS = 5
BATCH_SIZE = 64
INPUT_DIM = 512
HIDDEN_DIM = 1024
NUM_CLASSES = 10
NUM_BATCHES = 200


class BenchmarkModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(INPUT_DIM, HIDDEN_DIM),
            nn.ReLU(),
            nn.Linear(HIDDEN_DIM, HIDDEN_DIM),
            nn.ReLU(),
            nn.Linear(HIDDEN_DIM, NUM_CLASSES),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def print_env() -> None:
    print("=" * 50)
    print("环境信息")
    print("=" * 50)
    print(f"操作系统    : {platform.system()} {platform.release()}")
    print(f"处理器      : {platform.processor()}")
    print(f"PyTorch     : {torch.__version__}")
    if torch.cuda.is_available():
        print(f"CUDA        : {torch.cuda.get_device_name(0)}")
        device_name = torch.cuda.get_device_name(0)
    else:
        print("CUDA        : 不可用 (CPU 模式)")
        device_name = "CPU"
    print(f"训练设备    : {device_name}")
    print()


def run() -> None:
    random.seed(SEED)
    torch.manual_seed(SEED)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = BenchmarkModel().to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)

    # 预生成固定数据，排除数据生成耗时干扰
    x = torch.randn(NUM_BATCHES * BATCH_SIZE, INPUT_DIM, device=device)
    y = torch.randint(0, NUM_CLASSES, (NUM_BATCHES * BATCH_SIZE,), device=device)

    print_env()
    print("=" * 50)
    print(f"训练测速: {EPOCHS} 轮 x {NUM_BATCHES} 批 x batch_size={BATCH_SIZE}")
    print("=" * 50)

    epoch_times = []
    for epoch in range(1, EPOCHS + 1):
        model.train()
        if device.type == "cuda":
            torch.cuda.synchronize()
        start = time.perf_counter()

        total_loss = 0.0
        for i in range(NUM_BATCHES):
            bx = x[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
            by = y[i * BATCH_SIZE : (i + 1) * BATCH_SIZE]
            optimizer.zero_grad()
            output = model(bx)
            loss = criterion(output, by)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        if device.type == "cuda":
            torch.cuda.synchronize()
        elapsed = time.perf_counter() - start
        epoch_times.append(elapsed)
        print(
            f"Epoch {epoch}/{EPOCHS} | 耗时 {elapsed:6.2f}s | "
            f"平均 loss {total_loss / NUM_BATCHES:.4f}"
        )

    # 排除第 1 轮预热
    stable = epoch_times[1:] if len(epoch_times) > 1 else epoch_times
    avg = sum(stable) / len(stable)
    samples_per_sec = (NUM_BATCHES * BATCH_SIZE) / avg

    print()
    print("=" * 50)
    print("结果汇总")
    print("=" * 50)
    print(f"平均单轮耗时 (去预热): {avg:.2f}s")
    print(f"训练吞吐              : {samples_per_sec:.0f} 样本/秒")
    print(f"参数量                : {sum(p.numel() for p in model.parameters()):,}")


if __name__ == "__main__":
    run()
