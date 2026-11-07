# 验证记录

最新验证日期：2026-11-07（America/New_York）。此文件只记录实际执行过的验证；mock、协议测试和真实模型调用分别记录。

## 环境

- 工作目录：用户本地 KNOT 项目。
- Node.js：主进程已发现 24.19.0。
- Python：已实际执行用户 Miniconda 解释器，版本 3.14.6；系统 `python.exe` 是不可执行的 WindowsApps 别名。`scripts/dev.mjs` 会自动查找有效解释器。
- 初次交付时没有 OpenAI 或 Anthropic API 凭证；当时没有进行真实模型调用。之后的连接排障记录见下文。

## 实际结果

| 验证 | 实际结果 |
| --- | --- |
| Python 后端、执行器、导出集成测试 | 最新同次整合运行 **125 项：123 通过、2 跳过、0 失败**，18.598 秒 |
| 前端工作流、需求材料、存档迁移及连接预设数据测试 | **18 项全部通过** |
| Windows 启动器 | 实际解压 ZIP，执行 `start.bat`，创建 `.venv` 和 `.env`，成功运行至人工审核，退出码 2 |
| macOS/Linux 启动器 | Git Bash `bash -n` 语法检查通过；没有在 macOS/Linux 主机上执行 |
| 独立示例交付 | 导出 ZIP → 新目录解压 → mock 运行 → 审核暂停 → 显式确认 → 生成 report.md 和 summary.csv |
| 前端生产构建 | `npm run build` 已通过：TypeScript 检查与 Vite 生产构建成功 |
| 浏览器实际交互 | Playwright + 独立 Chrome：**24 项全部通过**；包含新首页与旧存档恢复、连接设置、多 Agent 独立配置、需求上传、浏览器返回和过期生成结果隔离，以及原有画布和运行包验证 |
| 真实模型 API | **5 个模型调用通过**：OpenAI Luna、Sol、Astra，以及 DeepSeek V4 Pro、V4 Flash 兼容 ID；两条 real 工作流完成，其中一条跨服务商执行工具并传递结果。此前 Luna 的合成 PDF 需求分析及工作流生成也已通过 |

KNOT 更名复验：生产构建通过；Python 94 项（93 通过、1 项系统权限跳过）、前端数据 16 项、浏览器 15 项全部完成。独立浏览器还验证了页面标题与可见品牌、旧版项目和项目库恢复，以及 `knot-workflow.zip` 下载名。生成的 `knot-demo.zip` 内 README、启动器和执行器均使用新名称，已重新独立运行到审核并在测试批准后交付。代码仅在旧存档兼容键及其测试中保留旧标识，不显示为产品名称。

Python 两个跳过项都需要先创建符号链接：一个验证执行器拒绝读取，另一个验证凭证保存拒绝覆盖链接目标。Windows 主机未授权测试进程创建符号链接。路径越界、Windows 预留文件名、大小写等价路径和最终文件保护的测试均已通过；这些符号链接系统级用例尚未实跑。

实际命令：

```sh
python -m unittest discover -s tests -p "test_*.py" -v
npm run test:model
node scripts/dev.mjs --check-python
npm run build
# 先在另一个终端启动 npm run dev，再运行：
npm run test:browser
```

本机 Python 测试使用已安装的 Miniconda 解释器，没有依赖系统中失效的 WindowsApps 别名。其他环境可通过 `PYTHON` 指定自己的解释器。集成测试在项目下 `.test-tmp/` 创建独立解压目录，子进程从解压目录运行、清除继承的 `PYTHONPATH`，完成后清理自身临时目录。HTTP 测试实际监听 loopback 随机端口。

