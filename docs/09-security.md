# 09 · 安全与护栏

> 一句话：用户问题和检索结果都是 untrusted；写工具默认拒绝；订单对非属主表现为「不存在」。

## 本章目录

1. [密钥](#密钥)
2. [Prompt Injection](#prompt-injection)
3. [查询边界](#查询边界)
4. [工具链](#工具链)
5. [写操作](#写操作)
6. [依赖降级](#依赖降级)

对应：`app/guardrails/`、`app/tools/permissions.py`、`app/config/settings.py`。

## 密钥

- `.env` gitignore；镜像不 COPY `.env`
- 类型 `SecretStr`，避免 `str(settings)` 泄露
- 密钥进过聊天记录 → 去供应商控制台轮换

### 代码摘要

```python
# app/config/settings.py
deepseek_api_key: SecretStr = SecretStr("")
admin_api_token: SecretStr = SecretStr("")
```

管理面：`APP_ENV=production` 且未配 `ADMIN_API_TOKEN` → admin 直接 401。比对 `hmac.compare_digest`。

## Prompt Injection

### 要点

两层：① 用户 query 正则拦截明显 jailbreak；② 检索/工具内容当数据，answer prompt 带 `UNTRUSTED_CONTEXT_BANNER`。知识库里出现 `Ignore previous instructions` 也不得升级为系统指令。

### 代码摘要

```python
# app/guardrails/injection.py
_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"忽略(以上|之前|上面)(的)?(指令|提示)", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"system\s*prompt", re.I),
)

def detect_prompt_injection(text: str) -> None:
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(text):
            raise GuardrailError(..., error_code=ErrorCode.PROMPT_INJECTION_BLOCKED)
```

护栏节点在 Graph 最前面：`apply_guardrail` → 命中则 `refuse_answer`，不调工具。

单测：`tests/unit/test_guardrails.py`、`tests/e2e/test_chat_api.py`。

### 为什么

只靠正则挡不住隐蔽注入，所以检索内容永远不进 system 角色。Banner 在 `app/core/constants.py` 的 `UNTRUSTED_CONTEXT_BANNER`。

## 查询边界

越权话题（违法、政治、医疗诊断、炒股等）→ `QUERY_OUT_OF_SCOPE` / `strategy=refuse`。实现：`app/guardrails/boundary.py` + 意图 `out_of_scope`。

## 工具链

```text
LLM JSON → Schema（Pydantic）→ 业务校验（订单可见性）→ 权限（HITL）→ Tool.execute
```

### 代码摘要

```python
# app/tools/base.py
def parse(self, arguments) -> BaseModel:
    return self.input_model.model_validate(arguments)  # 失败 → InvalidRequestError

async def run(self, arguments, context) -> ToolResult:
    parsed = self.parse(arguments)
    return await self.execute(parsed, context)
```

订单对非属主统一「不存在」，包括 `u_demo` 与 `anonymous`；只有订单的 `user_id` 与请求中的值一致才可读写。演示单只属于 `u_demo`。当前 API 尚无身份认证，请求方仍能自行填写 `user_id`，因此不能直接暴露给不可信客户端；生产部署须在可信网关完成认证并绑定用户身份，不能依赖请求体中的 `user_id` 做授权。

`order_id` 正则 `^[A-Za-z0-9_-]+$`。SQL 绑定参数；`ILIKE` 转义 `%` `_`。

## 写操作

退款/取消必须确认。超时重试靠幂等键。审计只记 `trace_id` + action + `order_id`。详见 [05 · HITL](05-agents-and-tools.md#hitl-与幂等)。

## 依赖降级

| 依赖 | 失败时 |
|---|---|
| Redis | 内存限流/缓存（多副本不共享） |
| Qdrant | 内存向量 ingest |
| Embedding / 本地 bge-small | 加载失败：hash 占位；已加载：`BAAI/bge-small-zh-v1.5` |
| Cross-Encoder | 未加载权重：词面 overlap；已加载：本地 `bge-reranker-base` |
| DeepSeek | 启动 Fake；运行中请求 503，不编造成功答案 |

---

上一章 [08](08-reliability.md) · 下一章 [10 · 评测](10-evaluation.md)
