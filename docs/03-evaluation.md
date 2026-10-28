# 实际评估记录

## 当前结论

2026-10-28（Asia/Shanghai），本轮针对实际Live失败完成修复：**离线142项通过，随后Live14项通过**。服务为 `api.deepseek.com`，实际返回模型 `deepseek-flash`，非思考模式，服务端strict关闭，本地证据校验保留。预算仍为8轮/10次工具调用。

离线证据见 [固定归档](../examples/test_runs/20261028T114623Z_b7635fca/results.txt)：142 passed, 14 skipped；此处14项跳过随后单独执行Live，不能将离线跳过算作通过。Live证据见 [固定归档](../examples/test_runs/20261028T114641Z_ace5d168/results.txt)：14 passed in 96.89s，退出0。两次顺序执行，共156项通过。

Live批次 `20261028T114641Z_ace5d168` 产生15条Trace（动态对照使用两次运行），共57次模型请求、62次工具尝试、61次实际执行；其中执行包括被校验器拒绝的submit_answer，不能将61理解为成功业务工具数。完整调用ID、参数、错误和文件哈希见 [机器摘要](../examples/test_runs/20261028T114641Z_ace5d168/live_summary.json)。Python及依赖版本以各Trace的versions为准。

## 修复前后的实际对照

用户首次全量测试为 **122 passed / 5 failed**，其中113项为离线；原输出保留于 [原始终端记录](../examples/repair_baseline/original_full_test_output.txt)。旧C06B虽被原测试判通过，实际没有触发工具，属于验收漏检。本轮开始前保存64个旧Live文件的SHA256，结束后核验全部未变，见 [基线清单](../examples/repair_baseline/manifest.json)。没有覆盖旧Trace或筛选不利记录。

| 项目 | 修复前原因 | 实现修改 | 本轮实际结果及调用 |
|---|---|---|---|
| C04 | 正式员工重复进入conditions，删除又被旧解释锁死 | contracts规范化scope条件；仅保护用户来源约束 | COMPLETED，3轮：search → 同批read D03/D04 → submit；[新Trace](../examples/generated/live/C04_67df1e912a35474c9e996b65764f9a9e/trace.json) |
| C05 | 试用期员工重复为conditions；错误范围可能混入终稿 | 同上；保留证据适用范围校验及恢复反馈 | COMPLETED，4轮：search → 同批read D04/D03 → submit被拒 → 修正submit；[新Trace](../examples/generated/live/C05_bb4257f0dc8942d7b389a8c54bd9540f/trace.json) |
| T04 | 模型推断的歧义及错误起算事件被锁定，并非30/30仍冲突 | 区分用户硬约束/模型推断，允许有原因纠正；说明字段语义 | COMPLETED，3轮：search → 同批read D01/D02 → submit，均为30且conflicts为空；[新Trace](../examples/generated/live/T04_df30d7b2ac8f4c86bce59eb48eb42186/trace.json) |
| T06 | 每周误写成reference_event且无法修正 | 周期/事件分离及安全规范化；允许推断纠错 | COMPLETED，4轮：search实际故障 → search成功 → read D03 → submit；[新Trace](../examples/generated/live/T06_666e7a8bbada4c39b408787c974fda31/trace.json) |
| 动态对照 | week/一周被拒；比较函数误取未执行的检索 | 合法别名规范化；只比较实际执行且后续轮次的动作 | 两次均COMPLETED；正常命中后read D03，注入故障后重新search；[新对照](../examples/generated/live/dynamic_fault_e15e91aff5fa483f95df445553d820b2/comparison.json) |
| C06B假通过 | 只断言最终状态，没有执行到持续故障 | Live全局路径断言检查executed及实际INJECTED_FAILURE | FAILED，5轮：4次实际故障search → 模型submit FAILED；[新Trace](../examples/generated/live/C06B_c1ac1a6fe7ed4c56b8de99fe15763116/trace.json) |

本轮C04/T04/T06主要通过明确字段语义避免了原错误，不把它们描述成全部经历原错误后的现场恢复。旧参数纠错通路由29项新增离线回归覆盖，其中6项直接取自原始Live参数，运行模式明确为Mock。

## 真实动态决策证据

正常分支：[Trace](../examples/generated/live/dynamic_normal_16350d6da87942c7a2f050629409bea9/trace.json) 中真实检索 `call_00_yjbPLrfOvuDimh2WMAnV1134` 成功，下一轮选择 `call_00_L2nIoitNIvht6l4pq6do2398`，动作read_doc(D03)。

故障分支：[Trace](../examples/generated/live/dynamic_fault_e15e91aff5fa483f95df445553d820b2/trace.json) 中真实检索 `call_00_m1yLyj3bnxC73tZ3pamv9303` 返回INJECTED_FAILURE，下一轮选择 `call_00_JOLBBBhSUkHvHa4jKwav2646`，动作search_docs重试。两次输入和请求模型一致；没有预填动作或依赖Mock。一次随机对照支持本次观测，不能作为严格因果证明或未来稳定性保证。

## 仍然保留的失败提交

- C05先提交了不适用的正式员工规则，证据校验拒绝；模型下一轮移除不适用声明才通过。没有放宽试用期范围要求。
- C03一次将ambiguous=true与INSUFFICIENT_EVIDENCE混用被拒，随后修正。
- T03一次把revision_reason写为null，Schema拒绝，随后改为合法提交。
- C06/C06B/T06/动态故障分支均保存实际工具故障；全部中间错误与下一动作可在新Trace中查到。

