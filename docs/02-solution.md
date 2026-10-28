# 实现方案与接口

## 执行流程

CLI 加载配置、历史和语料快照 → 模型原生工具调用 → 本地参数及问题解释校验 → 执行白名单工具 → tool observation 回传 → 模型继续决策 → submit_answer 校验并渲染 → 保存输入、输出与 Trace。

`src/agent.py` 只执行服务返回的工具动作。Live 和 ScriptedClient 共享执行器，后者仅回放 JSON 中显式预设的响应，不根据问题关键词生成动作。Mock 默认脚本是正式员工正常场景；其他问题需显式选择相应脚本，不存在通用离线智能问答能力。

## 数据及检索

`data/documents.json` 包含 `rule_groups` 和 `documents`。前者区分 functional（同条件下唯一制度规定）与 bounds（可叠加约束）；后者包含正文及条款数组。规则记录范围、生效区间、operator、constraint_type、值、单位、参考事件、周期、必要条件、显式 supersedes、完整 evidence 及可回答问题类型 facets。

有限员工分类为 regular、probation、all_employees。时间左闭右开，版本日期不产生覆盖关系。加载验证原文、数值模板、文本必要条件、日期、范围、条款引用和覆盖环。数值渲染仅支持当前远程额度及报销截止语料，不宣称支持任意企业规则语言。

冲突比较先检查规则组、范围交集、有效时间及显式覆盖；单位、周期、参考事件或条件不同且无法确定关系时标为 uncertain。functional 的唯一规定不一致构成冲突；bounds 计算允许值区间是否相交。不同 MAX 在 bounds 下可相容，不能因数值不同直接判冲突。部分范围被覆盖时，数值声明可缩小到仍有效的范围；摘录型文本不允许仅修改元数据来改变原文主语。

检索为中英文词条/中文二元与三元组、平滑 IDF、对数 TF 和余弦评分，默认阈值 **0.08**，top_k=5（1—10）。阈值由本合成语料的明确命中及无关负例检验，见 test_retriever；它不是外部语料校准结果，也不能保证消除所有低相关候选。未知词计入查询范数，避免只凭少量共享字符给出虚高分。搜索不扩充同义词、不负责查询改写。

## 严格工具契约

实际 Schema 由 `src/schemas.py` 生成；所有对象拒绝额外属性，必填字段完整，可空字段明确允许 null。本地始终使用 jsonschema 校验。依赖范围见 requirements.txt，实际安装版本写入每条 Trace。

