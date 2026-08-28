from fastapi.testclient import TestClient

import app.main as main_module
from app.kernel import KernelRegistry
from app.progress import ProgressStore


SOLUTIONS = {
    "tensor-info-cell": """def tensor_info(x):
    return {'shape': tuple(x.shape), 'ndim': x.ndim, 'dtype': str(x.dtype)}

input_info = tensor_info(token_ids)
input_info
""",
    "embedding-cell": """def embed_tokens(ids, embedding):
    return embedding(ids)

x = embed_tokens(token_ids, token_embedding)
tensor_info(x)
""",
    "split-heads-cell": """def split_heads(x, num_heads):
    batch, sequence, embed_dim = x.shape
    head_dim = embed_dim // num_heads
    return x.reshape(batch, sequence, num_heads, head_dim).transpose(1, 2)

heads = split_heads(x, NUM_HEADS)
tensor_info(heads)
""",
    "attention-scores-cell": """def attention_scores(q, k):
    return q @ k.transpose(-2, -1) / math.sqrt(q.size(-1))

q_layer = nn.Linear(EMBED_DIM, EMBED_DIM, bias=False)
k_layer = nn.Linear(EMBED_DIM, EMBED_DIM, bias=False)
q = split_heads(q_layer(x), NUM_HEADS)
k = split_heads(k_layer(x), NUM_HEADS)
scores = attention_scores(q, k)
tensor_info(scores)
""",
    "causal-softmax-cell": """def causal_softmax(scores):
    sequence = scores.size(-1)
    mask = torch.triu(
        torch.ones(sequence, sequence, dtype=torch.bool, device=scores.device),
        diagonal=1,
    )
    return torch.softmax(scores.masked_fill(mask, float('-inf')), dim=-1)

weights = causal_softmax(scores)
weights[0, 0]
""",
    "combine-heads-cell": """def combine_heads(attention_weights, values):
    context = attention_weights @ values
    batch, heads, sequence, head_dim = context.shape
    return context.transpose(1, 2).contiguous().reshape(batch, sequence, heads * head_dim)

v_layer = nn.Linear(EMBED_DIM, EMBED_DIM, bias=False)
v = split_heads(v_layer(x), NUM_HEADS)
attention_output = combine_heads(weights, v)
tensor_info(attention_output)
""",
    "decoder-trace-cell": """class TinyDecoder(nn.Module):
    def __init__(self, vocab_size, embed_dim, num_heads):
        super().__init__()
        self.num_heads = num_heads
        self.embedding = nn.Embedding(vocab_size, embed_dim)
        self.q = nn.Linear(embed_dim, embed_dim)
        self.k = nn.Linear(embed_dim, embed_dim)
        self.v = nn.Linear(embed_dim, embed_dim)
        self.out = nn.Linear(embed_dim, embed_dim)
        self.norm1 = nn.LayerNorm(embed_dim)
        self.ff = nn.Sequential(
            nn.Linear(embed_dim, 3 * embed_dim),
            nn.ReLU(),
            nn.Linear(3 * embed_dim, embed_dim),
        )
        self.norm2 = nn.LayerNorm(embed_dim)
        self.lm_head = nn.Linear(embed_dim, vocab_size)

    def forward(self, ids):
        x = embed_tokens(ids, self.embedding)
        q = split_heads(self.q(x), self.num_heads)
        k = split_heads(self.k(x), self.num_heads)
        v = split_heads(self.v(x), self.num_heads)
        scores = attention_scores(q, k)
        weights = causal_softmax(scores)
        attention = combine_heads(weights, v)
        x = self.norm1(x + self.out(attention))
        x = self.norm2(x + self.ff(x))
        logits = self.lm_head(x)
        trace = {
            'token_ids': tensor_info(ids),
            'embedding': tensor_info(self.embedding(ids)),
            'split_q': tensor_info(q),
            'scores': tensor_info(scores),
            'weights': tensor_info(weights),
            'attention': tensor_info(attention),
            'decoder': tensor_info(x),
        }
        return logits, trace

decoder = TinyDecoder(VOCAB_SIZE, EMBED_DIM, NUM_HEADS)
logits, shape_trace = decoder(token_ids)
""",
}


