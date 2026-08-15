---
title: "Harness Engineering 之三：Agent 编排——把 AI 关进改不错的流程里"
subtitle: "编排器不该是 AI——它应该是确定性的轨道，AI 只是轨道上的一节车厢。从 DAG 调度、三原语到对抗验证，搭一个改不错的流程引擎"
description: "单 Agent 不够用，多 Agent 不编排更糟糕。编排器的核心设计选择：确定性引擎 + AI 作为可选步骤。本文从 DAG 调度、pipeline/parallel/agent() 三原语、Generator+Reviewer 对抗验证，到 seneschal 确定性分层的工程参考，给出一套可落地的编排设计方法。"
date: 2026-07-23 23:30:00+08:00
lastmod: 2026-07-23 23:30:00+08:00
slug: "harness-engineering-orchestration"
author: "whitefirer"
authorLink: "https://whitefirer.org"
draft: true
hiddenFromHomePage: false

tags: ["tech", "ai", "harness engineering", "agent", "orchestration", "workflow", "claude code", "seneschal"]
series: ["harness-engineering"]
categories: ["Tech"]
toc:
    auto: false
---

> 沙箱让 Agent 干不了坏事，编排让流程把好事干成。但编排器本身不该是 AI——它应该是确定性的轨道，AI 只是轨道上的一节车厢。

---

## 0. 同一个任务，两种跑法

先看一个具体的任务：从一段需求描述出发，生成 Python 代码 + 单元测试 + 代码审查。

**跑法 A：裸 Agent。** 给一个 Agent 完整的 prompt，让它从头到尾搞定。Agent 自信地跑了一轮——代码写出来了，测试也写了，审查意见是"Looks good"。但你翻开一看：测试只覆盖了主路径，两个边界条件没测；审查漏了三个 `except: pass`；有一个函数参数类型写错了。

跑了四十分钟，产出不能用。

**跑法 B：编排过的流水线。** 三个 Agent，三个角色：

```
需求文档
    │
    ▼
[Agent 1: 写代码] ──→ 产出: code.py
    │
    ▼
[Agent 2: 写测试] ──→ 产出: test_code.py, 覆盖率报告
    │
    ▼
[Agent 3: 代码审查] ──→ 产出: review.md
    │
    ▼
[条件判断: review.md 是否包含 "REJECT"?]
    │
    ├── 是 → 打回 Agent 1，带上审查意见
    │
    └── 否 → ✅ 通过，合并
```

同样四十分钟。代码过了全部测试，审查意见是"三个 `except: pass` 需要显式声明异常类型"，Agent 1 被打回一次后修好了。

区别不在模型——跑法 A 和 B 用的是同一个 Claude。区别在**编排**。

[上一篇](/posts/2026/07/19/harness-engineering-sandbox/)我把 Agent 关进了干不了坏事的沙箱。这一篇回答下一个问题：沙箱里的 Agent，怎么组织起来把活干好。

---

## 1. 单 Agent 有天花板，多 Agent 不是堆人头

### 1.1 单 Agent 为什么不够

一个 Agent 同时想架构、写代码、测自己、审自己——等于让同一个人当球员、裁判、教练、记分员。

不是能力问题，是结构问题。三个硬天花板：

- **上下文衰减。** 任务越长，Agent 忘得越多。前十分钟想的架构决策，写到第四十分钟可能已经被压缩掉了。Context Engineering 那篇讲过压缩的代价，这里不再展开——只说一句：你不想让 Agent 在忘了需求之后继续写代码。
- **自我审查是幻觉。** "请审查你刚才写的代码"——这和"请确认你没犯错"是同一句话。Agent 不是故意偷懒，是审查自己的输出时它调的是同一套权重。真正有效的审查必须来自独立视角。
- **没有检查点。** 裸 Agent 跑一个长任务，中间在哪断了、断在哪一步、前面几步成功了没有——全凭运气。重跑就是从零开始。

### 1.2 不加编排的多 Agent 更危险

那就拆吧。一个写代码，一个写测试，一个审。各干各的，各配各的 prompt——然后问题来了。

