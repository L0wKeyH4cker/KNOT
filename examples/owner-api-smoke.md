# 双人 API 连通测试

首页点击 **Test member APIs**，或在编辑器导入同目录的 `owner-api-smoke.json`。

这个样例只有三个短任务：Alice 写 `alice.txt`，Bob 同时写 `bob.txt`，最后 Alice 读取双方文件，写出总和为 42 的 `summary.md`。无需外部资料、网页搜索或安装项目依赖。文件工具可能发起多轮模型请求，所以三个任务不等于三次 API 请求。

## 配置两个用户

在 **Project settings → Team members** 分别展开 Alice 和 Bob 的 **Configure connection**：

1. 选择各自的服务商，填写该账户可用的模型 ID。默认显示 OpenAI，但可以换为 Anthropic、DeepSeek 或其他兼容接口。模型故意留空，避免误用不属于你账户的模型。
2. 分别填写、保存各自的 API key。两位成员可以用同一服务商的不同 key，也可以用不同服务商、不同模型。
3. 凭据引用已经分别设为 `KNOT_DEMO_ALICE_API_KEY` 和 `KNOT_DEMO_BOB_API_KEY`，无需修改。

**这次要填写成员连接。** Agents 面板设置的是角色和旧直接 API 模式的连接。三个任务共用同一个 Agent 角色，OpenCode 仍按任务负责人选择各自的 key 和模型。

| 任务 ID | 负责人 | 使用的凭据引用 |
| --- | --- | --- |
| `alice-write` | Alice | `KNOT_DEMO_ALICE_API_KEY` |
| `bob-write` | Bob | `KNOT_DEMO_BOB_API_KEY` |
| `alice-join` | Alice | `KNOT_DEMO_ALICE_API_KEY` |

## 导出并启动

选择 **Export runner → OpenCode** 并下载 ZIP，解压到一个新文件夹。浏览器里保存的 key 不会放进 ZIP。

### 在当前编辑器所在电脑测试

在本项目源码目录打开终端，使用本机辅助脚本。它读取此编辑器保存的成员 key，并在解压目录执行任务；不会把 key 复制进工作包。终端中已有的同名环境变量优先。

```powershell
python scripts/run_owner_example.py "你的解压目录" --validate
python scripts/run_owner_example.py "你的解压目录"
```

第一条只检查配置和 CLI；第二条才发起真实模型请求。如果本项目 `.tools/opencode-cli` 下已安装 OpenCode，辅助脚本会直接使用，否则使用系统 PATH 中的 OpenCode。不要关闭运行窗口。失败原因修复后，可以给第二条加上 `--retry-failed`。

### 在其他电脑运行，或直接使用独立工作包

需要在解压目录配置凭据：复制 `.env.example` 为 `.env`，填写下面两项的真实值，并保存。

```dotenv
KNOT_DEMO_ALICE_API_KEY=
KNOT_DEMO_BOB_API_KEY=
```

在包含 `knot.py` 的解压目录打开 PowerShell。电脑需要 Python 3.10+ 和 OpenCode CLI 2.2.6 起的 2.x 版本；完整安装说明见工作包的 `START-HERE.md`。先检查配置，这一步不发起模型任务：

```powershell
.\knot.cmd run --validate
```

没有错误后开始运行：

```powershell
.\knot.cmd run --interactive
```

本样例没有人工审核节点，三个任务成功后会直接交付。不要把 key 填进任务说明、模型名或 JSON 文件。

## 怎么判断跑通

1. 看终端：两个写入任务都成功，汇总任务在双方结束后运行，最后显示工作流完成。
2. 看 `results/project/`：`alice.txt` 中是 `ALICE_VALUE=17`，`bob.txt` 中是 `BOB_VALUE=25`；`summary.md` 包含 `TOTAL=42` 和 `HANDOFF_OK`。`results/route-smoke-report.json` 还应有 `total: 42`、`handoff_ok: true`。
3. 看 `logs/run-state.json` 的 `task_routes`：`alice-write` 与 `alice-join` 应使用 Alice 的模型和凭据引用，`bob-write` 应使用 Bob 的。这里记录的是执行器配置，不包含 key 的真实值。模型自己说“我是某某模型”不能作为路由证明。

想进一步确认不同 key 生效，可以结合两边供应商的调用记录。也可以另解压一份工作包，保持 Alice 的 key 正确、将 Bob 的 key 改为无效测试值：预期 Bob 的任务认证失败，Alice 的独立任务仍可完成，汇总任务不会交付。这个反向测试仍可能产生 Alice 的正常调用费用。测试后恢复 Bob 的真实 key，再用 `--retry-failed` 明确重试；若换了负责人、服务商或模型，使用新的解压目录重新运行。

样例目前只验证配置和导出结构。你填写真实 key 后执行，才能确认你的账户权限、模型可用性和这次线上调用的结果。
