# 向量与相似度

> **从字面到语义的一步。** 理解了"文本如何变成数字、数字如何比较"，后面读融合、精排与改写才有地基。

本文是第二部分的正文，它讲清一件事：文本是怎样变成向量的，两个向量又是怎样比较的。

全文分为六节：前四节讲概念，第五节落回本仓库的代码，第六节给出练习与指标回指。

---

## 一、什么是向量表示

### 1.1 从字面匹配到语义匹配

传统的关键词检索把文本当作一串字符。它判断两段文本是否相关，靠的是字符是否重合：查询里出现"退货"，文档里也出现"退货"，系统就认为二者相关。

这种判断有一个天然的短板：只要换一个说法，系统就认不出来。用户问"买回来的东西不想要了"，政策文档写的是"七天无理由退货"，两句话没有一个字相同，关键词检索给出的结果是**零命中**。

向量表示要解决的正是这个问题。它不再让系统逐字比较，而是先把每段文本映射成一组固定长度的数字，再让系统比较这两组数字的远近。

在这个新的表示里，"不想要了"与"七天无理由退货"虽然字面不同，但它们的意思接近，因此它们对应的两组数字也会靠得很近。系统由此获得了判断语义的能力。

### 1.2 嵌入的含义

把文本映射成向量的过程，称为**嵌入（Embedding）**。承担这个映射任务的模型，称为**嵌入模型（Embedding Model）**，也叫**双塔模型**，因为它对查询和文档分别编码，只让它们在最后一层产生可比向量。

读者可以把嵌入模型想象成一张巨大的地图。地图上的每一个点都有一个坐标，坐标由若干数字组成。嵌入模型的作用，就是把每一段文本安置到这张地图上的某个位置，让意思相近的文本落在相邻的位置。

这张地图的坐标个数，就是向量的**维度（Dimension）**。本项目使用的 `BAAI/bge-small-zh-v1.5` 把每段文本映射成一个 512 维向量，也就是说，地图上的每个点由 512 个数字确定。

---

## 二、向量如何比较

### 2.1 余弦相似度

两组数字之间的比较方式有多种，本项目采用**余弦相似度（Cosine Similarity）**。余弦相似度衡量的不是两个向量的距离，而是它们方向的夹角。

两个向量的方向越接近，夹角越小，余弦值越接近 1；方向越垂直，余弦值越接近 0。

系统之所以选择余弦相似度而不是欧氏距离，原因在于文本向量的长度本身没有意义。一段长文档与一段短句，即使讲的是同一件事，它们的向量长度也可能相差很大。

系统真正关心的是方向，也就是"这段文本在讲什么"，而不是"这段文本有多长"。余弦相似度恰好只看方向，因此它比欧氏距离更适合文本比较。

### 2.2 归一化

余弦相似度的计算公式里有一个除法，分母是两个向量的长度之积。当系统把每个向量都提前除以它自己的长度时，每个向量的长度就都变成了 1，这个分母随之恒等于 1。此时，余弦相似度的计算就退化成一次简单的点积。

这一步预处理称为**归一化（Normalization）**，准确地说叫 **L2 归一化**。归一化的好处有两层：

- **第一层，省去每次比较时重复计算长度。**
- **第二层，让相似度的取值范围稳定落在 -1 到 1 之间，便于设定阈值。**

本项目在生成向量时就完成了归一化，因此后续的比较可以只做点积。

> 归一化之后，点积与余弦相似度等价，比较因此变得极简。

---

## 三、维度与存储的取舍

### 3.1 维度不是越高越好

维度决定了每个向量占用的存储空间，也决定了每次比较的计算量。

| 维度 | 单个向量占用 | 说明 |
| --- | --- | --- |
| 512 维 | 约 2 KB | 本项目所选 |
| 1024 维 | 约 4 KB | 存储与计算翻倍 |

当知识库有十几万个切片时，这份差距会被放大到数百兆。检索时，系统需要对每个候选向量做一次比较，维度翻倍，比较的耗时也大致翻倍。

更高的维度确实可能带来更强的表达能力，但它同时也带来更高的成本与更长的延迟。因此在真实项目中，维度的选择是一次**权衡**，而不是一次"越大越好"的竞赛。

### 3.2 本项目为什么选择小模型

本项目选择 512 维的 `bge-small-zh-v1.5`，理由是客服政策语料本身偏短、条款偏中文，小模型已经足够表达这层语义。

实测数据支持了这个判断：在 65 条政策问句的评测集上，仅使用该模型，检索的 Precision@1 就达到 83.1%，Recall@3 达到 94.6%，这一成绩已经超过了 BM25 的 76.9% 与 90.0%。换言之，本项目在不引入更大模型的前提下，已经拿到了可用的语义召回能力。

读者在面试中应当主动说明这一点。本项目从未使用 `bge-m3` 这类大模型，仓库里出现过的 `BgeM3EmbeddingProvider` 只是**历史遗留的类名**，它实际加载的仍是 `bge-small-zh-v1.5`。

> 把类名当成模型名，是最容易被代码对质发现的一处错误。

---

## 四、本项目如何生成向量

### 4.1 三级优先级

`app/providers/embeddings.py` 中的 `build_embedding_provider` 按三级优先级选择嵌入提供者。

| 优先级 | 触发条件 | 实现 |
| --- | --- | --- |
| 第一 | 配置了 `EMBEDDING_API_KEY` 与 `EMBEDDING_BASE_URL` | 调用 OpenAI 兼容的嵌入接口 |
| 第二 | 远程未配置而本地模型可用 | 加载 `BAAI/bge-small-zh-v1.5` |
| 第三 | 以上两者都不可用 | 退回确定性的哈希向量 |