浏览器测试使用独立 Chrome 会话，不依赖已登录的个人浏览器。Windows 自动查找 `C:/Program Files/Google/Chrome/Application/chrome.exe`；也可设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE`，或用 `npx playwright install chromium` 安装 Playwright Chromium。开发服务需先运行在 `127.0.0.1:5173` 和 `127.0.0.1:8000`。

## 关键验收证据

- **从零创建完整流程**：浏览器中填写项目、人数和目标，选择 Start from scratch，实际拖入 Start/Agent Task/Output，配置 Agent 和任务，拖端口建立执行/数据连接，检查通过后下载 JSON/ZIP。下载的手工工作流 ZIP 在新目录通过 Python 子进程实际运行，并生成 `report.md`。
- **自由画布交互**：实际移动积木并保留依赖；撤销/重做、复制/删除、保存后刷新恢复、拖动连接端点改接、删除/新建连接、循环拦截、平移/缩放及视角恢复均通过。JSON 往返保留节点、Agent、材料和连接。
- **浏览器显示与规划边界**：检查了小屏文档无横向溢出、导出控件可见以及页面无脚本异常。没有 key 时真实 `/api/plan` 请求明确报错；另用浏览器 API fixture 提供固定合法草案，验证后续人工编辑与撤销。后者仅验证交互，不是一次真实 AI 生成。
- **配置保真**：ZIP 内 `workflow.json` 与传入工作流深比较相等；位置、任务要求、权限、连线和输出文件名保留。修改 mock 内容和输出映射后，实际交付内容/文件名随之改变。
- **修改连接改变行为**：无审核的工作流能直接生成文件；在最终执行路径插入一个新的 Human Review 并重接连线后，导出包实际暂停，最终文件尚不存在。
- **审核不可自动跳过**：批准后交付，拒绝后阻止下游；多个人工审核节点需要逐个明确批准；恢复时已经成功的任务不重跑。修改工作流后不允许套用旧审核状态。
- **真实并发**：独立任务的开始/结束时间实际重叠；并发上限为 1 时执行串行；汇总任务等两项任务结束才开始。
- **条件与汇合**：未选分支标记 skipped；`all_selected` 汇合继续，`all_success` 按规则跳过；无永久等待。Output 读取已跳过来源时明确失败，不生成伪造文件。
- **显式数据**：只有执行连线时，任务不会自动拿到上游结果；需要数据连线。
- **权限**：工具调用同时检查 Agent/任务工具授权和文件路径授权；路径越界与未经允许的文件访问被阻止。大小写变化不能绕过最终 Output 文件保护。
- **规划模型**：没有凭证时明确拒绝；输出须通过 schema 与图校验；最多初次生成加两次修复；不能增加文件权限、工具授权或编造成员技能。此部分使用测试替身检验协议，未进行真实模型生成。
- **模型协议**：OpenAI Chat Completions、官方 GPT-6 工具任务的 Responses、DeepSeek 推理工具续接和 Anthropic Messages 的消息、工具调用、用量及错误处理有测试；有限工具轮数、缺 key、失败不回退均通过。另有真实 HTTP 请求到本地测试服务，覆盖混合适配器的 real 模式工作流、各任务独立上下文、各端点独立凭证及慢响应流的总超时。本地服务使用固定响应和测试凭证；提供商线上验证另记在下方。
- **凭证边界**：明显 key/secret 字段在前端保存前被拒绝；后端拒绝工作流内的环境凭证值；自定义凭证引用对应的值会被脱敏。ZIP 只含环境变量引用与空白 `.env.example`，无开发者绝对路径。

验收在本地生成了 `artifacts/knot-demo.zip`、`artifacts/demo-verification.json`、`artifacts/demo-results/report.md`、`artifacts/demo-results/summary.csv` 和对应事件/状态日志。整个 `artifacts/` 目录已由 Git 忽略，不包含在仓库中；可运行下方演示验收命令重新生成。示例审核由验收过程明确模拟确认，不声称通过了人类身份认证。`python -m backend.export_example` 只重新生成 ZIP，不运行工作流、不生成成果、不自动审核。

`python scripts/verify_demo.py` 是完整演示验收入口：重新打包、解压到临时目录、检查初次运行暂停且最终文件不存在，再显式调用 approve 恢复，保存报告、CSV、日志和验证摘要。成功后摘要包含所验 ZIP 的 SHA-256，便于核对包与证据一致。此脚本明确模拟审核，仅用于开发验收，不打包到普通运行包中。

运行 `npm run test:browser` 会在本地 `artifacts/browser/` 生成浏览器证据：`onboarding.png`、`canvas-desktop.png`、`canvas-mobile.png`、`manual-runner.zip` 和 `template-runner.zip`。产物不提交到 Git，测试源文件为 `tests/browser/workflow.spec.ts`。

## 已修复并回归验证的问题

独立审查发现并修复了 Windows 大小写路径绕过最终文件保护、畸形 JSON 导致校验异常、资料与固定 README 同名覆盖、真实 JSON 结果的结构解包以及启动器对 ensurepip 的不必要依赖。启动器使用 `venv --without-pip` 创建隔离环境，固定执行器只用标准库。

## 已知限制

- OpenAI 与 DeepSeek 的真实任务执行已通过下方合成输入测试；Anthropic 仅完成本地协议测试。此前由 PDF 生成的 7 节点工作流尚未执行 real Agent 任务。模型可用性和输出质量仍取决于账户及实际任务。
- macOS/Linux 启动脚本通过语法检查，尚未在相应系统上运行。
- 单机无环工作流，不支持循环、跨机器调度、多人实时协作或身份认证。
- 支持文本/CSV 和有限本地工具，不支持任意代码、shell、网页搜索、浏览器操作或 PPT 生成。
- 任务验收要求是模型指令与人工审核依据，不是自动质量证明；mock 使用固定示例结果。
- 画布以浏览器本地存储保存，受浏览器存储容量影响；重要工作流应另存 JSON。

## 必须明确区分

- mock 模式只验证流程，不证明真实模型输出质量或 API 可用性。
- 使用伪造 HTTP 服务的适配器测试，只能验证请求/响应处理，不能标记为真实 API 调用验证。
- UI 成功渲染不能代替实际拖拽、连线、恢复和导出后运行的验证。
- 规划请求缺少 key 必须明确报错；模板不是 AI 生成结果。

初次版本复验使用 `npm run build` 的生产产物，由 Python `server.py` 在端口 8000 提供页面。设置 `KNOT_URL=http://127.0.0.1:8000` 后运行浏览器测试，10/10 通过（12.2 秒）。`scripts/verify_demo.py` 重新导出并实际执行当时的运行包；ZIP 为 21 个条目，29,930 字节，审核前 report.md 和 summary.csv 不存在，批准后两者生成。重新运行 `python scripts/verify_demo.py` 后，可在本地 `artifacts/demo-verification.json` 查看对应运行包的大小和 SHA256。