第二个 Agent 拿到第一个的输出："这个函数接受一个 `data` 参数……"函数名变了。第一个 Agent 重构时把 `parse_config` 改成了 `parse_yaml_config`，但输出里没更新。第二个 Agent 写的测试调的还是旧函数名。跑都跑不起来。

没有编排的 Agent 之间是"扔过墙"模式——上游把东西扔过去，下游接住、皱眉、默默处理了。格式对不上？它努力猜。少了一个字段？它自己填一个默认值。最终产出烂在哪一步？没人知道。

### 1.3 编排要解决的三个元问题

编排不是"让 Agent 跑起来"——cron job 就能让 Agent 跑起来。编排要回答的是三个更难的问题：

1. **谁先谁后，依赖是什么？** 测试不能在没有代码的情况下跑。审查不能在测试结果出来之前做结论。依赖关系是图，不是列表。
2. **中间断了怎么办？** 第三步失败，能不能从第三步重试而不是从零开始？重试的时候前面的结果还在不在？
3. **怎么知道做对了？** Agent 说"做好了"不算数。谁来判断？判断标准是谁定的？不通过怎么办？

这三个问题的答案凑在一起，就是编排器的设计蓝图。而其中一个最反直觉的决策摆在最前面——编排器自己该不该是 AI。

---

## 2. 编排器应该是确定性的，AI 只是里面一个函数

### 2.1 为什么不能让 AI 管流程

AI 做编排有两个致命缺陷。

**幻觉。** 模型可能"觉得"第三步已经做完了——它输出了一行"Step 3 complete"，但实际什么都没执行。你拿到的不是编排日志，是一篇小说。

**不可重放。** 同一个 workflow 输入跑两次，AI 编排器可能走出两条不同的路径——第二次它"想了想"，觉得换个顺序更好。如果第一次跑出了错，你连重现都重现不了。不可重放的流程，出了问题全是玄学。

这两个缺陷有一个共同根因：**编排器的核心职责是"保证"，不是"建议"。** 你不需要编排器告诉你"可能应该先跑 A 再跑 B"——你需要它保证 A 跑完才跑 B，A 输出了正确的变量名，B 拿到的就是那个变量。这是机器的活，不是思考的活。

### 2.2 DAG 是编排器的骨架

依赖关系、拓扑排序、波次并发——这三个东西是计算科学里打磨了几十年的确定性基础设施，不因为"现在有了 AI"而失效。

