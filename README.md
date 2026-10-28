# EvidenceAgent

**基于 ReAct 与可验证证据的企业知识问答 Agent**

EvidenceAgent 是一个使用 Python CLI 运行的企业制度问答原型。它通过真实大模型的原生 Tool Calling 自主选择检索、读取文档、补充查证或提交答案；Python 执行工具并反馈实际结果，独立校验器检查引用、事实、制度冲突和问题覆盖，最终保存可审计的执行轨迹（Trace）。

本项目使用**自建合成企业制度**，不接入真实企业内部系统，也不使用互联网搜索补充企业事实。业务场景与验证结果均基于受控测试语料。

## 项目亮点

- **真实模型驱动的 ReAct**：模型根据 `search_docs`、`read_doc` 返回的 observation 决定后续动作，而非由固定业务分支预设工具链。
- **证据可信性与问题覆盖校验**：基于本次读取的原文生成受控 Claims，核对引用、数值、单位、适用范围、必要条件及问题覆盖，避免“引用真实但答非所问”。
- **多制度冲突查证**：综合规则组、生效区间、适用范围、条款语义和明确覆盖关系；缺少依据时报告冲突、请求澄清，不因版本较新就擅自选择。
- **错误反馈与修正**：无效提交返回字段级错误，模型可在保留用户明确约束的前提下纠正自身推断；工具错误也会作为 observation 反馈给模型。
- **可追踪、可复测**：保留真实调用 ID、参数、工具结果、修正过程和终止原因，提供离线测试、Live 测试、故障注入及语料变异对照。

## 评审速览

> **2026-10-28 实测批次**：离线 **142 passed**（另有 14 项 Live 用例在离线运行中跳过）；随后单独执行 Live **14 passed**。两批合计 **156 项通过**，并生成 **15 条真实 Live Trace**。本次运行使用 `api.deepseek.com`、实际返回模型 `deepseek-flash`（非思考模式）。这些数据只代表所述测试批次，不承诺不同运行或其他模型得到完全相同的结果。

| 评审重点 | 实际证据 |
| --- | --- |
| 离线测试结果 | [离线测试归档](examples/test_runs/20261028T114623Z_b7635fca/results.txt) |
| Live 测试结果 | [Live 测试归档](examples/test_runs/20261028T114641Z_ace5d168/results.txt) |
| Live 全量调用摘要、文件哈希 | [live_summary.json](examples/test_runs/20261028T114641Z_ace5d168/live_summary.json) |
| 正常检索后的模型动作 | [正常分支 Trace](examples/generated/live/dynamic_normal_16350d6da87942c7a2f050629409bea9/trace.json) |
| 检索故障后的模型动作 | [故障分支 Trace](examples/generated/live/dynamic_fault_e15e91aff5fa483f95df445553d820b2/trace.json) |
| 校验拒绝后模型修正 | [C05 Trace](examples/generated/live/C05_bb4257f0dc8942d7b389a8c54bd9540f/trace.json) |
| 持续故障的真实终止 | [C06B Trace](examples/generated/live/C06B_c1ac1a6fe7ed4c56b8de99fe15763116/trace.json) |
| 六项业务验收及修复前后对照 | [完整评估报告](docs/03-evaluation.md) |

**如何阅读验收结果？** `14 passed` 表示 14 项 Live *测试断言*通过；其中持续故障用例的 Agent 最终业务状态为 `FAILED`，这是该用例预期的诚实终止，并非测试执行失败。Live 批次记录了 57 次模型请求、62 次工具尝试、61 次实际执行；“实际执行”包括被校验器拒绝的 `submit_answer`，**不等于 61 次成功业务工具调用**。

## 系统架构

```text
用户问题 + 可选对话历史 + 制度适用日期
                     │
                     ▼
          LLM（原生 Tool Calling）
                     │ 选择动作及参数
           ┌─────────┼──────────────┐
           ▼         ▼              ▼
      search_docs  read_doc     submit_answer
           │         │              │
           └────┬────┘              ▼
                │           Claims / 冲突 / 问题覆盖校验
           真实工具结果              │
                │              ┌────┴────┐
                └──────────►   通过      拒绝并反馈
                 模型观察       │          │
                 后继续决策     ▼          └──► LLM 修正
                           最终答案 + 引用 + 状态
                                      │
                                      ▼
                           JSON 输出 + 审计 Trace
```

模型只可选择 `search_docs`、`read_doc`、`submit_answer` 三类动作。执行器负责参数及协议校验、预算、故障封装、记录和证据保护；**不会根据关键词替模型自动选择下一步业务动作**。`submit_answer` 是终止动作，但必须经过校验才能以有效状态结束。

### 关键设计取舍

