# 切块与稳定标识

本文是第三部分的第二篇正文，它讲清切片如何切分、每个切片如何带稳定的标识与元数据。

全文分为五节，前两节讲切块策略，中间两节讲标识与元数据，最后一节给出反例与练习。

---

## 一、为什么要切块

### 1.1 长文不能整段检索

嵌入模型对输入长度有上限，一段过长的文本也无法被压成一个有区分度的向量。

如果把整篇政策文档当作一个检索单位，那么这篇文档对应的向量会变成所有条款的平均，它既不能精确表达"七天无理由"，也不能精确表达"定制商品例外"。用户无论问哪一条，命中的都是同一篇，排序也就失去了意义。

因此，系统必须把长文切成若干短块，每个短块作为一个独立的检索单位。

这个过程称为**切块（Chunking）**，切出来的每一块称为一个**切片（Chunk）**。

### 1.2 切块的两难

切块有一个内在的两难。

- **切得太碎。** 每个切片承载的上下文太少，检索虽然能命中，但命中的片段可能缺少必要的前提。
- **切得太大。** 每个切片混入太多无关内容，语义被稀释，排序反而变差。

> 切块参数的选择，本质上是在"上下文完整"与"语义聚焦"之间找一个平衡点。

---

## 二、本项目的切块策略

### 2.1 两层切分

本项目采用两层切分，它不追求语义自适应切分，而是走一条确定、可复现的路线。

- **第一层是按结构分段。** 当解析器来自 Unstructured 时，系统用 `Title` 元素作为章节边界；当解析降级到 Markdown 时，系统用 `#{1,3}` 三级标题作为边界。
- **第二层是段内滑窗。** 系统在每一段内部按固定字符数滑动切分。

滑窗的两个关键参数如下。

| 参数 | 取值 | 作用 |
| --- | --- | --- |
| `MAX_CHUNK_CHARS` | 500 | 切片上限 |
| `OVERLAP_CHARS` | 60 | 相邻切片的重叠 |

这两层分工清晰：结构分段负责让切片尊重文档本身的逻辑，滑窗负责让过长的段落不至于挤成一块。

重叠的作用是防止语义被切断：如果一句话恰好落在两个切片的边界上，重叠部分会让这句话至少完整地出现在其中一个切片里。

滑窗由 `_window` 实现，它负责在段落内部按固定字符数滑动切分。

`app/retrieval/chunking.py` —— `_window`

```python
def _window(text: str, size: int, overlap: int) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(cleaned) <= size:
        return [cleaned] if cleaned else []
    pieces: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        pieces.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return pieces
```

`_window` 先把文本按 `size` 切成一段段，切完一段后把起点回退 `overlap` 个字符，于是相邻切片之间自然产生重叠。`start = max(end - overlap, start + 1)` 保证起点至少前进一个字符，避免 `overlap` 过大时陷入死循环。

### 2.2 表格单独成块

本项目对表格有一条例外规则：**表格单独成块，禁止用滑窗把它切碎**。

原因是表格的语义依赖行列结构，一旦被滑窗切开，表头与数据行分离，整张表就失去了意义。

> 这条规则与上一篇提到的"清洗时表格不拼硬换行"是同一个道理，二者都在保护表格的结构完整性。

---

## 三、为什么标识必须稳定

### 3.1 稳定标识的含义

每个切片都需要一个标识，本项目称它为 `chunk_id`。

这个标识有一条硬性要求：它必须在多次入库之间保持稳定。

- `app/retrieval/chunking.py` 中的 `stable_chunk_id` 把 `chunk_id` 定义为 `{document_id}_{两位序号}`。
- `document_id_from_path` 则把 `document_id` 定义为 `{文件名}_{路径 SHA1 前 8 位}`。

这一定义完全由文档路径与切片顺序决定，不含任何随机成分。

`stable_chunk_id` 与 `document_id_from_path` 定义了这两个标识。

`app/retrieval/chunking.py` —— `stable_chunk_id` 与 `document_id_from_path`

```python
def stable_chunk_id(document_id: str, chunk_index: int) -> str:
    """IDs are deterministic across ingest runs so citations stay stable."""
    return f"{document_id}_{chunk_index:02d}"


def document_id_from_path(path: Path) -> str:
    stem = path.stem.lower().replace(" ", "_")
    digest = hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{stem}_{digest}"
```

`stable_chunk_id` 只是把文档标识与两位序号拼接，`chunk_index:02d` 让序号固定占两位，保证同一文档的切片顺序变化时标识仍然可比。`document_id_from_path` 从文件名与路径 SHA1 的前 8 位拼出文档标识，两个输入都不含随机数，因此同一份文件重复入库得到的标识完全一致。

### 3.2 为什么不能用随机数

系统之所以禁止用 `uuid4` 生成 `chunk_id`，原因有三层。

| 层面 | 依赖 | 标识变化后的后果 |
| --- | --- | --- |
| 引用稳定 | 用户看到的引用、答案里标注的来源 | 历史引用失效 |
| 向量库覆盖 | Qdrant 以 `chunk_id` 派生值作为 point id | 向量库不断堆积重复数据 |
| 评测稳定 | 评测金标按文档名匹配 | 评测无法复现 |

> 三层原因指向同一件事：`chunk_id` 的稳定性是引用、存储与评测的共同前提。

### 3.3 Qdrant 的 point id

Qdrant 要求 point id 是 UUID 或整数，因此 `app/retrieval/vector.py` 中的 `stable_point_id` 把 `chunk_id` 做一次 MD5 派生，转成 UUID。

这一步同样是确定性的：只要 `chunk_id` 不变，派生的 UUID 也不变，重新入库就会覆盖同一个点。

---

## 四、每个切片带什么元数据

除了内容与标识，每个切片还携带一组元数据。

`app/schemas/retrieval.py` 中的 `RetrievedChunk` 定义了这些字段，其中包括标题 `title`、章节 `section`、类目 `category`、政策版本 `policy_version`，以及解析器、元素类型与页码等。

这些字段有两类用途。

- **展示。** 系统在生成引用时，需要知道切片的标题与章节，才能告诉用户"这条依据来自哪一份政策的哪一节"。
- **过滤。** 系统可以按类目缩小检索范围，也可以按政策版本区分新旧条款。

> 元数据既是引用的来源，也是过滤的依据。

---

## 五、反例与练习

假设系统改用固定字符数硬切，而不按结构分段。

一篇政策文档里有一个小标题"定制商品退货"，紧接着是它的正文。硬切之后，这个标题可能与它前面的上一节内容挤在同一个切片里，也可能与它的正文被切到两个不同的切片里。

无论哪种情况，标题与正文都会分离，检索时系统要么召回了孤立的标题而缺少正文，要么召回了正文而缺少标题的限定，用户拿到的依据都是残缺的。

> 这个反例说明，按结构分段不是可有可无的优化，而是保证切片语义完整的前提。

本部分的练习有两项。

- **设计切块参数。** 读者应取一篇真实政策文档，为它设计切片大小与重叠量，并说明为什么这样选。
- **验证标识稳定。** 读者应说明如果 `chunk_id` 改用 `uuid4`，引用、向量库覆盖与评测这三处会分别出现什么问题。

> **指标回指。** 本篇对应的指标同样是第 11 部分"评测体系"中的检索 Recall@3 与 Precision@1。切块粒度直接决定检索结果的排序质量，读者在阅读第 5 部分"融合精排"时，可以回到本篇确认候选切片的来源与结构。

---

**本篇涉及的源码：** `app/retrieval/chunking.py`、`app/retrieval/vector.py`、`app/schemas/retrieval.py`
