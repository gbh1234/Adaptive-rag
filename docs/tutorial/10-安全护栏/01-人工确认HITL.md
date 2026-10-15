# 人工确认 HITL

本文是第十部分的第一篇正文，它讲清写操作如何从"模型提案"走到"用户授权"。全文分为五节：前两节讲 HITL 的思路与流程，中间两节讲令牌校验与幂等，最后一节给出反例与练习。

---

## 一、为什么写操作要停下来

在只读场景里，模型说错话最多让用户困惑；在写入场景里，模型做错事可能造成不可逆的损失。退款一旦提交，钱就出去了；订单一旦取消，可能无法恢复。

模型本质上是概率系统，它可能被措辞误导，也可能被恶意输入诱导。让这样一个系统直接执行写操作，等于把不可逆的后果交给一个不确定的判断。

**HITL（Human In The Loop，人在回路）** 的思路是：把"想做"和"真做"拆开。模型可以提出一个动作提案，但它无权直接执行；只有得到用户的明确授权，写操作才被允许。

> 这样，最终的决策权回到了人手里。

---

## 二、HITL 的流程

本项目的 HITL 流程分四步。

| 步骤 | 负责方 | 产出 |
| --- | --- | --- |
| **提案** | 规划器 | `ActionProposal` |
| **返回** | 系统 | 待确认答案 |
| **确认** | 用户 / 客户端 | `confirm_action_id` |
| **执行** | 执行器 | 写工具运行 |

第一步是**提案**。当规划器发现计划里含有写入或破坏性工具，且当前请求没有确认标识时，它不执行，而是生成一个 `ActionProposal`。`app/agents/nodes/planner.py` 中的 `planner_node` 会构造这个提案，它包含动作标识 `action_id`、工具名 `tool_name`、参数 `arguments`、风险等级 `risk` 与一句说明 `summary`。

第二步是**返回**。系统把提案放进状态的 `pending_action` 字段。`generate_node` 在发现有待确认动作时，直接把提案的说明作为答案返回，例如"即将执行 cancel_order，需要你确认后才会真正提交"。用户此时看到的不是"已完成"，而是"待确认"。

第三步是**确认**。用户同意后，客户端在下一轮请求里带上 `confirm_action_id`，它的值就是提案的动作标识。

第四步是**执行**。执行器看到请求里带了确认标识，才允许写工具运行。

`app/agents/nodes/executor.py` —— `executor_node` 的写操作分支

```python
        tool = registry.get(step.tool_name)
        confirmed = bool(state.get("confirm_action_id"))
        try:
            if tool.risk in WRITE_RISKS:
                assert_permitted(tool, confirmed=confirmed)
                idem_key = context.confirmed_action_id or context.idempotency_key
                if idem_key:
                    fp = _fingerprint(tool.name, step.arguments)
                    existing = await idempotency.get_if_matches(idem_key, fp)
                    if existing is not None:
                        results.append(
                            ToolResult(
                                name=tool.name, success=True, output=existing, risk=tool.risk
                            )
                        )
                        TOOL_CALLS.labels(tool=tool.name, status="idempotent").inc()
                        calls += 1
                        continue
                    result = await tool.run(step.arguments, context)
                    await idempotency.put(idem_key, fp, result.output)
                    TOOL_CALLS.labels(tool=tool.name, status="ok").inc()
                    results.append(result)
                    calls += 1
                    continue
```

`executor_node` 先取出工具，再用 `state.get("confirm_action_id")` 计算 `confirmed` 布尔值。当工具属于 `WRITE_RISKS` 时，它调用 `assert_permitted` 校验确认标识；没有确认标识就会在这里抛出 `ToolPermissionError`，写操作不会执行。通过校验后，它才继续走幂等查询与真正执行的分支。

> 这四步把"模型想退"和"用户同意退"分成了两件事，任何一步缺失，写操作都不会发生。

---

## 三、令牌为什么必须服务端校验

