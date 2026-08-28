from __future__ import annotations

from collections.abc import Callable
from typing import Any

import torch
import torch.nn.functional as F
from torch import nn


def _result(checks: list[dict[str, Any]]) -> dict[str, Any]:
    passed = all(check["passed"] for check in checks)
    return {
        "passed": passed,
        "checks": checks,
        "message": "全部检查通过，可以继续下一节。" if passed else "还有检查未通过，请根据提示修改代码。",
    }


def _check(label: str, assertion: Callable[[], bool], hint: str) -> dict[str, Any]:
    try:
        passed = bool(assertion())
        return {"label": label, "passed": passed, "hint": None if passed else hint}
    except Exception as exc:
        return {
            "label": label,
            "passed": False,
            "hint": f"{hint}（{type(exc).__name__}: {exc}）",
        }


def test_vocabulary(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("build_vocabulary")
    try:
        stoi, itos = fn(["anna", "bob"])
    except Exception:
        stoi, itos = None, None
    checks = [
        _check("定义了 build_vocabulary", lambda: callable(fn), "请定义 build_vocabulary(names)。"),
        _check("句界符固定为 0", lambda: stoi["."] == 0 and itos[0] == ".", "保留索引 0 给开始/结束符 '.'。"),
        _check("字符按字母顺序编号", lambda: stoi == {".": 0, "a": 1, "b": 2, "n": 3, "o": 4}, "先收集去重字符，再用 sorted 排序。"),
        _check("两个映射完全互逆", lambda: all(itos[index] == char for char, index in stoi.items()), "itos 应由 stoi 反转得到。"),
        _check("没有遗漏或额外 token", lambda: len(stoi) == len(itos) == 5, "这个样例只应包含 '.', a, b, n, o。"),
    ]
    return _result(checks)


def test_training_pairs(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("make_bigram_pairs")
    sample_stoi = {".": 0, "a": 1, "b": 2}
    try:
        inputs, targets = fn(["ab", "a"], sample_stoi)
    except Exception:
        inputs, targets = None, None
    checks = [
        _check("返回两个一维 Tensor", lambda: inputs.shape == targets.shape == (5,), "'ab' 产生 3 对，'a' 产生 2 对。"),
        _check("包含开始和结束转移", lambda: torch.equal(inputs, torch.tensor([0, 1, 2, 0, 1])) and torch.equal(targets, torch.tensor([1, 2, 0, 1, 0])), "每个名字都要补成 .name. 后再取相邻字符。"),
        _check("索引类型可用于查表", lambda: inputs.dtype == targets.dtype == torch.long, "用 dtype=torch.long 创建 Tensor。"),
        _check("不跨名字制造 bigram", lambda: len(inputs) == sum(len(name) + 1 for name in ["ab", "a"]), "分别处理每个名字，不要把整份数据拼成一个长字符串。"),
    ]
    return _result(checks)


def test_count_matrix(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("count_bigrams")
    sample_inputs = torch.tensor([0, 1, 2, 0, 1])
    sample_targets = torch.tensor([1, 2, 0, 1, 0])
    try:
        counts = fn(sample_inputs, sample_targets, 3)
    except Exception:
        counts = None
    expected = torch.tensor([[0, 2, 0], [1, 0, 1], [1, 0, 0]])
    checks = [
        _check("计数表形状为 [V, V]", lambda: counts.shape == (3, 3), "行表示当前字符，列表示下一个字符。"),
        _check("每个 bigram 累加到正确格子", lambda: torch.equal(counts, expected), "对每一对 (x, y) 执行 counts[x, y] += 1。"),
        _check("总计数等于训练对数量", lambda: counts.sum().item() == len(sample_inputs), "每个训练对必须且只能计数一次。"),
        _check("计数使用整数", lambda: counts.dtype == torch.int64, "用 dtype=torch.int64 创建全零矩阵。"),
    ]
    return _result(checks)


def test_count_model(ns: dict[str, Any]) -> dict[str, Any]:
    normalize = ns.get("normalize_counts")
    nll_fn = ns.get("negative_log_likelihood")
    sample_counts = torch.tensor([[0, 2], [1, 0]], dtype=torch.int64)
    try:
        probabilities = normalize(sample_counts, smoothing=1.0)
        inputs = torch.tensor([0, 0, 1])
        targets = torch.tensor([1, 1, 0])
        loss = nll_fn(probabilities, inputs, targets)
    except Exception:
        probabilities, loss = None, None
    expected_probabilities = torch.tensor([[0.25, 0.75], [2 / 3, 1 / 3]])
    expected_loss = -torch.log(torch.tensor([0.75, 0.75, 2 / 3])).mean()
    checks = [
        _check("平滑后所有概率都大于 0", lambda: bool((probabilities > 0).all()), "归一化前先给每个格子加 smoothing。"),
        _check("每一行概率和为 1", lambda: torch.allclose(probabilities.sum(dim=1), torch.ones(2)), "沿列方向 dim=1 归一化每一行。"),
        _check("概率值正确", lambda: torch.allclose(probabilities, expected_probabilities), "先转浮点，再做 (counts+s)/(row_sum)。"),
        _check("NLL 是标量 Tensor", lambda: loss.shape == torch.Size([]), "取出每个真实目标的概率，取 log、加负号并求 mean。"),
        _check("NLL 只读取真实目标位置", lambda: torch.allclose(loss, expected_loss), "使用 probabilities[inputs, targets] 做成对索引。"),
    ]
    return _result(checks)


def test_neural_model(ns: dict[str, Any]) -> dict[str, Any]:
    cls = ns.get("NeuralBigram")
    try:
        model = cls(4)
        inputs = torch.tensor([0, 2, 1])
        logits = model(inputs)
        expected = F.one_hot(inputs, num_classes=4).float() @ model.weight
        parameters = dict(model.named_parameters())
    except Exception:
        model, logits, expected, parameters = None, None, None, {}
    checks = [
        _check("NeuralBigram 是 nn.Module", lambda: isinstance(model, nn.Module), "继承 nn.Module，并在 __init__ 中调用 super().__init__()。"),
        _check("登记了唯一的 weight 参数", lambda: set(parameters) == {"weight"} and isinstance(parameters["weight"], nn.Parameter), "将 [V, V] 权重包装为 nn.Parameter。"),
        _check("每个输入得到 V 个 logits", lambda: logits.shape == (3, 4), "输入 [N] 应输出 [N, V]。"),
        _check("one-hot 乘权重得到 logits", lambda: torch.allclose(logits, expected), "使用 F.one_hot(...).float() @ self.weight。"),
        _check("输出保留梯度路径", lambda: logits.requires_grad, "不要 detach logits。"),
    ]
    return _result(checks)


def test_training_loop(ns: dict[str, Any]) -> dict[str, Any]:
    cls = ns.get("NeuralBigram")
    train = ns.get("train_bigram")
    torch.manual_seed(123)
    model = cls(3)
    inputs = torch.tensor([0, 0, 1, 1, 2, 2])
    targets = torch.tensor([1, 1, 2, 2, 0, 0])
    before = model.weight.detach().clone()
    try:
        history = train(model, inputs, targets, steps=60, learning_rate=1.0)
    except Exception:
        history = None
    checks = [
        _check("每一步都记录一个 loss", lambda: len(history) == 60 and all(isinstance(value, float) for value in history), "每轮把 float(loss.detach()) 追加到列表。"),
        _check("训练显著降低交叉熵", lambda: history[-1] < history[0] * 0.35, "每轮依次 zero_grad、forward、cross_entropy、backward、step。"),
        _check("优化器确实更新了参数", lambda: not torch.equal(before, model.weight.detach()), "把 model.parameters() 交给 torch.optim.SGD。"),
        _check("训练后预测符合循环转移", lambda: torch.equal(model(inputs).argmax(dim=1), targets), "应学会 0→1、1→2、2→0。"),
    ]
    return _result(checks)


def test_sampler(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("sample_names")
    probabilities = torch.tensor([
        [0.0, 1.0, 0.0],
        [0.5, 0.0, 0.5],
        [1.0, 0.0, 0.0],
    ])
    itos = {0: ".", 1: "a", 2: "b"}
    try:
        first = fn(probabilities, itos, num_samples=4, seed=7, temperature=1.0, max_length=8)
        second = fn(probabilities, itos, num_samples=4, seed=7, temperature=1.0, max_length=8)
    except Exception:
        first, second = None, None
    checks = [
        _check("返回指定数量的字符串", lambda: len(first) == 4 and all(isinstance(name, str) for name in first), "每次生成一个字符串并追加到结果列表。"),
        _check("相同 seed 可复现", lambda: first == second, "创建 torch.Generator() 并调用 manual_seed(seed)。"),
        _check("不会把句界符写进名字", lambda: all("." not in name for name in first), "抽到索引 0 时停止，不要把 '.' 追加到字符列表。"),
        _check("生成结果遵守 bigram 规则", lambda: all(name in {"a", "ab"} for name in first), "每次用当前字符对应的那一行分布采样下一个字符。"),
    ]
    return _result(checks)


TESTS = {
    "vocabulary": test_vocabulary,
    "training-pairs": test_training_pairs,
    "count-matrix": test_count_matrix,
    "count-model": test_count_model,
    "neural-model": test_neural_model,
    "training-loop": test_training_loop,
    "sampler": test_sampler,
}


def run_test(test_id: str, namespace: dict[str, Any]) -> dict[str, Any]:
    try:
        return TESTS[test_id](namespace)
    except Exception as exc:
        return {"passed": False, "checks": [], "message": f"测试无法完成：{type(exc).__name__}: {exc}"}
