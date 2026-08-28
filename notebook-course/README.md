# Pushthrough Notebook Course

一个本地单用户的交互式 PyTorch 学习原型。每章课程是一个标准 Jupyter Notebook；章节内所有 Code Cell 共享同一个 Kernel，练习通过显式依赖组成完整项目。

## 已实现

- SvelteKit 单页课程界面与 Monaco Editor
- 自动扫描 `courses/` 目录的课程列表首页
- `/chapters/<chapter-id>` 动态课程路由
- Markdown、代码、文本、异常、HTML 和图片输出
- FastAPI 直接管理本地 Jupyter Kernel
- 后端 Pyright Language Server：实时诊断、补全和悬浮类型提示
- 整章 Code Cell 映射为同一份 `# %%` 虚拟 Python 文档，支持跨 Cell 类型分析
- “运行”和“运行并检查”两种模式
- 只读但可运行的教学示例 Cell；输出真实进入同一章 Kernel，但不修改学习进度
- 从干净 Kernel 顺序执行第一个 Code Cell 到当前 Cell
- 单个或整章还原 Code Cell，并同步清理保存状态
- 每个练习的结构化测试反馈
- 基于 `depends_on` 的下游失效传播
- 本地保存用户代码和完成状态
- Kernel 重启后重放已经通过的 Cell
- 第 01 课：从 Tensor、点积和矩阵乘法逐步组装 TinyMLP
- 第 02 课：用计数模型和神经网络两种方式实现字符 Bigram 语言模型

## 启动

首次安装依赖：

```bash
cd backend && uv sync
cd ../frontend && npm install
```

从项目目录同时启动前后端：

```bash
./dev.sh
```

然后访问 <http://127.0.0.1:5173/>。

首页显示课程列表和本地完成进度，点击课程卡片进入对应章节。

## 验证

```bash
cd backend && uv run pytest -q
cd ../frontend && npm run check && npm run build
```

后端测试会启动真实的 Jupyter Kernel，依次提交两章课程各七个任务的正确实现，并验证修改上游 Cell 后所有下游任务都会变为 `dirty`。
测试也会启动真实的 `pyright-langserver`，验证 LSP 消息封装、补全和悬浮信息。

## 代码智能提示

进入章节页时，前端会连接 `/api/chapters/<chapter-id>/lsp` WebSocket。后端为该连接启动
`pyright-langserver --stdio`，并在 WebSocket JSON 与 LSP `Content-Length` 消息之间转发。

Pyright 标准 Language Server 尚未提供 Notebook Document Sync，因此前端会按 Notebook 顺序把本章所有
Code Cell 组合为一份带 `# %% [cell-id]` 边界的虚拟 Python 文档。诊断范围、补全位置和悬浮范围会映射回
原始 Cell；隐藏的 Setup Cell 也包含在文档中，所以后续任务能够识别前面定义的 import、变量和函数。

## 课程文件

```text
courses/
├── tensors-and-matmul/
│   ├── chapter.ipynb
│   └── tests.py
└── makemore-bigram/
    ├── chapter.ipynb
    └── tests.py
```

Notebook 使用 `metadata.pushthrough` 描述课程：

```json
{
  "type": "exercise",
  "title": "任务 4 · 归一化概率并计算 NLL",
  "exercise_id": "count-model",
  "depends_on": ["count-matrix"],
  "test": "count-model"
}
```

支持的 Cell 类型包括 `lesson`、`setup`、`example`、`exercise`、`checkpoint` 和 `finale`。测试函数由相邻的 `tests.py` 暴露，并统一通过 `run_test(test_id, namespace)` 调用。

代码 Cell 的 `editable` 和 `runnable` 是两项独立能力。教学示例通常设置为
`{"type": "example", "editable": false, "runnable": true}`：学习者不能修改源码，但可以执行并查看真实输出。

学习进度保存在 `.progress/<chapter-id>.json`，该目录默认不提交到 Git。