MAKEMORE_SOLUTIONS = {
    "vocabulary-cell": """def build_vocabulary(names):
    chars = sorted(set(''.join(names)))
    stoi = {char: index + 1 for index, char in enumerate(chars)}
    stoi['.'] = 0
    itos = {index: char for char, index in stoi.items()}
    return stoi, itos

stoi, itos = build_vocabulary(words)
VOCAB_SIZE = len(stoi)
VOCAB_SIZE, stoi
""",
    "training-pairs-cell": """def make_bigram_pairs(names, stoi):
    input_indices = []
    target_indices = []
    for name in names:
        tokens = ['.'] + list(name) + ['.']
        for current, following in zip(tokens, tokens[1:]):
            input_indices.append(stoi[current])
            target_indices.append(stoi[following])
    return torch.tensor(input_indices, dtype=torch.long), torch.tensor(target_indices, dtype=torch.long)

xs, ys = make_bigram_pairs(words, stoi)
xs.shape, ys.shape
""",
    "count-matrix-cell": """def count_bigrams(inputs, targets, vocab_size):
    counts = torch.zeros((vocab_size, vocab_size), dtype=torch.int64)
    for current, following in zip(inputs, targets):
        counts[current, following] += 1
    return counts

counts = count_bigrams(xs, ys, VOCAB_SIZE)
counts.shape, counts.sum().item()
""",
    "count-model-cell": """def normalize_counts(counts, smoothing=1.0):
    smoothed = counts.float() + smoothing
    return smoothed / smoothed.sum(dim=1, keepdim=True)

def negative_log_likelihood(probabilities, inputs, targets):
    return -torch.log(probabilities[inputs, targets]).mean()

count_probabilities = normalize_counts(counts, smoothing=1.0)
count_nll = negative_log_likelihood(count_probabilities, xs, ys)
count_nll
""",
    "neural-model-cell": """class NeuralBigram(nn.Module):
    def __init__(self, vocab_size):
        super().__init__()
        self.vocab_size = vocab_size
        self.weight = nn.Parameter(torch.randn(vocab_size, vocab_size))

    def forward(self, inputs):
        encoded = F.one_hot(inputs, num_classes=self.vocab_size).float()
        return encoded @ self.weight

neural_model = NeuralBigram(VOCAB_SIZE)
initial_logits = neural_model(xs)
initial_logits.shape
""",
    "training-loop-cell": """def train_bigram(model, inputs, targets, steps=100, learning_rate=10.0):
    optimizer = torch.optim.SGD(model.parameters(), lr=learning_rate)
    history = []
    for _ in range(steps):
        optimizer.zero_grad()
        logits = model(inputs)
        loss = F.cross_entropy(logits, targets)
        loss.backward()
        optimizer.step()
        history.append(float(loss.detach()))
    return history

loss_history = train_bigram(neural_model, xs, ys, steps=100, learning_rate=10.0)
loss_history[0], loss_history[-1]
""",
    "sampler-cell": """def sample_names(probabilities, itos, num_samples=5, seed=42, temperature=1.0, max_length=20):
    generator = torch.Generator().manual_seed(seed)
    names = []
    for _ in range(num_samples):
        current = 0
        chars = []
        for _ in range(max_length):
            row = probabilities[current]
            adjusted = torch.softmax(torch.log(row.clamp_min(1e-12)) / temperature, dim=0)
            following = int(torch.multinomial(adjusted, 1, generator=generator).item())
            if following == 0:
                break
            chars.append(itos[following])
            current = following
        names.append(''.join(chars))
    return names

count_samples = sample_names(count_probabilities, itos, num_samples=8, seed=42)
count_samples
""",
}