### 3.1 默认拒绝

`app/tools/permissions.py` 中的 `assert_permitted` 是这套流程的守门人。它检查工具的风险等级：如果工具属于写入或破坏性操作，且当前请求没有确认标识，它就抛出 `ToolPermissionError`。

> 这是一种**默认拒绝**的设计：写操作在没有授权时一律被拒，只有明确授权才被放行。

### 3.2 提示词不是权限系统

这里有一条必须强调的原则：确认令牌的校验**必须**发生在服务端代码里，不能写进提示词。

原因在于，提示词是模型输入的一部分，模型可以被诱导忽略它。如果系统只在提示词里写一句"退款需要用户确认"，那么一次成功的注入就能让模型跳过这句话，直接执行退款。

> 而 `assert_permitted` 是纯代码，它不看模型怎么说，只看请求里有没有确认标识。模型无法绕过它，因为它根本不经过模型。

### 3.3 越权查询的同一原则

同样的原则也适用于查询。`app/repositories/order_repository.py` 对非属主的订单统一返回"不存在"，而不是返回"无权查看"。

系统之所以这样做，是为了避免用户通过"对错"来探测别人的订单号：如果系统对存在但无权访问的订单返回"无权"，用户就能借此确认这个订单号是真实存在的。

> 统一返回"不存在"，让探测失去意义。

---

## 四、幂等如何兜底

### 4.1 超时重试的隐患

即便有了确认流程，写操作仍然可能重复。原因在于，大模型调用与网络传输都可能超时，客户端可能重试，系统也可能重试。

> 如果没有幂等保护，一次超时重试就可能生成两笔退款。

### 4.2 指纹与冲突

本项目的幂等由 `IdempotencyRepository` 实现。执行器在执行写工具前，先算出参数指纹，也就是把工具名与参数序列化后取 SHA256，再以确认标识或幂等键为键去查历史。

如果查到相同指纹，系统返回首次结果；如果键相同但指纹不同，系统抛出 `IDEMPOTENCY_CONFLICT`。

`app/agents/nodes/executor.py` —— `_fingerprint`

```python
def _fingerprint(tool_name: str, arguments: dict) -> str:
    payload = json.dumps(
        {"tool": tool_name, "arguments": arguments}, sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(payload.encode()).hexdigest()
```

`_fingerprint` 把工具名与参数一起序列化，用 `sort_keys=True` 保证字典顺序稳定，再取 SHA256 作为指纹。参数只要有任何一处不同，指纹就会改变，因此同一幂等键配上不同参数会被识别为冲突，而不是重复。

> 这个设计把"重复"与"冲突"分开处理，既保证了同一操作只执行一次，又防止了"换个参数重复提交"。

---

## 五、反例与练习

假设系统去掉 HITL，让模型直接执行退款。用户一句"帮我退款"，模型立即发起退款，用户甚至来不及确认；如果用户随后说"我不是要退款，我是想问退款进度"，钱已经出去了。

> 这个反例说明，HITL 的价值在于给不可逆操作设一道人工闸门。这道闸门可能带来一点交互成本，但它换来的是不可逆损失的基本防线。

本部分的练习有两项。

- 第一项是**推演流程**。读者应描述一次退款请求从发起、提案、确认到执行的完整过程，指出每一步由谁负责。
- 第二项是**解释原则**。读者应说明为什么确认令牌必须在服务端校验，而不是写进提示词。

> **指标回指。** 本篇对应的指标是第 11 部分"评测体系"中的工具路径准确率与端到端延迟。在 16 条端到端用例中，`e15` 的取消订单走了人工确认流程，系统返回了待确认动作但并未真正取消，这正是 HITL 生效的证据。读者在阅读下一篇时，可以对照理解输入输出两侧的护栏如何协同。

---

**本篇涉及的源码：** `app/agents/nodes/planner.py`、`app/agents/nodes/executor.py`、`app/tools/permissions.py`、`app/repositories/order_repository.py`