## 后续 API 连接排障（2026-11-06）

用户配置凭证后，使用现有 key 对 OpenAI 官方模型查询接口做了两次只读请求：`GPT-6 Luna` 返回 HTTP 404 / `model_not_found`，`gpt-6-luna` 返回 HTTP 200 且 ID 相符。确认截图使用了展示名称，应改为 API 模型 ID。没有调用生成接口、没有消耗生成 token，没有输出或修改 key。此项只验证身份及模型可访问性，不替代完整 AI 生成和 real 工作流执行验证。

本次错误诊断修复新增 9 项纯测试替身用例。完整 Python 回归实际执行 60 项：59 通过、1 项符号链接系统权限跳过（14.536 秒）；前端构建通过。模型名输入增加 API ID 提示；HTTP 状态、白名单错误代码和固定中文建议可以显示在规划失败提示中，服务商原始响应内容不会回显。示例包当时已通过 verify_demo 再次独立执行；运行包及其大小、SHA256 记录属于本地验证产物，可重新运行该脚本生成。

## 需求 PDF → 任务分析 → 工作流（2026-11-06）

完整 Python 回归实际执行 **94 项，93 通过、1 项系统符号链接权限跳过**。新增验证覆盖真实文本 PDF 提取、页码和文档指纹、混合空白页提示、扫描件/加密/损坏/超限文件拒绝、解析超时、需求分析结构校验与修复、无凭证拒绝，以及原文传入规划模型和资源保留。`npm run test:model` 的 **10 项前端数据测试全部通过**，包括需求材料组装、保留原项目内容和无效任务拒绝；最终生产构建通过。