| 设计 | 选择与原因 |
| --- | --- |
| Agent 实现 | 原生 Python ReAct + Chat Completions Tool Calling：便于审计真实模型动作，不引入额外工作流框架。 |
| 文档检索 | 本地中英文词条与中文字符 n-gram TF-IDF：满足小规模合成语料的候选发现与可复现需求。 |
| 证据读取 | 检索与原文读取分离：`search_docs` 的摘要不能替代成功 `read_doc` 得到的引用证据。 |
| 答案生成 | 结构化 `claims` 经校验后由程序渲染答案，不直接放行含未验证事实的自由文本。 |
| 冲突处理 | 仅在同规则、适用范围与时间重叠、语义互斥且无明确优先关系时认定冲突。 |
| 修正机制 | 用户明确提出的约束不可随意更改；模型自行推断的错误字段可经说明后修正。 |
| 执行保护 | 默认最多 8 轮模型请求、10 次工具调用；预算耗尽且尚未有效终止时返回 `INCOMPLETE`，最后一次额度内的有效提交仍可完成。 |

完整工具 Schema 以 [`src/schemas.py`](src/schemas.py) 为准，架构与校验细节见 [`docs/02-solution.md`](docs/02-solution.md)。三个工具的调用参数包含 `question_contract`；`submit_answer` 使用结构化 `claims`。字段涵盖规则主题、适用人群、生效时间、周期、参考事件、条件和约束类型。最终提交按状态执行相应校验，其中 `COMPLETED` 必须满足完整问题覆盖要求；澄清、证据不足和失败状态不要求已经完整回答问题。

## 快速开始

### 环境要求

- Python 3.11+（本轮测试环境为 Python 3.13.14）
- Python 依赖见 [`requirements.txt`](requirements.txt)
- 真实模型模式需要可用的、支持 Tool Calling 的 API 凭证；离线 Mock 模式不需要凭证

**Windows PowerShell**（在仓库根目录）：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**Linux / macOS**：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 配置真实模型

将 `.env.example` 复制为 `.env`，并填写自己的凭证。以下为本轮已验证的 DeepSeek **配置格式**（示例值不含真实密钥）：

```dotenv
OPENAI_API_KEY=your_deepseek_api_key
OPENAI_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-flash
MODEL_REASONING_EFFORT=none
STRICT_TOOLS=false
DISABLE_PARALLEL=false
MAX_STEPS=8
MAX_TOOL_CALLS=10
```

`OPENAI_API_KEY` 是本项目兼容客户端使用的配置变量名，可存放 DeepSeek 凭证，不表示调用 OpenAI 服务。当前 DeepSeek 运行配置未启用服务端 Strict Schema；**本地工具参数 Schema 与业务证据校验仍然生效**。不同 API 服务可能有不同参数支持情况，请按实际服务配置；本项目的 Live 结果不构成跨服务商兼容性认证。

> **安全提示**：不要提交 `.env`、密钥、认证信息或真实企业敏感资料；公开 Live Trace 前需检查其内容。仓库只使用合成制度数据。

### 运行示例

Windows PowerShell：

```powershell
# 不使用模型 API：显式 Mock 回放（仅验证执行流程）
.\.venv\Scripts\python.exe -X utf8 -m src.main --mock --question "正式员工一周最多远程办公几天？" --as-of 2026-10-28

# 真实模型：正常知识问答
.\.venv\Scripts\python.exe -X utf8 -m src.main --question "正式员工一周最多远程办公几天？" --as-of 2026-10-28

# 真实模型：冲突制度查证
.\.venv\Scripts\python.exe -X utf8 -m src.main --question "差旅费用最晚什么时候报销？" --as-of 2026-10-28

# 真实模型：一次性检索故障注入
.\.venv\Scripts\python.exe -X utf8 -m src.main --question "正式员工能否远程办公？" --as-of 2026-10-28 --fault search_docs:once

# 真实模型：包含历史对话的追问
.\.venv\Scripts\python.exe -X utf8 -m src.main --question "那试用期员工呢？" --history-file examples/context_history.json --as-of 2026-10-28
```

Linux/macOS 使用已激活环境的 `python -m src.main ...` 即可。`-X utf8` 用于避免 Windows 控制台/日志的中文编码问题，输出 JSON 使用 UTF-8。默认在 `examples/generated/live/` 或 `examples/generated/mock/` 保存本次输入、输出和 Trace；终端打印状态、回答摘要及文件位置。