FOUNDATION_SOLUTIONS = {
    "tensor-summary-cell": """def tensor_summary(x):
    return {
        'shape': tuple(x.shape),
        'ndim': x.ndim,
        'dtype': str(x.dtype),
        'device': str(x.device),
    }

sample_info = tensor_summary(samples)
sample_info
""",
    "select-features-cell": """def select_features(x, columns):
    return x[:, columns]

chosen_features = select_features(samples, [0, 2])
chosen_features
""",
    "dot-product-cell": """def dot_product(left, right):
    return (left * right).sum()

first_hidden_value = dot_product(samples[0], input_weight[:, 0])
first_hidden_value
""",
    "manual-matmul-cell": """def manual_matmul(left, right):
    rows, inner = left.shape
    inner_right, columns = right.shape
    assert inner == inner_right
    output = torch.empty((rows, columns), dtype=left.dtype, device=left.device)
    for row in range(rows):
        for column in range(columns):
            output[row, column] = dot_product(left[row], right[:, column])
    return output

hidden_without_bias = manual_matmul(samples, input_weight)
hidden_without_bias
""",
    "linear-transform-cell": """def linear_transform(x, weight, bias):
    return x @ weight + bias

hidden = linear_transform(samples, input_weight, input_bias)
hidden
""",
    "batched-linear-cell": """def batched_linear(x, weight, bias):
    return linear_transform(x, weight, bias)

sequences = samples.reshape(2, 2, 3)
sequence_hidden = batched_linear(sequences, input_weight, input_bias)
tensor_summary(sequence_hidden)
""",
    "tiny-mlp-cell": """class TinyMLP(nn.Module):
    def __init__(self, first_weight, first_bias, second_weight, second_bias):
        super().__init__()
        self.first_weight = nn.Parameter(first_weight.clone())
        self.first_bias = nn.Parameter(first_bias.clone())
        self.second_weight = nn.Parameter(second_weight.clone())
        self.second_bias = nn.Parameter(second_bias.clone())

    def forward(self, x):
        hidden = linear_transform(x, self.first_weight, self.first_bias)
        hidden = torch.relu(hidden)
        return linear_transform(hidden, self.second_weight, self.second_bias)

classifier = TinyMLP(input_weight, input_bias, output_weight, output_bias)
logits = classifier(samples)
""",
}