最新生产构建由独立本地测试服务 `http://127.0.0.1:8001` 提供，未停止用户已有服务。设置 `KNOT_URL` 后运行全部浏览器测试，**15 项全部通过，19.8 秒**。五项新增用例位于 `tests/browser/requirements.spec.ts`：

- 新项目不填写目标或交付物，直接上传真实两页 PDF；实际调用后端提取文字，再分析并编辑任务标题，生成画布后继续修改、保存、刷新。
- 真实无文字 PDF 被后端拒绝，页面显示扫描件/OCR 说明，不调用规划模型。
- 关闭上传弹窗后，项目、材料、节点位置和连线不变。
- 修改提取原文会清除旧任务分析；再次分析时发出修改后的文字。
- 生成保留原有项目名、成员和其它材料，一次 Undo 恢复原工作流。

这些浏览器用例只有 `/api/requirements/analyze` 和 `/api/plan` 的模型响应使用固定测试数据；PDF 提取、校验和 ZIP 导出调用真实后端。导出的 JSON 包含需求原文和修改后的任务，ZIP 内两份材料的内容逐字一致，没有原 PDF。测试使用独立 Chrome 会话；没有访问用户个人浏览器、读取 key 或调用线上模型。

另有一次独立的真实模型验证：使用用户已配置的 `gpt-6-luna`，将两页合成测试 PDF 的提取文本交给需求分析接口，得到 **3 项任务**；随后调用规划接口，得到 **7 个节点、14 条连线**，源材料完整保留。输入为虚构调查数据，未使用用户私有项目文档。详细记录仅保留在本地 `artifacts/requirements-live-check.json`，不随仓库发布。这证明本次分析和规划调用成功；`execution_run:false` 明确表示没有进一步执行真实 Agent 任务，也不能据此保证任意文档的分析质量。复验当前配置时，可在界面上传测试文档，依次点击 Analyze requirements 和 Generate workflow from requirements；这会发起真实模型调用，不属于默认测试套件。

弹窗关闭、文档移除和字段锁定的小修完成后，针对最终生产构建再次运行五项需求浏览器用例，**5/5 通过，7.5 秒**。本地浏览器证据包括 `artifacts/browser/requirements-upload.png`、`requirements-review.png`、`requirements-runner.zip`，可用 `npm run test:browser` 重新生成。截图禁用了淡入动画，已检查上传入口和可编辑任务卡片显示完整。

## 多服务商、多模型任务分工（2026-11-07）

最新完整回归为 **109 项 Python 测试：108 通过、1 项系统符号链接权限跳过**；前端生产构建通过，前端数据测试 16 项通过，浏览器交互测试 18 项通过。更新后的示例 ZIP 已用 `scripts/verify_demo.py` 重新导出并独立运行，确认审核前无交付文件、测试批准后生成报告与 CSV。

新增自动化覆盖：

- `tests/test_multi_provider.py` 的 6 项测试使用三个独立 loopback HTTP 服务，分别校验模型、地址、认证和任务上下文；验证并行执行、显式结果传递、单个凭证缺失时零请求、401 后阻止下游且不回退 mock，以及导出 ZIP 在独立子进程中的 real 协议执行。
- `tests/test_reasoning_providers.py` 的 9 项测试验证官方 GPT-6 工具任务路由至 Responses、第三方兼容地址仍走 Chat Completions、完整工具续接、推理内容不进入结果、DeepSeek 推理字段回传，以及异常输出、重复调用 ID、工具权限、轮数和超时检查。
- `tests/browser/providers.spec.ts` 的 3 项测试验证三个 Agent 的独立配置、任务绑定、保存刷新及 JSON 导出；切换服务商清空模型和地址，规划模型独立；未知凭证引用显示“未检查”，不误报“缺失”。浏览器测试不会请求线上模型。