其他常用参数：`--documents-file` 指定合成语料副本；`--trace-file`、`--output-file` 指定输出位置；`--max-steps`、`--max-tool-calls` 覆盖默认预算；`--mock-script` 选择显式 Mock 回放脚本；`--as-of` 指定制度适用日期。完整可用参数请运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m src.main --help
```

Mock 默认使用预设正常脚本，不会仅根据用户问题自动推断并切换 Mock 场景；更多脚本与对应输入见 [`examples/mock_scripts/`](examples/mock_scripts/) 和 [`examples/cases.json`](examples/cases.json)。

### 任务状态与退出码

| 任务状态 | 含义 | CLI 退出码 |
| --- | --- | ---: |
| `COMPLETED` | 问题已由有效证据充分回答 | 0 |
| `NEEDS_CLARIFICATION` | 制度冲突或适用条件不明，需用户确认 | 0 |
| `INSUFFICIENT_EVIDENCE` | 缺少支持结论的资料，不编造答案 | 0 |
| `FAILED` | 工具或模型故障导致任务无法完成 | 1 |
| `INCOMPLETE` | 达到调用预算或无进展等未完成条件 | 1 |

无效输入或配置错误返回退出码 `2`；结果/Trace 保存失败返回非零码，并不会报告保存成功。退出码 `0` 表示已得到明确且有效的**业务状态**，不保证状态一定为 `COMPLETED`。

## 业务验收与实测证据

全部六类业务验收、六项语料变异（T01–T06）及成对动态决策对照均纳入本轮 Live 验证；原始输入、结果和完整 Trace 以归档为准。

| 场景 | 预期行为及本轮验证重点 |
| --- | --- |
| **C01 · 明确答案** | 读取 D03，依据规则回答正式员工每周最多远程办公 2 天。 |
| **C02 · 制度冲突** | D01 为 30 天、D02 为 15 天；列明冲突与引用，不擅自依据版本日期选择。 |
| **C03 · 资料外问题** | 对语料没有证据支持的问题返回 `INSUFFICIENT_EVIDENCE`，不虚构企业事实。 |
| **C04 · 相似问题** | 对“在家上班”等改写表述正确定位相关制度；不以未发生的查询改写冒充 Agent 动作。 |
| **C05 · 上下文追问** | 根据历史理解试用期远程办公问题；错误引用正式员工规则时拒绝并允许修正。 |
| **C06 · 工具故障** | 一次性故障后合理恢复；持续故障实际发生时返回明确失败，而非虚报成功。 |

### 真实模型的动态决策对照

两次运行使用相同问题与请求模型，分别采用正常检索和一次性故障注入；首轮查询文本和 `top_k` 由模型自主选择，也存在差异。对应 observation 和后续动作来自真实执行与 `tool_calls`：

| 分支 | 已执行的工具 observation | 模型下一轮实际动作 |
| --- | --- | --- |
| 正常 | `search_docs` 返回成功结果 | `read_doc(D03)` |
| 故障 | `search_docs` 返回 `INJECTED_FAILURE` | 再次调用 `search_docs` |

- [正常分支完整 Trace](examples/generated/live/dynamic_normal_16350d6da87942c7a2f050629409bea9/trace.json)
- [故障分支完整 Trace](examples/generated/live/dynamic_fault_e15e91aff5fa483f95df445553d820b2/trace.json)
- [机器可读对照记录](examples/generated/live/dynamic_fault_e15e91aff5fa483f95df445553d820b2/comparison.json)

这是一组**真实模型行为证据**，不同于 Mock 预设路径；单组成对实验不等于严格因果证明，也不保证未来每次都采取相同动作。

### 校验拒绝与修复证据

- [C05：不适用声明被拒，随后修正成功](examples/generated/live/C05_bb4257f0dc8942d7b389a8c54bd9540f/trace.json)
- [T04：冲突消除后完成回答](examples/generated/live/T04_df30d7b2ac8f4c86bce59eb48eb42186/trace.json)
- [T06：一次工具故障后成功继续](examples/generated/live/T06_666e7a8bbada4c39b408787c974fda31/trace.json)
- [C06B：持续检索故障实际发生，诚实结束为 `FAILED`](examples/generated/live/C06B_c1ac1a6fe7ed4c56b8de99fe15763116/trace.json)

首次 Live 中曾出现 5 项失败及一处持续故障测试假通过，随后根据原始 Trace 修复字段规范化、模型推断修订与执行路径断言。原始 Live Trace 仍保留在 [`examples/generated/live/`](examples/generated/live/)，原始终端输出及旧文件哈希清单保存在 [`examples/repair_baseline/`](examples/repair_baseline/)，详细对比见 [`docs/03-evaluation.md`](docs/03-evaluation.md)。

## 测试与复现

**Windows PowerShell**：

```powershell
# 离线检查：不调用真实模型，输出会归档
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_checks

# 生成七组明确标记为 Mock 的输入、输出和 Trace
.\.venv\Scripts\python.exe -X utf8 -m scripts.generate_examples

# 完整 Live 验收：需要 .env 中配置有效模型凭证；会产生 API 费用
.\.venv\Scripts\python.exe -X utf8 -m scripts.run_checks --live