这三级的顺序体现了本项目的取舍：能用真实语义就用真实语义，实在不能用时，也要保证系统不中断。

第三级的哈希向量几乎没有语义，它的命中率约为 3%，只用于测试环境与无权重开发，绝不能写进简历，也不能把它说成"语义检索"。

### 4.2 编码与归一化

本地模型通过 `sentence-transformers` 加载。`BgeM3EmbeddingProvider._encode` 在编码时传入 `normalize_embeddings=True`，这一步就是前面所说的 L2 归一化。

查询侧与文档侧使用同一套模型、同一套归一化，只有这样，两侧的向量才落在同一个空间里，比较才有意义。

设备的选择由 `app/providers/device.py` 的 `resolve_torch_device` 决定。它优先使用显式配置的设备，其次检测 CUDA，再次检测 Apple 的 MPS，最后退回 CPU。

这层封装让同一份代码既能跑在有显卡的服务器上，也能跑在只有 CPU 的开发机上。

`BgeM3EmbeddingProvider._ensure_model` 负责真正加载模型，并在加载成功后从模型读取维度回填 `self.dim`。

`app/providers/embeddings.py` —— `BgeM3EmbeddingProvider._ensure_model`

```python
    def _ensure_model(self) -> Any | None:
        if self._model is not None:
            return self._model
        if not self._should_load():
            return None
        with self._load_lock:
            if self._model is not None:
                return self._model
            if self._load_error is not None:
                return None
            # ...
            device = resolve_torch_device(self._settings.local_embedding_device)
            try:
                logger.info(
                    "local_embedding_loading",
                    extra={"model": self._settings.local_embedding_model, "device": device},
                )
                self._model = self._load_sentence_transformer(device)
                dim = self._model.get_sentence_embedding_dimension()
                if dim:
                    self.dim = int(dim)
            except Exception as exc:  # model download / CUDA / Hub errors
                self._load_error = str(exc)
                logger.warning("local_embedding_load_failed", extra={"error": str(exc)})
                return None
            return self._model
```

`_ensure_model` 用一把锁保证模型只加载一次，并用 `_load_error` 记住失败原因、避免重复尝试。加载成功后它调用 `get_sentence_embedding_dimension` 读取真实维度并写回 `self.dim`，因此维度不是写死的常量，而是由模型决定。

本地模型的归一化在编码阶段完成。

`app/providers/embeddings.py` —— `BgeM3EmbeddingProvider._encode`

```python
    @staticmethod
    def _encode(model: Any, texts: list[str]) -> list[list[float]]:
        raw = model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        if raw and isinstance(raw[0], int | float):
            return [[float(value) for value in raw]]
        return [[float(value) for value in row] for row in raw]
```

关键行是 `normalize_embeddings=True`，它让 `sentence-transformers` 在编码时就对每个向量做 L2 归一化。归一化完成后，下游比较只需做点积，这正是 4.3 节要讲的 `cosine`。

### 4.3 向量如何被比较

`app/retrieval/vector.py` 中的 `cosine` 函数只有一行，它计算的是两个向量的点积。这一行之所以成立，正是因为上游已经完成了归一化。

内存向量库 `InMemoryVectorStore.search` 对每个候选记录调用这个函数，按得分从高到低排序，取前 `top_k` 条。Qdrant 向量库则把这项工作交给远端，但距离度量同样配置为 COSINE，二者保持一致。

`app/retrieval/vector.py` —— `cosine`

```python
def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))
```

这个函数只做逐元素相乘再求和，没有除以长度，因为它假定两侧向量已经归一化。`strict=False` 允许两侧长度不一致时按较短的一侧截断，不会直接抛错。

---

## 五、反例：不做归一化会怎样

假设系统省略了归一化这一步，直接对两个原始向量做点积，会发生什么。

考虑两段文本，第一段是"退货"，第二段是一篇长文，长文中只顺带提到一次"退货"。在未归一化的情况下，长文的向量长度远大于短句，即使它的方向与查询并不接近，它的点积也可能因为长度大而超过短句。

系统于是把这篇长文排在了真正相关的短句前面，相似度排序由此错乱。

> 归一化不是可有可无的优化，而是让余弦相似度成立的前提。一旦省略它，系统得到的排序就不再反映语义接近程度，而会不自觉地偏向长文本。

---

## 六、练习与指标回指

本部分的练习有两项。

- **第一项，手算相似度。** 取 `a = [1, 0, 1]` 与 `b = [0, 1, 1]`，先算余弦相似度，得到 `1/2 = 0.5`；再把两者归一化后做点积，应当得到同一个值 0.5，这验证了归一化之后点积等价于余弦。
- **第二项，选型陈述。** 读者应当能用三句话说明本项目为何使用 512 维小模型，其中至少包含一句关于语料偏短、一句关于成本，以及一句关于实测成绩。

本部分对应的指标是第 11 部分"评测体系"中的检索 Precision@1 与 Recall@3。仅使用 `bge-small-zh-v1.5` 时，这两项分别为 83.1% 与 94.6%，它是后面 Hybrid 检索的基础。

> **指标回指。** 读者在阅读第 4 部分"召回"时，可以回到本部分确认这组向量的来源与比较方式。

---

**本篇涉及的源码：** `app/providers/embeddings.py`、`app/providers/device.py`、`app/retrieval/vector.py`
