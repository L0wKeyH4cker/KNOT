# 工作流格式与执行语义

所有入口使用同一份 `schema_version: "1.0"` JSON：画布编辑、AI 草案、JSON 导入导出和 Python 执行器之间不做语义转换。

| 顶层字段 | 含义 |
| --- | --- |
| `project` | 项目名、任务目标、交付目标、成员列表 |
| `agents` | Agent 名称、角色、system prompt、提供商、模型名、凭证引用、允许工具 |
| `nodes` | 积木 ID、类型、标签、画布位置、配置 |
| `edges` | 起点/终点、端口、`control` 或 `data` 类型 |
| `resources` | 材料引用、相对路径、描述、是否示例、可选内联内容 |
| `limits` | 最大并发、超时、重试次数、工具调用轮数 |
| `viewport` | 平移与缩放，仅用于展示 |
| `design_notes` | 设计依据或待补信息 |

任务用 `agent_id` 引用 Agent，用 `owner_id` 引用成员。同一 Agent 可以承担多个任务，同一成员可以负责多个 Agent 的任务。

成员列表是任务负责人和审核人的内部姓名记录，不是账号或权限系统。界面不再单独设置人数、姓名或技能；需求生成和任务里的负责人输入会维护姓名记录，旧工作流的成员 ID 与技能仍保留。需求分析任务可含 `owner`（明确的人名，未指定为空）；有明确分工时，生成节点的 `config.requirement_task_indexes` 用从 1 开始的编号关联已确认任务，规划阶段校验覆盖及负责人一致性。该关联用于生成检查，不影响执行调度。

项目设置保留 **Members** 人工审阅总览，按 `owner_id` 展示每个人的 Agent 任务和审核节点。归属以任务为单位，同一个 `agent_id` 可以对应不同人的任务；不额外引入与任务归属冲突的 Agent 全局负责人。

## 用量与费用账本

费用数据独立于工作流，修改账本不会改变工作流哈希或触发任务重跑。运行状态的 `usage_ledger` 按 `run_id + node_id + attempt` 保存每次尝试，并导出 `logs/usage-report.json`（`kind: "knot-usage"`、`schema_version: "1.0"`）。每条记录包含执行时的 Agent 和负责人快照、执行状态、模型、已报告用量及可选估算金额。历史责任不会跟随画布改名或改负责人重新分配。

前端账本使用 `kind: "knot-billing"`、`schema_version: "1.0"`，保存于 `knot.billing.v1.<encoded project id>`；由 `entries`（执行用量）、`confirmed`（人工核对金额及分摊方式）、`shared`（补录共用费用）组成。用户必须显式导入账本 JSON 才会恢复确认金额；普通用量报告不能夹带确认金额。详情、限制及舍入规则见 [BILLING.md](BILLING.md)。

## 两种连线

`control` 连线决定执行顺序，不自动授予读取上游内容的权限。普通端口为 `out → in`，Condition 的输出端口为 `true` 和 `false`。

`data` 连线决定可读取的上游结果，端口为 `data-out → data-in`。任务只收到自己的入站数据连线引用的内容，不共享其它 Agent 的完整聊天记录。

两种依赖都参与环检测。移动积木或缩放画布不会改变依赖。所有节点必须沿执行连线从唯一的 Start 可达。

## 积木

| 类型 | 运行含义 |
| --- | --- |
| `start` | 项目入口 |
| `shared_resource` | 从 `resource_ids` 指定的材料读取内容，只允许 `inputs/` 内的路径 |
| `parallel` | 激活多个独立分支，由并发限制决定同时运行数量 |
| `agent_task` | 使用指定 Agent 执行任务，输入由数据连线明确提供 |
| `condition` | 对结构化结果字段执行 `eq`、`neq`、`gt` 或 `contains` 判断 |
| `human_review` | 持久化状态并暂停，等待明确 approve/reject 后继续 |
| `output` | 根据 `mappings` 把明确引用的上游成果写入 `results/` |

Agent Task 可配置具体要求、验收要求、输出类型、工具和读写权限。Output 的每项映射包含 `source_node`、`filename`、`format`；源节点必须有直接数据连线。数据连线可以从汇总任务直接到 Output，而执行连线经过 Human Review，因此文件交付会等待审核。

## 汇合和跳过

节点等待所有执行依赖和数据依赖结束。未选择的条件分支标为 `skipped`；其下游继续传播跳过，而非一直等待。

- `all_selected`：默认规则，等待所有执行入边结束，至少有一个激活的成功分支即可继续；允许其它分支被跳过。
- `all_success`：每个执行输入都必须成功；存在跳过分支时该节点也跳过。

失败或拒绝审核会阻止依赖它的后续节点。数据来自已跳过分支时该项不存在；不会伪造输入结果。

## 文件权限和凭证

工具为 `read_text`、`read_csv`、`summarize_csv`、`write_file`。运行时会同时检查 Agent 工具许可、任务工具许可和任务路径许可。读取只限 `inputs/` 和 `results/`，写入只限 `results/`，并校验实际解析路径，拒绝 `..`、绝对路径和符号链接绕过。

`credential_ref` 是环境变量名称，真实 key 不属于工作流格式。人工负责人字段只表达协作归属，不能代替文件权限或 API 凭证。

完整字段约定见根目录 `CONTRACT.md`；实际可接受结构以 `runtime/validation.py` 的校验为准。