# 直接运行 pytest
.\.venv\Scripts\python.exe -X utf8 -m pytest -q

# 工程检查
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q src scripts tests
```

Live 测试也可通过 `python -m pytest -q --run-live tests/test_live.py` 执行。`scripts.run_checks` 会按批次归档测试报告；直接运行 pytest 仍会生成独立 Live Trace，但不会自动归档终端测试报告。`scripts.generate_examples` 使用固定文件名，会覆盖已有 Mock 示例。离线跳过的 Live 用例不计为离线通过，Mock 也不能证明真实 LLM 的动态决策。

本轮证据归档：

- [离线归档：142 passed、14 skipped](examples/test_runs/20261028T114623Z_b7635fca/results.txt)
- [Live 归档：14 passed，96.89 秒](examples/test_runs/20261028T114641Z_ace5d168/results.txt)
- [Live 调用统计及文件哈希](examples/test_runs/20261028T114641Z_ace5d168/live_summary.json)
- [Mock 场景执行索引](examples/generated/mock/manifest.json)

## 项目结构

```text
EvidenceAgent/
├── README.md
├── requirements.txt
├── .env.example
├── src/
│   ├── main.py                # CLI 入口
│   ├── agent.py               # ReAct 执行与预算管理
│   ├── llm_client.py          # Live / Mock 模型适配
│   ├── schemas.py             # Tool Calling 与数据 Schema
│   ├── contracts.py           # 字段规范化与语义错误反馈
│   ├── rules.py               # 规则加载、约束及冲突语义
│   ├── tools.py               # 检索、读取与故障注入
│   ├── retriever.py           # 本地检索
│   ├── evidence_validator.py  # 证据与 Claims 校验
│   ├── coverage.py            # 问题覆盖校验
│   ├── evaluation.py          # Live 执行路径与动态对照评估
│   └── trace.py               # 可审计执行记录
├── data/
│   └── documents.json        # 七篇合成制度及规则元数据
├── scripts/
│   ├── run_checks.py          # 测试归档入口
│   └── generate_examples.py   # Mock 样例生成
├── tests/                     # 工具、校验、协议、Live 测试
├── examples/
│   ├── cases.json
│   ├── context_history.json
│   ├── mock_scripts/
│   ├── generated/mock/
│   ├── generated/live/
│   ├── test_runs/
│   └── repair_baseline/
└── docs/
    ├── 01-requirements.md
    ├── 02-solution.md
    ├── 03-evaluation.md
    ├── 04-ai-usage.md
    └── 05-retrospective.md
```

目录展示的是主要模块，完整文件以仓库实际内容为准。运行产生的 Trace 可能包含多个批次和更详细的配置摘要。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [01 · 需求与成功标准](docs/01-requirements.md) | 目标用户、输入输出、业务边界与六类验收场景 |
| [02 · 方案与技术取舍](docs/02-solution.md) | ReAct 过程、工具 Schema、冲突规则、受控 Claims 和执行保护 |
| [03 · 真实效果评估](docs/03-evaluation.md) | 离线/Live 结果、真实 Trace、失败修复对照及已知限制 |
| [04 · AI 辅助与个人贡献](docs/04-ai-usage.md) | Codex 参与范围、个人技术决策与核验边界的如实披露 |
| [05 · 工程复盘](docs/05-retrospective.md) | 工程难点、失败根因、修复验证与技术收获 |

## 已知限制与安全边界

1. **受控知识域**：当前使用七篇合成制度；结构化规则与 Claims 校验不能推广为任意自然语言事实的完整语义蕴含证明。
2. **语言表达与规则覆盖有限**：复杂否定、多主题条件归属、未知员工范围等情况可能需要进一步澄清；不会把不确定信息强行包装为确定答案。
3. **模型非确定性**：本轮全部测试通过不代表后续每次运行都通过；真实模型版本、配置或语料变化会影响结果。
4. **模型兼容范围**：本轮验证来自 DeepSeek 非思考模式，服务端 strict 和其他提供商尚未验证。当前客户端不支持思考模式的多轮协议，`MODEL_REASONING_EFFORT` 仅接受留空或 `none`，其他非空值会报配置错误。
5. **安全性边界**：文档内容作为不可信工具数据处理，工具权限受到限制；已有离线提示注入测试，但不声称完成真实模型对抗性注入认证。
6. **运行与保存边界**：模型步数和工具次数受预算限制；文件写入失败会明确报错，多文件保存不保证事务性。

**项目定位**：EvidenceAgent 是一个具备真实模型动态决策、受控证据可信性验证、错误修正和可审计轨迹的企业知识问答工程原型，不是可直接部署到真实企业内部系统的生产级服务。