我自己的开源项目 [seneschal](https://github.com/whitefirer/seneschal)（觞政）用的就是 DAG 波次调度：Kahn 算法做拓扑排序，无依赖的节点同一波内并发执行，一波跑完才进下一波。AI 步骤在这个图里就是一个普通节点——编排器不关心它内部怎么调模型，只问两件事："前置步骤跑完了吗？""输出写进变量了吗？"

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 360" width="100%" style="max-width:680px;display:block;margin:1.2em auto"><defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#9ca3af"/></marker><marker id="arrow-red" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" fill="#ef4444"/></marker><filter id="sh"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.06"/></filter></defs>
<!-- Wave labels -->
<text x="10" y="36" fill="#9ca3af" font-size="11" font-family="system-ui,sans-serif">Wave 0</text>
<text x="10" y="106" fill="#9ca3af" font-size="11" font-family="system-ui,sans-serif">Wave 1</text>
<text x="10" y="180" fill="#9ca3af" font-size="11" font-family="system-ui,sans-serif">Wave 2</text>
<text x="10" y="256" fill="#9ca3af" font-size="11" font-family="system-ui,sans-serif">Wave 3</text>
<!-- Wave 0 -->
<g filter="url(#sh)"><rect x="240" y="16" width="180" height="40" rx="8" fill="#6366f1"/><text x="330" y="41" text-anchor="middle" fill="#fff" font-size="13" font-weight="700" font-family="system-ui,sans-serif">解析需求</text></g>
<!-- Wave 0 → Wave 1: fan out -->
<line x1="300" y1="56" x2="180" y2="80" stroke="#9ca3af" stroke-width="1.5" marker-end="url(#arrow)"/>
<line x1="360" y1="56" x2="500" y2="80" stroke="#9ca3af" stroke-width="1.5" marker-end="url(#arrow)"/>
<!-- Wave 1: 2 parallel nodes -->
<g filter="url(#sh)"><rect x="80" y="84" width="200" height="40" rx="8" fill="#10b981"/><text x="180" y="109" text-anchor="middle" fill="#fff" font-size="12" font-weight="700" font-family="system-ui,sans-serif">写代码（AI）</text></g>
<g filter="url(#sh)"><rect x="400" y="84" width="200" height="40" rx="8" fill="#f59e0b"/><text x="500" y="109" text-anchor="middle" fill="#fff" font-size="12" font-weight="700" font-family="system-ui,sans-serif">生成测试框架</text></g>
<!-- Wave 1 → Wave 2: straight down (each feeds its own child) -->
<line x1="180" y1="124" x2="140" y2="152" stroke="#9ca3af" stroke-width="1.5" marker-end="url(#arrow)"/>
<line x1="500" y1="124" x2="510" y2="152" stroke="#9ca3af" stroke-width="1.5" marker-end="url(#arrow)"/>
<!-- Wave 2: 2 parallel nodes -->
<g filter="url(#sh)"><rect x="40" y="156" width="200" height="40" rx="8" fill="#ef4444"/><text x="140" y="181" text-anchor="middle" fill="#fff" font-size="12" font-weight="700" font-family="system-ui,sans-serif">写单元测试（AI）</text></g>
<g filter="url(#sh)"><rect x="410" y="156" width="200" height="40" rx="8" fill="#ef4444"/><text x="510" y="181" text-anchor="middle" fill="#fff" font-size="12" font-weight="700" font-family="system-ui,sans-serif">跑已有测试套件</text></g>
<!-- Wave 2 → Wave 3: converge -->
<line x1="140" y1="196" x2="300" y2="230" stroke="#9ca3af" stroke-width="1.5" marker-end="url(#arrow)"/>
<line x1="510" y1="196" x2="380" y2="230" stroke="#9ca3af" stroke-width="1.5" marker-end="url(#arrow)"/>
<!-- Wave 3 -->
<g filter="url(#sh)"><rect x="200" y="234" width="260" height="42" rx="8" fill="#1f2937"/><text x="330" y="260" text-anchor="middle" fill="#fff" font-size="13" font-weight="700" font-family="system-ui,sans-serif">代码审查（AI）</text></g>
<!-- Wave 3 → condition split -->
<line x1="290" y1="276" x2="200" y2="302" stroke="#ef4444" stroke-width="1.5" marker-end="url(#arrow-red)"/>
<line x1="370" y1="276" x2="470" y2="302" stroke="#10b981" stroke-width="1.5" marker-end="url(#arrow)"/>
<!-- Labels on branches -->
<text x="230" y="298" fill="#ef4444" font-size="10" font-family="system-ui,sans-serif">REJECT</text>
<text x="440" y="298" fill="#10b981" font-size="10" font-family="system-ui,sans-serif">PASS</text>
<!-- Branch outcomes -->
<g filter="url(#sh)"><rect x="100" y="306" width="200" height="34" rx="6" fill="#fef2f2" stroke="#ef4444" stroke-width="1"/><text x="200" y="328" text-anchor="middle" fill="#ef4444" font-size="12" font-weight="700" font-family="system-ui,sans-serif">编排器重跑子 DAG</text></g>
<g filter="url(#sh)"><rect x="380" y="306" width="180" height="34" rx="6" fill="#ecfdf5" stroke="#10b981" stroke-width="1"/><text x="470" y="328" text-anchor="middle" fill="#10b981" font-size="12" font-weight="700" font-family="system-ui,sans-serif">✅ 合并输出</text></g>
<!-- Annotation -->
<text x="340" y="352" text-anchor="middle" fill="#9ca3af" font-size="10" font-family="system-ui,sans-serif">DAG 本身无环；回路是编排器层面的"重跑子 DAG"，不是 DAG 边</text></svg>
<figcaption class="image-caption">图 1：DAG 波次调度——每层无依赖的节点并发执行。AI 步骤（蓝/红色）和确定性步骤（黄/绿色）在同一个图里，走同一套调度逻辑。</figcaption>
</figure>

### 2.3 确定性分层，不是非黑即白

不是所有步骤都需要保证确定性。把步骤分三层：

| 层级 | 特征 | 例子 | 能不能缓存 |
|------|------|------|-----------|
| 纯函数 | 同样输入永远同样输出，无副作用 | `set`、`log`、变量赋值 | ✅ 永远可以 |
| 有副作用 | 结果依赖外部状态，但可重现 | `shell`、`http` 请求、文件操作 | ⚠️ 条件可缓存 |
| 概率性 | 同样输入可能不同输出 | `ai` 步骤 | ❌ 每次都重跑 |

关键在于 **taint 传播**：一个步骤如果消费了 AI 步骤的输出，它自动被标记为非确定性。这意味着排错时你不用猜——taint 之前的步骤全从缓存拿，只看 AI 那一步的输出。

seneschal 的做法：每个步骤产出带一个 `Nondeterministic` 布尔位。`ai`/`ai_decide` 步骤自动标为 `true`。下游步骤消费了这些变量，引擎把 taint 传过去。重放执行时，引擎跳过所有 `Nondeterministic == false` 的步骤，只重跑 AI 及其下游。省时间，更关键是——保证同一条路径可以精确复现。

**编排器不需要理解 AI 说了什么。它只管传变量、比 taint、排队重试。** 这就是编排器和 Agent 的分界线。

---

## 3. 三原语：pipeline、parallel、agent()

编排器的 API 不需要花哨。三个原语够用。下面用 Claude Code Workflow 的语法示意——但原语本身跟具体实现无关，任何编排器都逃不开这三个。

### 3.1 pipeline — 串联

A 的输出是 B 的输入。典型的代码生成流水线：

```javascript
// Claude Code Workflow — pipeline 示例
pipeline([
  { name: "parse_requirements", prompt: "解析需求文档，输出结构化 spec" },
  { name: "generate_code", prompt: "根据 spec 生成 Python 代码" },
  { name: "generate_tests", prompt: "根据 spec + code 生成单元测试" },
  { name: "run_tests", prompt: "运行 pytest，输出覆盖率报告" },
])
```

每一步的产出进变量系统，下一步通过变量名读取。第二步看不到 spec，第四步拿不到覆盖率数据——不是靠 prompt 约束，是编排器在变量层保证了数据流。

**适用场景**：步骤间有严格依赖——代码在 spec 之后，测试在代码之后，审查在测试之后。

**反模式**：把没有依赖的步骤串起来。"先生成英文版，再生成中文版"——两个互不依赖，pipeline 白白多等一倍时间。

### 3.2 parallel — 并联

A、B、C 互不依赖，同时跑。三个独立审查者同时审同一段代码：

```javascript
// Claude Code Workflow — parallel 示例
const reviews = await parallel([
  () => agent("从类型安全角度审查这段代码", { schema: REVIEW_SCHEMA }),
  () => agent("从性能角度审查这段代码", { schema: REVIEW_SCHEMA }),
  () => agent("从可维护性角度审查这段代码", { schema: REVIEW_SCHEMA }),
])
// reviews = [类型审查结果, 性能审查结果, 可维护性审查结果]
// 三个审查者同时跑，各看各的维度，互不干扰
```

三个审查同时跑，各看各的维度。总耗时 = 最慢的那个审查者，不是三者之和。

**适用场景**：任务间互不依赖——多维度审查、多语言生成、批量独立任务。

**反模式**：把有依赖的放进去。审查者 B 需要审查者 A 的输出？那不是 parallel，是 pipeline 里套 parallel。

### 3.3 agent() — 节点

一个 Agent 是一个可替换的执行单元。输入是变量，输出进变量系统：

```javascript
// Claude Code Workflow — agent() 节点
const code_result = await agent("根据以下 spec 生成 Python 代码:\n" + spec, {
  schema: { code: "string", explanation: "string" }
})
// code_result.code → 变量系统
// code_result.explanation → 变量系统
// 下一步 agent("写测试") 可以读取 code_result.code
```

`agent()` 的设计把 AI 变成了流程里的一个"函数调用"——编排器不管函数里面怎么调模型，只管三件事：传参、等返回值、写进变量。和 `pipeline` 与 `parallel` 不同——那两个管的是"步骤之间的拓扑关系"；`agent()` 管的是"一个节点内部的执行"。

**选型速查**：

| 你要什么 | 用什么 |
|----------|--------|
| 步骤有先后依赖 | pipeline |
| 步骤互不依赖，可以同时跑 | parallel |
| 一个节点是 AI 步骤 | agent() |
| 三个审一个 | parallel([agent(), agent(), agent()]) |
| 审完打回重写 | pipeline + condition 循环 |

### 3.4 嵌套编排：组合拳

真实场景很少只用一种。最常见的是 pipeline 外层套 parallel 内层：

```javascript
pipeline([
  agent("根据需求生成 spec"),
  // 第二步：三路并行——三个 Agent 各写一版代码
  parallel([
    agent("基于 spec 写保守方案"),
    agent("基于 spec 写激进方案"),
    agent("基于 spec 写折中方案"),
  ]),
  // 第三步：评审选最优
  agent("对比三个方案，选最优，写最终版本"),
  // 第四步：并行多维审查
  parallel([
    agent("从类型安全角度审查", { output: "z" }),
    agent("从性能角度审查", { output: "z" }),
  ]),
  // 第五步：汇总修复
  agent("合并所有审查意见，修复代码"),
])
```

这个流程在 Claude Code 的 Workflow 引擎里就是一段 JS。换成 seneschal，就是一份 YAML。**原语一样，实现不同。** 编排器选型考量的不是语法，是这些原语底下的调度模型靠不靠得住。

---

## 4. 对抗验证：Generator + Reviewer

单 Agent 审自己的代码 = "请确认你没犯错" = 没用。

### 4.1 模式

```
Generator（写代码）
    │
    ▼
Reviewer（挑刺）─── 通过？ ─── ✅ 输出
    │                    │
    └── 不通过，带意见 ──┘
```

Generator 产出 → Reviewer 挑刺 → 不通过打回 Generator → 循环直到 Reviewer 闭嘴。

三个关键设计决策：

**一：Generator 和 Reviewer 不能是同一个 Agent。** 不只是不同的 prompt，最好用不同的模型或不同的 temperature。强模型审弱模型（Claude Opus 审 Sonnet）保质量；弱模型审强模型（Sonnet 审 Opus）省成本——两个方向各有适用场景。

**二：Reviewer 必须有具体挑刺指令。** "你觉得怎么样？" → Agent 回答 "Looks good"——不是它敷衍，是你的问题太模糊。正确问法："找出三个你确定有问题的点，给出文件、行号、原因。如果一个都没找到，说 NO_ISSUES。"

**三：上限三轮。** 超过三轮说明任务本身定义太模糊，不是 Agent 的问题。这时候该拆任务，不是继续打回。

### 4.2 实现

在 Claude Code Workflow 里的实现——Generator + Reviewer 循环：

```javascript
for (let round = 0; round < 3; round++) {
  const code = await agent("根据需求生成代码。审查意见: " + (feedback || "无"), {
    phase: "Generate",
    schema: { code: "string" }
  })

  const review = await agent(
    `审查以下代码。找出三个你确定有问题的点（类型安全、异常处理、边界条件）。
    格式: ISSUE: <文件:行号> <问题描述> <严重程度>
    如果一个都没找到，输出: PASS`,
    { phase: "Review" }
  )

  if (review.includes("PASS")) {
    log("审查通过，第 " + (round + 1) + " 轮")
    break
  }

  feedback = review
  log("第 " + (round + 1) + " 轮未通过，打回重写")
}
```

### 4.3 seneschal 里的对应

编排器的条件分支是确定性能力，不是 AI 能力。seneschal 的 YAML 里，`condition` 节点做判断：

```yaml
steps:
  - id: generate
    action: ai
    prompt: "根据需求生成代码"
    output: code

  - id: review
    action: ai
    prompt: "审查代码，输出 PASS 或 REJECT + 意见"
    output: review_result

  - id: check
    action: condition
    expression: review_result contains "PASS"
    next_if_true: merge       # 通过了，合并
    next_if_false: generate   # 不通过，打回 Generator
    retry_limit: 3
```

`condition` 不是让 AI 判断"要不要重来"——是引擎根据 Reviewer 的输出字面值做分支。确定性引擎的 if/else，AI 只管"审"这一步。

**什么场景用对抗验证？** 代码生成、技术文档审稿、方案评估——输出质量标准高、结构可验证的任务。**什么时候不用？** 翻译、摘要、格式转换——标准明确、单步完成的任务，对抗验证是杀鸡用牛刀。

---

## 5. 工程参考：编排器的确定性设计

seneschal 的三层防御式分法——不是唯一的做法，但把"确定性编排"这个理念落地得比较完整。挑三个设计决策展开：

### 5.1 DAG 波次调度：Kahn 算法 + 并发波

所有步骤先建 DAG 图，Kahn 算法做拓扑排序。这一步能发现循环依赖（A 等 B、B 等 A），编译时就能报错——不用等跑到一半才发现死锁。

排好序后，所有无依赖的节点同一波并发跑。WaitGroup 等一波全部完成，计算下一波。下图是该逻辑在引擎侧的落地示意（完整实现见 `workflow/executor.go:runWaves`）：

```
buildDAGGraph(steps) → topologicalSort → runWaves:
  Wave 0: [id=A, id=B]        ← 无前置，并发
  Wave 1: [id=C]              ← 依赖 A+B，等 Wave 0 全完成
  Wave 2: [id=D, id=E, id=F]  ← 依赖 C，并发
```

### 5.2 确定性三层 + taint 传播

每个步骤产出带一个 `Nondeterministic` 位，再加上 taint 传播——这才是确定性追踪的关键，而不是简单地给 AI 步骤打标记：

| 步骤 | Nondeterministic？ | 为什么 |
|------|-------------------|--------|
| 解析 YAML 配置 | `false` | 纯解析，无外部依赖 |
| 调用 LLM 生成代码 | `true` | 同样 prompt，每次输出不同 |
| 用 AI 输出拼接 shell 命令 | `true` | 输入源是非确定的 → taint 传播 |
| 执行 shell 命令 | `false` | 命令本身是确定的脚本（但结果依赖外部状态） |

taint 传播规则：如果一个步骤的输入中包含了任何标记为 `Nondeterministic` 步骤的输出变量，它自动被标记为 `Nondeterministic`。不需要人工标注，引擎推断。

**排错时的效果**：重放一个执行记录。引擎自动跳过所有 `false` 步骤（从缓存返回结果），只重跑标记为 `true` 的步骤。你不需要"从零开始重现问题"——翻车点之前的确定性世界，全部精确复原。

### 5.3 智能重放

改了一个步骤的 YAML，重跑时引擎自动识别哪一步变了、哪些下游受影响。没变的确定性步骤直接拿缓存，完全不执行。只有被改的那一步 + taint 下游才会重跑。

一个真实场景：五步流水线，你调了第三步的 prompt。重跑只需要跑第三步（AI）+ 第四步（受 taint 影响）。第一步和第二步从缓存拿，第五步没受影响也跳过。五步流水线的重跑时间 = 两步的时间。

这三个设计决策的共同出发点：**让编排器做编排器该做的事——调度、依赖、缓存、重试。让 AI 做 AI 该做的事——在一个受控的输入输出边界里发挥智能。**

---

## 6. 设计原则

从上面所有讨论里抽三条原则。和上一篇沙箱的原则对照着看——沙箱画圈，编排铺轨。

### 6.1 确定性优先

编排器本身不该调 AI。DAG 结构、依赖解析、重试策略、条件分支——这些是引擎写死的，不是模型"觉得"的。

一个编排器如果连"第三步跑没跑"都要问模型，它不是编排器——它是另一个 Agent，而你只是把编排问题往上层挪了一层。

### 6.2 AI 后置

先搭骨架，再填 AI。设计一个编排流程时，先用纯确定性步骤跑通——shell 脚本、HTTP 调用、人工 mock 数据。确认流程本身没问题（依赖对、变量对、重试对），再把关键步骤换成 AI。

反着来——上来就让 AI 管一切——你会分不清是流程设计烂，还是 AI 输出烂。十有八九是两者一起烂，而你没法拆开排错。

### 6.3 失败有路可退

编排器要能回答三个问题，排错才不是靠猜：

- **哪一步失败了？** — 步骤级 checkpoint，每一步的输入输出都在
- **影响了哪些下游？** — taint 传播，一个失败步骤的下游全部标出来
- **重跑从哪开始？** — 智能重放，跳过没变的确定性步骤，只重跑失败链路

这三个答案缺一个，你就回到了"Agent 到底干了什么"的猜谜游戏。而猜谜游戏是编排器被设计来消灭的东西。

---

## 7. 选型指南：你的场景该上什么

| 场景 | 编排方式 | 为什么 |
|------|---------|--------|
| 单个明确任务（修 bug、写函数） | 单 Agent，不上编排 | 编排开销 > 收益；Agent + 好的 prompt 够用 |
| 多步串行（需求→代码→测试） | pipeline | 每步有依赖，输入输出要对齐 |
| 需要多视角并行（多维度审查） | parallel | 互不依赖的审查者同时跑，耗时 = 最慢那个 |
| 输出质量要求高 | pipeline + 对抗验证 | Generator→Reviewer 循环，直到通过或上限 |
| 复杂项目 | 嵌套编排 | 外层 pipeline 定阶段，内层 parallel + agent() 并发 |

还有一组反模式：

| 反模式 | 问题 | 怎么改 |
|--------|------|--------|
| 单 Agent 干全套 | 自我审查幻觉，上下文衰减 | 拆成 pipeline，至少把 Generate 和 Review 拆开 |
| 没依赖的步骤放 pipeline | 浪费时间 | 改成 parallel |
| 有依赖的步骤放 parallel | 下游拿不到上游产物 | 改回 pipeline，或 pipeline 外层 parallel 内层 |
| 对抗验证不限轮次 | 模糊任务无限循环 | 上限三轮，超了拆任务 |
| 一上来就搭 full pipeline | 过度设计 | 从单 Agent 开始，翻车了再加编排 |

和上一篇沙箱的选型指南一样：**够用且开销低优先。** 别一上来就配 pipeline + parallel + 对抗验证。从单 Agent 开始。等它翻车了，你就知道自己需要的是哪一种编排。

---

## 8. 和系列其他组件的关系

编排是 Harness 六组件中最中心的一环。它往上接沙箱，往下接状态记忆和独立评估：

| 组件 | 编排管什么 | 那个组件管什么 |
|------|----------|--------------|
| 沙箱 | 不管 → 编排只负责"怎么跑" | 沙箱管"能跑什么"——编排器在沙箱里排流程 |
| 状态记忆 | 紧耦合 → 编排输出执行状态 | 状态记忆持久化 checkpoint，编排器断点续跑 |
| 独立评估 | 单向配合 → review.md 进评估系统 | 评估系统跑在编排器外面，不参与流程，只管判分 |
| 约束恢复 | 紧耦合 → 编排里的 condition 分支 | 约束恢复是 condition 的升级版——失败后不是打回，是 rollback |

沙箱画了圈，编排铺了轨。圈 + 轨 = Agent 的安全工作空间。

---

## 9. 结语

回到开篇那个对比实验。裸 Agent 跑了四十分钟产出不能用，不是因为模型不够好——是因为没有轨道。

你给模型配了沙箱，它不会删你项目了。你给模型铺了编排轨道，它不会跑偏了。但不会删、不走偏的前提是——Agent 没忘自己在干什么。而"不忘"这件事，和"不删""不走偏"一样——不靠劝，靠结构。

---

*感谢阅读。*
