# 可靠性与降级

> 本文是第十二部分的第一篇正文，它讲清系统如何面对异常。全文分为五节，前两节讲超时与重试，中间两节讲失败语义与降级，最后一节给出反例与练习。

---

## 一、超时

任何一次外部调用都必须设超时。如果系统对一个外部接口使用无限等待，那么一次对端挂起就可能拖住整个请求，进而耗尽连接池，最终拖垮服务。

本项目在 `app/providers/deepseek.py` 中为模型调用设置了明确的超时，四个超时各管一件事。

| 超时项 | 取值 | 管什么 |
| --- | --- | --- |
| 连接超时 | 3 秒 | 连得上连不上 |
| 读取超时 | `llm_timeout_seconds`，默认 30 秒 | 连上之后多久没响应算失败 |
| 写入超时 | 10 秒 | 发请求本身不能卡死 |
| 连接池超时 | 5 秒 | 从池里取不到连接时等多久 |

把这四个超时分开设置，是为了让不同类型的异常有不同的容忍度。项目对 Qdrant 调用设置了 **5 秒**超时，并把同步调用包在 `asyncio.to_thread` 里，避免阻塞事件循环。

---

## 二、重试

### 2.1 哪些错误应当重试

重试不能无差别进行。本项目在 `app/core/retry.py` 中区分了两类状态码。

| 类别 | 状态码 | 性质 |
| --- | --- | --- |
| 可重试 | 超时、连接错误、408、429、500、502、503、504 | 瞬时错误，重试一次可能成功 |
| 不可重试 | 400、401、403、404、422 | 确定性错误，重试只会重复失败 |

这里有一条反例值得强调：如果一个 **401** 错误被重试，那么一个坏掉的密钥会被放大成一串无效的计费请求。

> 把 401 排除在重试之外，是一条成本纪律。

`app/core/retry.py` —— `RETRYABLE_HTTP_STATUS`、`NON_RETRYABLE_HTTP_STATUS`、`is_retryable_status`

```python
RETRYABLE_HTTP_STATUS = frozenset({408, 429, 500, 502, 503, 504})
NON_RETRYABLE_HTTP_STATUS = frozenset({400, 401, 403, 404, 422})


def is_retryable_status(status_code: int) -> bool:
    return status_code in RETRYABLE_HTTP_STATUS
```

项目用两个 `frozenset` 把状态码分成可重试与不可重试两组，`is_retryable_status` 只做一次集合成员判断。注意源码把 500 也放进了可重试集合，而 400、401、403、404、422 被明确排除，这正是"确定性错误重试只会重复失败"这条纪律的落点。

### 2.2 全抖动退避

可重试的错误用**指数退避**处理，也就是每次重试的等待时间翻倍。但单纯的指数退避有一个隐患：如果多个实例同时失败，它们会按同样的节奏醒来，同时发起重试，形成**重试风暴**。

本项目因此使用**全抖动（Full Jitter）**：等待时间取 `随机数(0, min(上限, 基数 * 2^次数))`。随机化让不同实例的唤醒时刻错开，把重试压力摊平。

还有一条边界：流式响应不在中途重试。原因是流式输出已经向用户推送了一部分 token，如果中途重试，用户会看到重复内容。

> 对已经开始的流，系统只能让它失败或完成，不能从头再来。

`app/core/retry.py` —— `with_exponential_backoff`、`_full_jitter_delay`

```python
async def with_exponential_backoff(
    operation: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 8.0,
    operation_name: str = "operation",
    trace_id: str | None = None,
) -> T:
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await operation()
        except AppError as exc:
            last_error = exc
            if not exc.retryable or attempt == max_attempts - 1:
                raise
            delay = _full_jitter_delay(attempt, base_delay_seconds, max_delay_seconds)
            # ...
            await asyncio.sleep(delay)
        # ...
    assert last_error is not None
    raise last_error


def _full_jitter_delay(attempt: int, base: float, cap: float) -> float:
    ceiling = min(cap, base * (2**attempt))
    return random.uniform(0.0, ceiling)
```

`with_exponential_backoff` 最多重试 `max_attempts` 次，只有当异常带有 `retryable` 标记且尚未用尽次数时才继续，否则立即 `raise`。真正的等待时长由 `_full_jitter_delay` 给出：它先算出 `base * 2^attempt` 并以 `cap` 封顶，再取 `random.uniform(0.0, ceiling)`，也就是文档所说的全抖动公式，随机化把多实例的重试时刻错开。

---

## 三、失败语义

系统必须把业务失败与系统失败分开。本项目的失败语义可以概括为一张对照表。

| 情形 | 返回 | 说明 |
| --- | --- | --- |
| 政策证据不足 | 200 | 业务结果，文案为不确定或转人工 |
| 注入或越权 | 200 | 业务结果，标记 `refused` 为真 |
| 模型超时 | 503 | 错误码 `LLM_TIMEOUT` |
| 两路检索都失败 | 503 | 错误码 `VECTOR_DB_UNAVAILABLE` |
| 数据库不可用 | 503 | 系统失败 |
| 限流 | 429 | 系统失败 |

这里有一条重要区别：**限流故障应当 fail-open，鉴权故障应当 fail-closed**。限流组件挂了，系统应当放行请求，而不是把整站客服打挂；鉴权组件挂了，系统应当拒绝请求，而不是放行未授权访问。

> 一个偏向可用性，一个偏向安全，二者的方向相反，取决于故障的后果。

---

## 四、降级矩阵

本项目的核心设计之一是：任何一项外部依赖不可用，都不应让整个服务瘫痪。系统为此准备了一张降级矩阵。

| 依赖 | 不可用时的行为 |
| --- | --- |
| Redis | 限流与缓存退回进程内实现 |
| Qdrant | 向量退回内存库 |
| 嵌入模型 | 向量退回哈希实现 |
| Cross-Encoder | 精排退回词面重叠 |
| 模型 | 启动用 Fake 提供者，运行中返回 503 |

Redis 不可用时，限流与缓存退回进程内实现，代价是多副本之间不共享状态。模型不可用时，系统启动用 Fake 提供者，运行中返回 503，绝不编造一个成功的答案。

> 这张矩阵体现了一条原则：降级要降得诚实。系统在降级时不会假装自己还有原来的能力，它要么用一个明确更弱的能力顶上，要么干脆返回错误。把降级路径伪装成完整能力，比直接失败更危险，因为它会让使用者产生错误的信任。

---

## 五、反例与练习

假设系统对模型调用不设超时，也不做重试分类。某一天模型服务出现波动，响应变慢，大量请求卡在等待上，连接池被占满，新的请求无法获取连接，整站客服不可用。

> 这个反例说明，超时与重试分类不是可选的优化，而是系统在异常面前保持可用的前提。

本部分的练习有两项。

- **第一项，判断重试。** 读者应说明 429 与 401 分别应当如何处理。429 可以重试，因为它是瞬时限流；401 不应重试，因为它是确定性鉴权失败。
- **第二项，解释抖动。** 读者应说明如果去掉随机化，多个实例会同时重试，形成重试风暴。

> **指标回指。** 本篇对应的指标是第 11 部分"评测体系"中的端到端延迟与错误码分布。可靠性设计直接决定了系统在异常时的行为，读者在阅读下一篇时，可以对照理解这些行为如何被日志与指标观测到。

---

**本篇涉及的源码：** `app/providers/deepseek.py`、`app/core/retry.py`