真实 API 测试使用用户已配置的本地环境凭证，未打印或修改密钥；输入仅包含合成标记和测试文本文件，没有用户项目文档：

| 实际流程 | 结果 |
| --- | --- |
| `gpt-6-luna` 与 `gpt-6-sol` 并行返回各自标记 → `gpt-6-astra` 接收两份结果并汇总 | 3 个任务成功，整体 completed；三个 OpenAI 模型 ID 的只读查询也均返回 HTTP 200 |
| `deepseek-v4-pro` 与 `deepseek-v4-flash` 并行读取测试文件 → `gpt-6-astra` 接收两份结果、读取同一测试文件并汇总 | 3 个任务成功，各调用一次 `read_text`，返回预期标记，整体 completed |

第二条流程实际验证了 DeepSeek Chat Completions 的推理工具续接和 OpenAI Astra Responses 的工具续接。针对官方 `api.openai.com` 地址的 `gpt-6*` 工具任务自动选择 Responses；其他兼容地址保持 Chat Completions。推理上下文只用于本次 API 续接，不写入任务结果或日志。

本地证据为 `artifacts/selected-models-check.json` 和 `artifacts/mixed-models-live-check.json`，均不提交 Git。前一份记录生成时尚未配置 DeepSeek，因此其 `deepseek_live_verified:false` 是当时状态；用户随后配置凭证，后一份记录已确认 DeepSeek 与 Astra 的混合流程成功。此次测试证明连通、模型路由、工具执行及结果传递，不是通用任务能力或输出质量评测。

模型名与当前映射参考 [OpenAI GPT-6 工具调用说明](https://developers.openai.com/api/docs/guides/latest-model)、[DeepSeek 接口说明](https://api-docs.deepseek.com/) 和 [DeepSeek 推理工具调用说明](https://api-docs.deepseek.com/guides/thinking_mode/)。其中 `deepseek-v4-flash` 是兼容名称，目前由 DeepSeek-V4.1-Flash-1017 提供服务；此次保留并实测了用户指定的旧 ID，不声称调用已下线的原 V4 Flash 版本。

## 首页和连接设置分支合并（2026-11-07）

实际远端分支为 `codex/shipitbot-ui`，此次合并来源为 `66f9ae9`，合并前 main 为 `6301ad4`。比较后端后，保留 main 的执行器、需求解析、导出、权限检查及多模型工具续接，只接入新界面需要的本地凭证保存、连接测试和健康状态接口；HTTP 402 归类为额度不足。没有使用分支旧代码覆盖 main 的功能。

新界面包括首页、需求上传入口、独立设置页面、DeepSeek 预设、保存凭证和测试连接。合并时保留 KNOT 品牌、项目存档迁移与多 Agent 独立配置，规划配置以 `knot.planner.v1` 单独保存，并兼容经过校验的旧规划配置。

修复了合并发现的兼容问题：未知凭证引用不误报缺失且可由后端实际检查；连接测试必须得到完整非空文本，空响应、拒绝、截断和意外工具调用不会假报成功；官方 OpenAI 使用兼容的输出预算参数。连接测试不发送项目材料。保存密钥的 HTTP 测试只操作临时目录，浏览器保存/连接测试使用固定响应，不写入用户 `.env.local`，不调用线上模型。

生产构建和 18 项前端数据测试通过。完整 Python 回归 125 项，其中 123 通过、2 项因 Windows 符号链接权限跳过。示例 ZIP 已重新独立运行，审核前无交付文件，显式测试批准后生成报告与 CSV。此次合并验证没有额外调用收费 API，前述五模型真实调用记录仍属于上一轮验证。

浏览器覆盖扩展到 24 项，新增 KNOT/旧版项目库及规划配置恢复、首页直接上传需求、浏览器后退后保留原项目，以及延迟生成响应隔离。后者先暂停旧请求，后退并打开另一个项目、发起新请求，再放行旧响应，确认它不会改变项目、跳转页面或解除新请求的忙碌状态；随后新请求可以正常完成。页面离开时只丢弃过期结果，已经发给模型服务的请求不能据此撤回。
