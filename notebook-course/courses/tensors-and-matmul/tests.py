from __future__ import annotations

from collections.abc import Callable
from typing import Any

import torch
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


def test_tensor_summary(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("tensor_summary")
    try:
        sample = torch.zeros(2, 3, dtype=torch.float32)
        info = fn(sample)
    except Exception:
        info = None
    checks = [
        _check("定义了 tensor_summary", lambda: callable(fn), "请定义 tensor_summary(x)。"),
        _check(
            "只返回四个固定键",
            lambda: set(info) == {"shape", "ndim", "dtype", "device"},
            "不要增加或省略键；必须恰好返回 shape、ndim、dtype、device。",
        ),
        _check("shape 是普通 tuple", lambda: info["shape"] == (2, 3), "使用 tuple(x.shape)。"),
        _check(
            "值使用约定的 Python 类型",
            lambda: isinstance(info["shape"], tuple)
            and all(isinstance(size, int) for size in info["shape"])
            and isinstance(info["ndim"], int)
            and isinstance(info["dtype"], str)
            and isinstance(info["device"], str),
            "shape/ndim/dtype/device 的类型依次应为 tuple、int、str、str。",
        ),
        _check("正确读取维数", lambda: info["ndim"] == 2, "使用 x.ndim。"),
        _check("dtype 转为字符串", lambda: info["dtype"] == "torch.float32", "使用 str(x.dtype)。"),
        _check("记录所在设备", lambda: info["device"] == "cpu", "使用 str(x.device)。"),
    ]
    return _result(checks)


def test_select_features(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("select_features")
    sample = torch.tensor([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    try:
        output = fn(sample, [0, 2])
        reordered = fn(sample, [2, 0, 2])
    except Exception:
        output, reordered = None, None
    checks = [
        _check("保留所有样本", lambda: output.shape == (2, 2), "第一维使用冒号，保留所有行。"),
        _check("选出指定特征列", lambda: torch.equal(output, torch.tensor([[1.0, 3.0], [4.0, 6.0]])), "使用 x[:, columns]。"),
        _check(
            "保留列号的顺序和重复项",
            lambda: torch.equal(reordered, torch.tensor([[3.0, 1.0, 3.0], [6.0, 4.0, 6.0]])),
            "columns=[2, 0, 2] 应按这个顺序返回三列，使用 x[:, columns] 即可。",
        ),
        _check("没有修改原 Tensor", lambda: torch.equal(sample, torch.tensor([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])), "返回选择结果，不要原地修改 x。"),
        _check("保持 dtype 和 device", lambda: reordered.dtype == sample.dtype and reordered.device == sample.device, "索引结果应沿用 x 的 dtype/device。"),
    ]
    return _result(checks)


def test_dot_product(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("dot_product")
    left = torch.tensor([1.0, 2.0, 3.0])
    right = torch.tensor([4.0, -1.0, 2.0])
    try:
        output = fn(left, right)
        precise_left = torch.tensor([1.0, 2.0], dtype=torch.float64)
        precise_output = fn(precise_left, torch.tensor([3.0, 4.0], dtype=torch.float64))
    except Exception:
        output, precise_left, precise_output = None, None, None
    checks = [
        _check("点积得到标量 Tensor", lambda: output.shape == torch.Size([]), "逐元素相乘后调用 sum()。"),
        _check("点积数值正确", lambda: torch.allclose(output, torch.tensor(8.0)), "计算 1×4 + 2×(-1) + 3×2。"),
        _check("适用于其他长度", lambda: torch.allclose(fn(torch.tensor([2.0, 3.0]), torch.tensor([5.0, 7.0])), torch.tensor(31.0)), "不要把长度写死。"),
        _check("保持 dtype 和 device", lambda: precise_output.dtype == precise_left.dtype and precise_output.device == precise_left.device, "逐元素相乘并 sum() 会自然沿用输入 dtype/device。"),
    ]
    return _result(checks)


def test_manual_matmul(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("manual_matmul")
    left = torch.tensor([[1.0, 2.0, 3.0], [0.0, -1.0, 2.0]])
    right = torch.tensor([[2.0, 1.0], [1.0, 0.0], [3.0, -2.0]])
    try:
        output = fn(left, right)
    except Exception:
        output = None
    original_dot = ns.get("dot_product")
    dot_calls = 0

    def tracked_dot(*args: Any, **kwargs: Any) -> Any:
        nonlocal dot_calls
        dot_calls += 1
        return original_dot(*args, **kwargs)

    try:
        ns["dot_product"] = tracked_dot
        tracked_output = fn(left, right)
    except Exception:
        tracked_output = None
    finally:
        ns["dot_product"] = original_dot
    expected = left @ right
    checks = [
        _check("输出形状为 [M, N]", lambda: output.shape == (2, 2), "[M, K] @ [K, N] 得到 [M, N]。"),
        _check("每个行列点积正确", lambda: torch.allclose(output, expected), "第 i,j 项是 left 第 i 行与 right 第 j 列的点积。"),
        _check("复用了 dot_product", lambda: dot_calls == 4 and torch.allclose(tracked_output, expected), "2×2 的输出应调用 4 次 dot_product；不要改用 @ 或 torch.matmul。"),
        _check("保持 dtype 和 device", lambda: output.dtype == left.dtype and output.device == left.device, "创建 output 时沿用 left.dtype 和 left.device。"),
    ]
    return _result(checks)


def test_linear_transform(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("linear_transform")
    x = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
    weight = torch.tensor([[2.0, -1.0, 0.5], [1.0, 3.0, -2.0]])
    bias = torch.tensor([0.5, -1.0, 2.0])
    x_before, weight_before, bias_before = x.clone(), weight.clone(), bias.clone()
    try:
        output = fn(x, weight, bias)
    except Exception:
        output = None
    expected = x @ weight + bias
    checks = [
        _check("线性变换输出形状正确", lambda: output.shape == (2, 3), "[batch, in] @ [in, out] 得到 [batch, out]。"),
        _check("矩阵乘法结果正确", lambda: torch.allclose(output, expected), "先计算 x @ weight。"),
        _check("bias 广播到每一行", lambda: torch.allclose(output - x @ weight, bias.expand_as(output)), "直接加一维 bias，PyTorch 会自动广播。"),
        _check("没有原地修改输入", lambda: torch.equal(x, x_before) and torch.equal(weight, weight_before) and torch.equal(bias, bias_before), "请返回新结果，不要修改 x、weight 或 bias。"),
        _check("保持 dtype 和 device", lambda: output.dtype == x.dtype and output.device == x.device, "@ 和 + 会自然沿用输入 dtype/device。"),
    ]
    return _result(checks)


def test_batched_linear(ns: dict[str, Any]) -> dict[str, Any]:
    fn = ns.get("batched_linear")
    x = torch.arange(24, dtype=torch.float32).reshape(2, 4, 3)
    weight = torch.arange(15, dtype=torch.float32).reshape(3, 5) / 10
    bias = torch.arange(5, dtype=torch.float32)
    try:
        output = fn(x, weight, bias)
    except Exception:
        output = None
    original_linear = ns.get("linear_transform")
    linear_calls = 0

    def tracked_linear(*args: Any, **kwargs: Any) -> Any:
        nonlocal linear_calls
        linear_calls += 1
        return original_linear(*args, **kwargs)

    try:
        ns["linear_transform"] = tracked_linear
        tracked_output = fn(x, weight, bias)
    except Exception:
        tracked_output = None
    finally:
        ns["linear_transform"] = original_linear
    expected = x @ weight + bias
    checks = [
        _check("保留 batch 和 sequence 维", lambda: output.shape == (2, 4, 5), "矩阵乘法只处理最后两个相关维度。"),
        _check("批量矩阵乘法数值正确", lambda: torch.allclose(output, expected), "同一个 weight 应用于每个 batch、每个位置。"),
        _check("二维输入仍可使用", lambda: torch.allclose(fn(x[0], weight, bias), expected[0]), "不要把 batch 或 sequence 大小写死。"),
        _check("复用了 linear_transform", lambda: linear_calls == 1 and torch.allclose(tracked_output, expected), "直接 return linear_transform(x, weight, bias)，无需按 ndim 分支。"),
        _check("保持 dtype 和 device", lambda: output.dtype == x.dtype and output.device == x.device, "结果应沿用 x 的 dtype/device。"),
    ]
    return _result(checks)


def test_tiny_mlp(ns: dict[str, Any]) -> dict[str, Any]:
    cls = ns.get("TinyMLP")
    try:
        model = cls(ns["input_weight"], ns["input_bias"], ns["output_weight"], ns["output_bias"])
        logits = model(ns["samples"])
        expected = torch.relu(ns["samples"] @ ns["input_weight"] + ns["input_bias"])
        expected = expected @ ns["output_weight"] + ns["output_bias"]
    except Exception:
        model, logits, expected = None, None, None
    try:
        named_parameters = dict(model.named_parameters())
    except Exception:
        named_parameters = {}
    expected_parameter_names = {"first_weight", "first_bias", "second_weight", "second_bias"}
    checks = [
        _check("TinyMLP 是 nn.Module", lambda: isinstance(model, nn.Module), "继承 nn.Module 并调用 super().__init__()。"),
        _check(
            "登记了四个同名 nn.Parameter",
            lambda: set(named_parameters) == expected_parameter_names
            and all(isinstance(parameter, nn.Parameter) for parameter in named_parameters.values()),
            "属性名必须是 first_weight、first_bias、second_weight、second_bias，并分别赋值为 nn.Parameter。",
        ),
        _check(
            "参数与构造输入不共享存储",
            lambda: named_parameters["first_weight"].data_ptr() != ns["input_weight"].data_ptr()
            and named_parameters["first_bias"].data_ptr() != ns["input_bias"].data_ptr()
            and named_parameters["second_weight"].data_ptr() != ns["output_weight"].data_ptr()
            and named_parameters["second_bias"].data_ptr() != ns["output_bias"].data_ptr(),
            "先对每个输入 Tensor 调用 clone()，再包装成 nn.Parameter。",
        ),
        _check("输出每个样本的类别分数", lambda: logits.shape == (4, 2), "最后一维应等于 2 个类别。"),
        _check("复用了两次线性变换", lambda: torch.allclose(logits, expected), "依次执行 linear → ReLU → linear。"),
        _check("可以得到每个样本的预测", lambda: logits.argmax(dim=-1).shape == (4,), "沿最后一维选出最大分数的位置。"),
    ]
    return _result(checks)


TESTS = {
    "tensor-summary": test_tensor_summary,
    "select-features": test_select_features,
    "dot-product": test_dot_product,
    "manual-matmul": test_manual_matmul,
    "linear-transform": test_linear_transform,
    "batched-linear": test_batched_linear,
    "tiny-mlp": test_tiny_mlp,
}


def run_test(test_id: str, namespace: dict[str, Any]) -> dict[str, Any]:
    try:
        return TESTS[test_id](namespace)
    except Exception as exc:
        return {"passed": False, "checks": [], "message": f"测试无法完成：{type(exc).__name__}: {exc}"}