- search_docs：query、top_k、reason、question_contract，返回摘要与真实评分。
- read_doc：doc_id、reason、question_contract，返回完整文档及规则；未知 ID 为 NOT_FOUND。
- submit_answer：README 原有业务字段，加 claims 和 question_contract；必须单独调用。
- 首次工具调用提供 question_contract；后续无修订时为 null。实际示例见 examples/mock_scripts/*.json，其中响应是明确预设的 Mock 输入，不能当作运行证据。

question_contract 每项 requirement 包含 rule_group、scope、as_of、period、reference_event、conditions、facet、constraint_type，以及顶层 ambiguous、clarification、revision_reason。本地从原始用户/历史及运行日期提取受保护约束，模型不能重写其来源。仅保护有输入依据的约束；模型推断的错误范围、条件、参考事件或ambiguous可以写revision_reason后修正，再重新校验用户约束与已读证据。仅修改审计说明不算语义修订，不再因旧解释文本不同而锁死。

新增contracts.py作为执行前规范化层：scope只表示员工类型，conditions表示额外业务前提；每周/week/weekly/一周等明确别名统一为每周；周期误放reference_event且不存在冲突时迁回period，DEADLINE不做这种迁移。员工类别仅在与scope一致时从重复conditions中移除，类别不一致则返回语义冲突；不会从正式员工改成试用期或从每月改成每周。conditions按集合比较而非顺序，原文quote不改写，数值、单位和约束类型不放宽。

规范化前的raw_arguments、转换记录、每次契约尝试及逐字段provenance均保留。额外条件逐项标为user/history_user或model，不能把整个条件列表都当作用户输入。结构/语义/覆盖错误返回field、actual、expected_semantics、allowed_corrections和constraint_source；反馈只能暴露已读规则内容或潜在冲突ID，不能自动补读证据。该层不选择工具或执行自动业务恢复。

claims 每项包含 statement、evidence_doc_id、evidence_quote、rule_id 和完整规则语义字段。数值 statement 必须符合确定性模板，文本必须为原文摘录。自由 answer、gaps 和 conflicts 仅是模型提交意见，不直接放行；最终正文、状态说明、缺口和冲突文本由校验结果生成，citations 从有效 claims 去重得到。

覆盖检查不仅比较规则组，还比较员工类型、日期、周期、参考事件、条件、约束类型和 facets，并要求覆盖相应组的全部适用条款。此策略保守，复杂自然语言和否定/条件推理可能要求澄清；它不等于通用意图或语义蕴含验证。

## 协议及运行保护

默认 8 次模型调用、10 次工具调用；非法参数、工具失败、终止调用都计入尝试预算，真实执行数单独统计。多调用按顺序处理，超预算调用仅产生 BUDGET_EXCEEDED。任何再次发送的历史均保证每个调用 ID 有 observation；预算耗尽后直接结束。最后一次额度内有效提交可以完成。

普通文本不能成功终止；无效终稿反馈模型修正。缺失/重复调用 ID、无法处理的协议结构和 API 异常为 FAILED。连续三次同工具、业务参数及 observation 相同且无新增证据时为 INCOMPLETE/NO_PROGRESS。注入一次或持续工具故障只改变工具结果，不决定模型恢复动作。

优先 strict=true、parallel_tool_calls=false，SDK max_retries=0、单请求超时45秒。兼容参数仅通过 `--no-strict-tools` / `--allow-parallel-tools` 或环境变量显式撤除，不自动降级。接受参数不证明服务实际强制 Schema；Trace 记录 unknown、accepted/enforcement unknown 或 observed violation。官方协议参考 [Function Calling](https://developers.openai.com/api/docs/guides/function-calling)、[Python SDK](https://developers.openai.com/api/reference/python)。

文档、历史均保持为数据，不注入 system 身份；工具仅为三项白名单。规则正文中的命令不能获得新的文件、Shell 或网络权限。离线数据隔离测试不代表真实模型已通过注入对抗。

DeepSeek兼容配置见README第13.6节。新增可选MODEL_REASONING_EFFORT=none，显式关闭思考模式；留空则不发送该请求字段。当前不支持思考模式所需的额外多轮协议，其他非空值在配置阶段拒绝。Trace记录请求的reasoning_effort，不记录隐式推理链。服务端strict与parallel约束可显式关闭，本地校验不变；本轮已实际调用DeepSeek，14项Live通过，具体配置及局限见评估文档。

## 保存与复现

默认日期为 Asia/Shanghai 当天；测试统一 2026-10-28。CLI 参数覆盖环境预算，环境预算覆盖默认值。Trace 记录语料/提示词/Schema 哈希、实际及请求模型、服务域名、依赖、时间、耗时、计数、校验及真实 observation；next_action 在实际后续动作发生后回填。文件经过密钥脱敏和临时文件替换；多文件整体不具备事务性，部分保存后失败会明确报错。

完整业务结果（包括澄清/证据不足）退出0，配置/输入错误退出2，FAILED/INCOMPLETE/保存失败退出1。哈希与版本用于定位实验，不保证远程模型结果完全可复现。

Live路径评估额外核对语料哈希、固定日期、实际业务执行、观察后的模型轮次、终止动作及引用读取来源；持续故障必须实际观察INJECTED_FAILURE。动态对照忽略参数/契约拒绝，比较真实检索与下一轮实际执行动作，同批并行调用不能被解释成观察结果后的选择。测试结果按唯一批次保存在examples/test_runs/，旧记录不删除。