def test_complete_makemore_chapter_and_invalidate_downstream(tmp_path) -> None:
    main_module.progress_store = ProgressStore(tmp_path)
    main_module.kernels = KernelRegistry()

    with TestClient(main_module.app) as client:
        listing = client.get("/api/chapters")
        assert listing.status_code == 200
        summaries = listing.json()["chapters"]
        assert [summary["id"] for summary in summaries] == [
            "tensors-and-matmul",
            "makemore-bigram",
        ]
        makemore_summary = summaries[1]
        assert makemore_summary["exercise_count"] == 7
        assert makemore_summary["progress_percent"] == 0

        chapter = client.get("/api/chapters/makemore-bigram")
        assert chapter.status_code == 200
        assert len(chapter.json()["cells"]) == 34

        for cell_id, source in MAKEMORE_SOLUTIONS.items():
            response = client.post(
                f"/api/chapters/makemore-bigram/cells/{cell_id}/run",
                json={"source": source, "check": True},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["error"] is None
            assert body["test_result"]["passed"], body["test_result"]

        changed_counts = MAKEMORE_SOLUTIONS["count-matrix-cell"] + "\n# implementation changed\n"
        response = client.post(
            "/api/chapters/makemore-bigram/cells/count-matrix-cell/run",
            json={"source": changed_counts, "check": True},
        )
        statuses = {
            cell_id: value["status"] for cell_id, value in response.json()["progress"].items()
        }
        assert statuses["count-matrix-cell"] == "passed"
        assert statuses["count-model-cell"] == "dirty"
        assert statuses["neural-model-cell"] == "dirty"
        assert statuses["training-loop-cell"] == "dirty"
        assert statuses["sampler-cell"] == "dirty"


def test_complete_foundation_course(tmp_path) -> None:
    main_module.progress_store = ProgressStore(tmp_path)
    main_module.kernels = KernelRegistry()

    with TestClient(main_module.app) as client:
        chapter = client.get("/api/chapters/tensors-and-matmul")
        assert chapter.status_code == 200
        body = chapter.json()
        assert body["order"] == 1
        assert len(body["cells"]) == 25

        for cell_id, source in FOUNDATION_SOLUTIONS.items():
            response = client.post(
                f"/api/chapters/tensors-and-matmul/cells/{cell_id}/run",
                json={"source": source, "check": True},
            )
            assert response.status_code == 200
            result = response.json()
            assert result["error"] is None
            assert result["test_result"]["passed"], result["test_result"]

        listing = client.get("/api/chapters").json()["chapters"]
        foundation_summary = listing[0]
        assert foundation_summary["id"] == "tensors-and-matmul"
        assert foundation_summary["progress_percent"] == 100


def test_run_read_only_teaching_example_without_changing_progress(tmp_path) -> None:
    main_module.progress_store = ProgressStore(tmp_path)
    main_module.kernels = KernelRegistry()

    with TestClient(main_module.app) as client:
        response = client.post(
            "/api/chapters/tensors-and-matmul/cells/tensor-summary-demo/run",
            json={"source": "raise RuntimeError('learner source must be ignored')", "check": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["error"] is None
        output_text = "".join(
            output.get("text", "")
            for output in body["outputs"]
            if output.get("output_type") == "stream"
        )
        assert "torch.Size([4, 3])" in output_text
        assert all(value["status"] == "idle" for value in body["progress"].values())


def test_all_makemore_teaching_examples_run_without_progress(tmp_path) -> None:
    main_module.progress_store = ProgressStore(tmp_path)
    main_module.kernels = KernelRegistry()

    with TestClient(main_module.app) as client:
        chapter = client.get("/api/chapters/makemore-bigram").json()
        example_cells = [cell for cell in chapter["cells"] if cell["type"] == "example"]

        assert len(example_cells) == 8
        for cell in example_cells:
            response = client.post(
                f"/api/chapters/makemore-bigram/cells/{cell['id']}/run",
                json={"source": "raise RuntimeError('ignored')", "check": True},
            )
            assert response.status_code == 200
            assert response.json()["error"] is None, cell["id"]

        progress = client.get("/api/chapters/makemore-bigram").json()["progress"]
        assert all(value["status"] == "idle" for value in progress.values())


def test_restore_cells_and_run_through(tmp_path) -> None:
    main_module.progress_store = ProgressStore(tmp_path)
    main_module.kernels = KernelRegistry()

    with TestClient(main_module.app) as client:
        for cell_id in ("tensor-summary-cell", "select-features-cell"):
            response = client.post(
                f"/api/chapters/tensors-and-matmul/cells/{cell_id}/run",
                json={"source": FOUNDATION_SOLUTIONS[cell_id], "check": True},
            )
            assert response.status_code == 200
            assert response.json()["test_result"]["passed"]

        restored = client.post(
            "/api/chapters/tensors-and-matmul/cells/tensor-summary-cell/reset"
        )
        assert restored.status_code == 200
        restored_body = restored.json()
        assert "# TODO: 从 x 的属性中整理四项信息" in restored_body["source"]
        assert restored_body["progress"]["tensor-summary-cell"]["status"] == "idle"
        assert restored_body["progress"]["select-features-cell"]["status"] == "dirty"
        assert restored_body["progress"]["select-features-cell"]["test_result"] is None

        run_through = client.post(
            "/api/chapters/tensors-and-matmul/cells/select-features-cell/run-through",
            json={
                "sources": {
                    "tensor-summary-cell": FOUNDATION_SOLUTIONS["tensor-summary-cell"],
                    "select-features-cell": FOUNDATION_SOLUTIONS["select-features-cell"],
                }
            },
        )
        assert run_through.status_code == 200
        run_body = run_through.json()
        assert [item["cell_id"] for item in run_body["executions"]] == [
            "tensor-summary-cell",
            "select-features-cell",
        ]
        assert run_body["stopped_at"] is None
        assert all(item["error"] is None for item in run_body["executions"])

        stopped = client.post(
            "/api/chapters/tensors-and-matmul/cells/select-features-cell/run-through",
            json={
                "sources": {
                    "tensor-summary-cell": "raise ValueError('stop here')",
                    "select-features-cell": FOUNDATION_SOLUTIONS["select-features-cell"],
                }
            },
        ).json()
        assert stopped["stopped_at"] == "tensor-summary-cell"
        assert len(stopped["executions"]) == 1
        assert stopped["executions"][0]["error"]["ename"] == "ValueError"

        reset_all = client.post("/api/chapters/tensors-and-matmul/reset")
        assert reset_all.status_code == 200
        reset_body = reset_all.json()
        assert "tensor-summary-cell" in reset_body["sources"]
        assert all(value["status"] == "idle" for value in reset_body["progress"].values())