## 已实际执行

在项目根目录使用项目虚拟环境：

```powershell
.venv/Scripts/python -X utf8 -m scripts.run_checks
.venv/Scripts/python -X utf8 -m scripts.generate_examples
.venv/Scripts/python -X utf8 -m src.main --help
.venv/Scripts/python -m pip check
.venv/Scripts/python -m compileall -q src scripts tests
.venv/Scripts/python -X utf8 -m scripts.run_checks --live
```

首次实现曾运行离线示例、帮助、依赖和编译检查；首次Live配置检查因缺凭证阻塞，历史文件 [live_validation_status.json](../examples/live_validation_status.json) 仅表示当时状态。本轮已按上面的归档顺序实际执行离线与Live测试。最新结果文件是便捷入口，完整历史记录保存在examples/test_runs/，每次运行都先归档，不删除失败报告。

## Mock 场景实测

下列均来自程序执行预设响应，证明执行器及校验逻辑，**不是模型决策证据**。每组同目录包含对应 `_input.json`、`_output.json`、`_trace.json`。完整机器可读索引见 [manifest.json](../examples/generated/mock/manifest.json)。

| 用例 | 预期 / 实测 | 证据 |
|---|---|---|
| C01 | COMPLETED / COMPLETED；D03，MAX 2天/每周 | [normal_trace](../examples/generated/mock/normal_trace.json) |
| C02 | NEEDS_CLARIFICATION / 同；双份引用与冲突 | [conflict_trace](../examples/generated/mock/conflict_trace.json) |
| C03 | INSUFFICIENT_EVIDENCE / 同；无确定性企业事实 | [missing_trace](../examples/generated/mock/missing_trace.json) |
| C04 | COMPLETED / 同；明确正式员工的相似表述 | [similar_trace](../examples/generated/mock/similar_trace.json) |
| C05 | COMPLETED / 同；仅使用 D04 试用期规则 | [context_trace](../examples/generated/mock/context_trace.json) |
| C06 一次故障 | COMPLETED / 同；失败后预设重试成功 | [failure_trace](../examples/generated/mock/failure_trace.json) |
| C06 持续故障 | FAILED / 同；如实记录失败 | [always_trace](../examples/generated/mock/always_trace.json) |

Mock 路径差异来自显式脚本设计，不证明模型会随 observation 改变行为。相似表述回放直接搜索标准主题，也不能证明模型自主查询改写。

## 自动化覆盖

- 工具层：26项初始测试通过后才推进执行器；检索明确命中/无关为空、未知ID、读取隔离、故障注入均受测。
- 事实/覆盖：未读引用、假引文、附加编造声明、忽略自由文本、范围/日期/周期/参考事件/条件、MIN与MAX、额度与审批混淆、多问题漏答、多主题分别覆盖、未知或未指明员工类型不得默认为正式员工。
- 冲突：不同生效区间、范围互斥、日期不产生优先级、显式及部分覆盖、bounds区间、条件不明、漏读第二份制度的保护。
- 执行器：工具回传协议、多调用混合提交、预算内最后提交、超预算跳过及完整observation、无效提交修正、普通文本、重复ID、无进展和API异常。
- 兼容性：使用实际 OpenAI SDK 配合 httpx.MockTransport，验证参数、max_retries=0、服务拒绝或忽略strict、异常多调用、空choices；这些是模拟传输测试，不是服务商Live兼容认证。
- T01—T06：数值变异、冲突消失、删除制度、工具故障和正文/元数据不同步均有离线验证。Mock新声明基于测试夹具构造，只验证证据边界，不证明真实模型适应变异。
- 注入：文档恶意指令保持为tool数据，不能增加工具权限；真实模型抗注入行为未验证。

## Live复跑方式

配置 `.env` 后执行 `python -m scripts.run_checks --live`，或 `python -m pytest -q --run-live tests/test_live.py`。会实际调用模型并产生费用，保存真实模型输入、输出、Trace及语料快照到 `examples/generated/live/`。测试可以失败，须保留失败证据。

共14项：七个业务场景变体、六个语料变异测试、一个成对动态决策对照。对照以相同问题和请求模型，比较正常结果与一次工具失败后的真实后续工具动作及参数，报告引用具体调用ID；仅答案变化不算通过。无所需差异则明确失败，不筛选/手写结果来制造证明。

## 已知限制与未通过项目

本轮无失败测试，但存在模型随机波动；不同供应商、模型版本或语料的结果不能由本次推断。服务端strict关闭，不宣称强制Schema兼容认证。规范化只处理明确列出的同义值，7天不自动等同于日历周；真正不同的月/周、员工类别及起算事件不能被规范化抹去。硬约束提取面向有限受控表达，不能穷尽任意自然语言、复杂否定或跨主题条件归属；额外未知条件仍可能需要澄清。引用/数值核验不等于通用语义蕴含证明；真实模型抗注入对抗尚未单独Live验收。

上述评估完成时尚未建立Git仓库或执行提交、推送。后续正式发布目标为 [Filan616/EvidenceAgent](https://github.com/Filan616/EvidenceAgent)，实际提交与推送结果以远端引用及最终交付记录为准。
