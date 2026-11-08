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

## OpenCode 的成员连接

成员可以包含可选 `connection` 对象：`provider`（`openai` 兼容协议或 `anthropic`）、`model`、`credential_ref` 和可选 `base_url`。旧工作流不需要增加该字段。`credential_ref` 始终是本机环境变量名称，不是 key 值。

导出执行配置 `knot.json` 中的 `backend: "opencode"` 表示按任务 `owner_id` 选择成员连接，此时共享 `model` 必须为空。任务仍使用 `agent_id` 对应的角色与提示词；Agent 上的旧 API 配置不覆盖成员连接。所有编码任务必须有完整的负责人连接，启动时还会检查凭据是否存在。仅负责人工审核的成员不需要 API 连接。

OpenCode 走 `local` 编码路径，沿用独立工作副本、显式数据交接、审核与失败重试。运行记录只保存成员、模型与凭据引用等连接信息，恢复时核对配置；不保存真实 key。`codex` / `claude` 仍使用 `knot.json` 的共享模型，`--mode real` 仍使用逐 Agent 直接 API 配置。

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

`credential_ref` 是环境变量名称，真实 key 不属于工作流格式。OpenCode 模式按负责人选择预先配置的成员连接；负责人字段本身不能代替文件权限、提供密钥或验证远程人员身份。

完整字段约定见根目录 `CONTRACT.md`；实际可接受结构以 `runtime/validation.py` 的校验为准。
