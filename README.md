# KNOT

<img src="public/brand/KNOT-logo.png" alt="KNOT" width="220" />

在自由画布上设计小组 AI 工作流，下载可调用本地 Codex、Claude 或 OpenCode 的项目工作包。所有 Agent 按画板分工，在一台电脑上写代码、执行任务并交接成果。Codex/Claude 使用共享连接；OpenCode 按任务负责人使用各自的 API key 和模型。

升级到 KNOT 后，浏览器内旧版保存的项目和项目库会自动迁移，已有的新存档不会被覆盖。

## 下载并运行本地 Agent 工作包

1. 在画板上确认任务和连接，点击 **Export runner**。
2. 在 **Run with** 选择 **Codex**、**Claude** 或 **OpenCode**。Codex/Claude 的共享模型可以留空。选择 OpenCode 时，先为团队成员配置连接，并为每个任务指定负责人，模型与密钥跟随负责人。
3. 点击 **Download agent workspace**，解压到新目录。用户电脑需要 Python 3.10+ 和对应 CLI：[Codex 安装说明](https://developers.openai.com/codex/cli/)、[Claude Code 安装说明](https://code.claude.com/docs/en/setup)、[OpenCode CLI](https://opencode.ai/docs/cli/)。Codex/Claude 使用本机登录；本地 OpenCode 个人包自动携带网页已保存的任务负责人凭据，无需再次配置。
4. 如有初始项目代码，放入 `workspace/`；按包内 **Inputs you must provide** 补齐资料。接下来按操作系统启动任务。

### Windows：启动任务

在资源管理器进入解压后的文件夹，确认能看到 `knot.cmd` 和 `workflow.json`。点击地址栏，输入 `powershell` 后按 Enter，再执行：

```powershell
.\knot.cmd run --interactive
```

### macOS / Linux：启动任务

打开终端，进入解压后的文件夹；把下面第一行的路径换成自己的路径：

```sh
cd "/path/to/extracted-folder"
sh knot.sh run --interactive
```

**运行一次就会自动派发画板上的任务。** 启动器读取导出时保存的运行方式，为每个 Agent 建立独立任务上下文；能并行的任务同时执行，依赖其他任务的工作会等待结果。不需要逐个打开 Agent 或复制任务说明。没有预先选择的包会询问一次并记住选择。

### OpenCode：按负责人使用连接

想先测试两个用户的连接，在首页点击 **Test member APIs** 打开“双人 API 连通测试”。Alice 和 Bob 并行写入两个小文件，再由 Alice 读取并汇总；详细步骤见 [样例说明](examples/owner-api-smoke.md)。同一台电脑上可用 `python scripts/run_owner_example.py "解压目录"` 直接使用编辑器保存的成员 key，无需再次填写；加 `--validate` 只检查配置，不发起模型调用。

在项目的团队成员设置中，为每位负责人填写服务商、模型和成员专属凭据引用；任务的 **Human owner** 决定使用哪个连接，Agent 的角色与提示词决定如何工作。同一服务商的两位成员也应使用不同引用，避免覆盖彼此的 key。

运行电脑需安装 OpenCode CLI **2.2.6 或以上的 2.x 版本**。已有 npm 时可运行 `npm install -g @opencode/cli@2.2.6`。KNOT 为每项任务启动 `--standalone` 独立实例，使用任务专属的临时配置，结束后清理；不会复用 OpenCode 默认共享后台中的账号。

在本地编辑器保存各任务负责人的 key，导出时选择 **OpenCode**，保持 **Include saved member API keys** 勾选。下载的 `knot-personal-workspace.zip` 会自动包含已配置的 `.env`，解压后即可启动，无需手工填写密钥。只写入实际任务负责人的 key；未参与执行的成员、规划模型和其他环境凭据不会被一起导出。未保存某位负责人的 key 时，导出会指出该成员，先保存再下载即可。

**个人包中的 `.env` 含明文密钥，ZIP 和解压目录只供本人使用，不要分享或提交到 Git。** 如需分享流程，取消上述选项，下载只含空白 `.env.example` 的包，由接收者配置自己的 `.env`。公开部署不提供携带服务器凭据的导出。工作流 JSON、提示词和浏览器存储始终只保留凭据引用。

可执行 `.\knot.cmd run --validate`（macOS/Linux：`sh knot.sh run --validate`）检查，再按上文启动任务。连接缺失会明确停止，不会换用其他成员或本机全局登录的账号。`--validate` 不调用线上模型，因此不代表模型权限或配额已经验证。

所有任务仍在这一台电脑上运行。把同一个 ZIP 发到多台电脑分别启动，会产生独立运行，不会自动组成远程团队。KNOT 负责依赖、并行、结果交接和人工审核，OpenCode 负责单个任务里的代码编辑与命令执行。负责人连接的服务商、模型和凭据引用随运行记录保存；恢复与失败重试必须沿用原任务配置，密钥值不写入记录。

运行窗口会显示实时看板。**任务执行期间保持这个窗口打开**；打开监控窗口后也不要关闭它。Windows 也可以双击 `start.bat`，macOS/Linux 可以运行 `sh start.sh`，同样会启动任务。

如果提示找不到 Python，请先安装 Python 3.10+；已安装 Conda 的用户可以运行 `conda env list`，再执行 `conda activate YOUR_ENV_NAME`（将 `YOUR_ENV_NAME` 换成自己的 Python 3.10+ 环境名），然后重试上面的启动命令。使用 Conda 时，新的监控窗口也应激活相同环境。`knot.cmd` / `knot.sh` 会选择可用的 Python，无需手动填写解释器路径。

### 另开一个终端：查看所有项目的进度

新开终端并进入同一个解压目录，再执行对应命令：

**Windows PowerShell**

```powershell
.\knot.cmd monitor
```

**macOS / Linux**

```sh
sh knot.sh monitor
```

`monitor` 只查看本机已注册项目的状态；**它不会启动或派发任务**。先执行上面的 `run --interactive` 才会开始工作。看板展示任务状态、耗时、命令、文件改动和最近活动；多个项目可以在同一个看板切换。

交互式看板启动时会短暂显示 KNOT 标志。运行中右上角的 K / 工作流图标交替，只表示任务仍在运行，不代表完成百分比；空闲、等待审核或结束时固定显示 K。给 `run` 或 `monitor` 命令加上 `--no-splash` 可跳过开场；设置环境变量 `KNOT_NO_ANIMATION=1` 可关闭全部动画，`NO_COLOR=1` 可关闭颜色。`status`、JSON 和重定向输出始终保持纯文本。

- 上下箭头或 `j` / `k` 选择任务，Tab 或 `n` / `p` 切换项目。
- 按 `q` 隐藏看板，Agent 继续运行。独立监控窗口按 `Ctrl+C` 或关闭窗口也不会停止任务。
- **在运行窗口按 `Ctrl+C` 会停止它启动的本地 Agent。**
- 只想看一次状态，用 `.\knot.cmd status` 或 `sh knot.sh status`。

### 人工审核与结果

到达 Human Review 节点后，回到**运行窗口**检查草稿，输入 `approve` 批准、`reject` 拒绝，或 `later` 保持暂停。按 Enter 也只会保持暂停。之后可再次执行同一条 `run --interactive` 命令处理已保存的审核，已完成的任务不会重跑。

Output 节点将项目文件交付到 `results/project/`，画板配置的报告放在 `results/`。审核前的草稿保留在 `.knot/tasks/`，运行窗口会提示具体路径。

### 调整运行方式与监控说明

更换执行方式、只检查配置或改用滚动日志：

| 操作 | Windows PowerShell | macOS / Linux |
| --- | --- | --- |
| 更换运行方式 | `.\knot.cmd run --configure` | `sh knot.sh run --configure` |
| 只检查配置和 CLI | `.\knot.cmd run --validate` | `sh knot.sh run --validate` |
| 使用滚动日志 | `.\knot.cmd run --interactive --plain` | `sh knot.sh run --interactive --plain` |

`--configure` 在开始新一次运行前使用；`--validate` 不调用模型，认证和实际模型可用性仍需真实调用确认。已能直接使用 Python 的用户也可以运行 `python knot.py run --interactive` / `python knot.py monitor`。旧的 `--mode mock` 与 `--mode real` 保留为显式高级模式。

旧运行包可用 `python knot.py monitor --root "旧运行包路径"` 查看已记录的状态；要看到命令和文件的实时活动，需要重新导出新版 ZIP。界面显示完成任务数和距上次活动的时间，静默或连接断开不会被当作任务完成。

运行发现只在本机保存目录指针和心跳：Windows 位于 `%LOCALAPPDATA%/KNOT/runs`，macOS/Linux 位于 `$XDG_STATE_HOME/knot/runs`（默认 `~/.local/state/knot/runs`），可用 `KNOT_RUNS_DIR` 改位置。不扫描全盘、不上传日志；进度摘要不含任务提示词、结果正文、命令输出和模型私有推理，并过滤凭据及终端控制符。

`knot.json` 保存执行方式，`workflow.json` 保留原画板及成员连接；`tasks/` 和 `prompts/` 是可读的任务说明，`AGENTS.md` / `CLAUDE.md` 方便编程助手接手。任务各自拥有工作副本，独立任务按画板并发上限执行。执行连线只控制先后，数据连线才传递上游结果和代码改动。文件冲突会明确停止相关任务，不会自动覆盖。

源码交接限制为单文件 16 MiB、总计 128 MiB、最多 5,000 个文件；不适合把大型数据集、权重或依赖目录作为源码交接。

本地 Agent 任务失败并查明原因后，可执行 `.\knot.cmd run --retry-failed --interactive`（macOS/Linux：`sh knot.sh run --retry-failed --interactive`）。这会备份原状态，保留成功任务，只重试失败任务并恢复受其阻断的下游。失败任务的草稿会复制到新的工作目录，重新检查后才能作为成功产物交接；旧草稿保持不变。修改过工作流或执行配置、人工审核已拒绝、仍在运行或中断状态不明的项目不能直接使用此命令，应保留记录并在新目录重新开始。人工审核暂停仍按上文批准或拒绝，不会被失败重试自动跳过。

任务按实际交付物和验收判断完成。某条采集命令失败后，若其他已获允许的方式取得相同质量的证据并完成必要检查，应记录方法限制，而不是仅因失败尝试把任务判为阻断；明确规定的采集方法和未完成的必要检查仍必须满足。

启动器默认运行真实本地 Agent；缺少 CLI、认证或输入资料时停止并说明原因，不会退回 mock。账号额度与模型权限由用户配置的连接提供，网页版聊天本身不代表具备本地执行能力。工作副本用于隔离并行改动，不是操作系统沙箱；命令权限由所选 CLI 执行。仅明确选择携带密钥的 OpenCode 个人包包含所需成员凭据。

## 启动项目

需要 Node.js 22.12+（或 20.19+）和 Python 3.10+。本地后端使用 `pypdf` 提取需求 PDF；下载的固定执行器仍然只使用标准库。

```sh
npm install
python -m pip install --target .tools/python -r requirements.txt
npm run dev
```

打开 http://127.0.0.1:5173。开发启动器会同时启动 Vite 和端口 8000 的 Python 后端。它会查找 `PYTHON` 环境变量、`python3`、`python`、`py -3`，以及用户目录下的 Miniconda / Anaconda。

如果 Python 未加入 PATH，可先设置 `PYTHON` 为解释器路径：

```powershell
$env:PYTHON = 'C:\path\to\python.exe'
& $env:PYTHON -m pip install --target .tools/python -r requirements.txt
npm run dev
```

也可以分别启动：

```sh
python server.py --port 8000
npx vite --host 127.0.0.1
```

生产构建在本地运行：

```sh
npm run build
python server.py --port 8000
```

打开 http://127.0.0.1:8000；后端会提供 `dist/` 中的页面。此项目按本地应用设计，未部署公网服务。

## 演示流程

首次访问时，首页会高亮 **Explore an example**。点击后进入示例的 9 步功能引导，逐项介绍画布、积木、连线、任务配置、Agent、项目设置、AI 设计、检查和导出；支持 **Previous / Next / Back to home**。每一步的 **Back to home** 都返回首页，右上角 **×** 或 **Escape** 只关闭引导并留在当前示例页面，可以继续编辑。需要重看时打开 **A quick guide → Take a guided tour**。

**Quick Guide** 提供 9 步全英文图文教程，每步使用示例项目的真实页面截图，支持翻页、章节跳转和截图放大；最后可以返回首页开始自己的项目。阅读教程不会修改当前工作流，也不会调用模型。首页说明文字和项目输入框之间提供 **View on GitHub** 按钮，在新标签页打开本仓库。

项目库中点击项目图标或名称会在新标签页打开该项目，原标签页保持不变；各项目草稿分别自动保存。右侧垃圾桶按钮先弹出确认窗口，选择 **Delete project** 才会删除；**Cancel** 或 **Escape** 会取消操作。删除会同时清理对应存档与草稿，并阻止其他旧标签页的自动保存让它重新出现。

引导期间的示例是临时演示，返回首页会恢复原来的项目；只关闭引导时，示例会成为可编辑的独立项目，原有的未完成项目会先保存在项目库中。关闭或完成的状态只保存在当前浏览器，不会重复弹出。引导只读取演示资料、进行本地工作流检查，不会自动调用模型、保存凭证或下载运行包。

1. 在首页描述项目想法，点击 **Continue** 填写项目名、小组人数、任务目标和最终交付物；也可以直接点 **Add requirements** 上传需求。
2. 选择 **Start from scratch** 搭建空白画布，或 **Generate with AI** 使用已配置的规划模型。没有 API 凭证时，可以使用明确标注的演示模板。
3. 从左侧拖入积木，在画布上移动、连接、配置。执行连线表示何时开始，数据连线表示可以读取哪些上游结果。
4. 修改任务、Agent、负责人或权限；保存后刷新，或导入/导出工作流 JSON。
5. 运行检查并下载 ZIP，解压到新的目录，按包内 README 运行。

示例为三人校园可持续出行调研。两项任务并行执行，汇总结果经过人工审核后生成 `report.md` 和 `summary.csv`。示例材料是虚构的教学输入，不能作为真实调研数据。

## 从需求文件生成工作流

新项目可在首页点击 **Add requirements** 直接上传 PDF，也可先创建项目；已有项目点击 **AI designer → Upload project requirements**。不需要先把 PDF 的内容手动整理成项目目标。Agents、项目设置、AI designer、项目库和帮助在同一工作台内切换，只替换右侧内容；顶部 Logo 和左侧导航保持可用。点击左侧 **Workflow canvas** 或 **Back** 返回画布，原有缩放、节点位置和编辑内容会保留。鼠标悬停或键盘聚焦侧栏图标时显示功能提示，按 **Escape** 关闭提示。

1. 上传 PDF、TXT 或 Markdown 文件，检查并按需修改提取出的原文。
2. 填写规划模型的 API 模型 ID，点击 **Analyze requirements**。模型会整理项目目标、交付物、具体任务、验收要求，以及还缺少的信息。
3. 检查并修改任务清单，点击 **Generate workflow from requirements**。生成的积木和连线可以继续编辑；一次 Undo 可恢复生成前的工作流。

上传和文字提取在本地完成，不需要 API key。点击分析、生成或测试连接时才调用配置的模型。支持带可选择文字的 PDF；扫描件尚未提供 OCR，会明确提示换用文本 PDF 或粘贴文字。单个文件最多 5 MiB、PDF 最多 40 页、提取文字最多 60,000 字符，超过限制会提示，不会悄悄截断。

生成后，需求原文和确认后的任务清单会作为项目材料保存，随工作流 JSON 和运行包 ZIP 一起导出；不附带原始 PDF。只上传或关闭弹窗不会修改现有画布。完整操作和限制见 [需求文件使用说明](docs/REQUIREMENTS.md)。

验收时已在本地生成示例运行包、`report.md`、`summary.csv` 和运行验证摘要。这些产物位于 `artifacts/`，不提交到 Git；克隆仓库后可按下方命令重新生成。

运行 `python -m backend.export_example` 可用当前固定执行器重新生成示例 ZIP。这个命令只打包，不执行工作流，也不批准人工审核。上面的示例成果由验收时单独解压、运行并显式确认审核后生成。

如需重新执行整条演示验收，运行 `python scripts/verify_demo.py`。它会打包、解压到临时目录、确认审核前没有交付文件，再**明确模拟一次审核批准**，保存成果及包含 ZIP SHA-256 的验证摘要。这是开发验收脚本，不包含在用户下载的运行包中。

需要演练模板时，显式运行 `python run.py --mode mock`。运行到审核时退出码是 **2**，表示暂停。检查 `logs/run-state.json` 的草稿，明确批准后继续：

```sh
python run.py --mode mock --resume --review review --decision approve --reviewer member-3
```

拒绝时使用 `--decision reject`。新的一次运行应将 ZIP 解压到新的目录，已有运行状态不会被悄悄覆盖。恢复时必须使用原来的运行模式；本地 Agent 使用 `local`，直接 API 调用使用 `real`。

## 规划与直接 API 模式的模型、凭证

规划模型负责生成结构化草案；下文的逐 Agent 连接配置适用于高级 `--mode real` 直接 API 模式。本地 Codex/Claude 模式使用导出时选择的统一连接。直接 API 模式支持 OpenAI 兼容接口与 Anthropic Messages；OpenAI 官方 GPT-6 模型执行带工具的任务时自动使用 Responses，模型名称由用户填写。

工作流中只允许保存环境变量名称，例如 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`，不要把真实 key 放进节点、prompt 或 JSON。模型设置中的 **API key → Save on this device** 会将凭证保存到本机 `.env.local` 并立即生效；密码框随后清空，浏览器本地存储不包含 key。只有 OpenCode 个人包会把实际任务负责人已保存的 key 单独写入 `.env`；其他导出保持无密钥。也可以自行设置后端环境变量。

选择 **DeepSeek** 会自动填写官方 API 地址、`DEEPSEEK_API_KEY` 引用和 `deepseek-flash` 模型 ID；可按账号实际支持的模型修改。DeepSeek 使用现有 OpenAI-compatible 适配器，工作流 schema 不变。参考 [DeepSeek 官方接入说明](https://api-docs.deepseek.com/)。点击 **Test connection** 会发送一条简短测试请求；常规服务限制为 16 个输出 token，OpenAI 官方接口上限为 512（包含推理 token），只有完整返回非空文本才显示成功。测试不发送项目材料。

模型字段必须填写 API 模型 ID。例如 GPT-6 Luna 的 ID 是 `gpt-6-luna`，不能填写带空格的展示名称 `GPT-6 Luna`。规划模型和 Agent 的模型字段都遵守这一规则；参见 [OpenAI 官方模型说明](https://developers.openai.com/api/docs/models/gpt-6-luna)。页面显示 `Credential detected` 只代表配置中有 key，不代表生成请求已成功。

开发后端启动时优先读取 `.env.local`，其次 `.env`，不覆盖已存在的进程环境变量。在设置页显式保存的新 key 会更新当前后端进程和 `.env.local`，无需重启。规划模型的非敏感连接设置保存在当前浏览器中。下载的运行包使用自己的 `.env`；OpenCode 个人包自动带上负责人已保存的凭据，无密钥分享包需在运行电脑配置。

- **local**（默认）：调用用户电脑上的编程工具。Codex/Claude 使用共享连接；OpenCode 按任务负责人选择成员模型与凭据。各任务维护独立上下文和工作副本。
- **mock**（显式选择）：固定示例结果，验证调度、条件、权限和人工审核，不调用收费 API。
- **real**：调用真实 API。缺少模型、凭证或 API 调用失败时明确报错，不会切换到 mock。

已使用用户配置的 `gpt-6-luna` 完成真实需求分析和工作流生成：两页合成测试 PDF 提取出 3 项任务，生成 7 个节点、14 条连线。尚未执行这条工作流的真实 Agent 任务。完整验证状态见 [验证记录](docs/VERIFICATION.md)。本次调用的详细记录仅保留在本地 `artifacts/requirements-live-check.json`；可在界面上传自己的测试文档，再依次分析和生成，验证当前 API 配置。

## 高级：不同任务使用不同 API 和模型

同一个 KNOT 执行器可以连接多个模型服务。打开 **Agents**，分别为每个 Agent 设置 **Provider、Model name、Credential reference、API base URL**；然后在画布上的 **Agent Task → Agent** 选择负责该任务的 Agent。例如：

| 工作 | Agent | 接口协议 | 模型 | 凭证引用 |
| --- | --- | --- | --- | --- |
| 资料分析 | Analyst | OpenAI-compatible | 服务 A 的模型 ID | `ANALYSIS_API_KEY` |
| 撰写初稿 | Writer | Anthropic | 服务 B 的模型 ID | `WRITING_API_KEY` |
| 审校汇总 | Reviewer | OpenAI-compatible | 服务 C 的模型 ID | `REVIEW_API_KEY` |

三个 Agent 可以使用不同 API 地址和密钥；这是配置示意，模型 ID 和地址需要按你的服务填写。一个 Agent 被多个任务复用时，这些任务共享该 Agent 的模型配置。要用不同模型，应建立不同 Agent。切换接口提供商会清空原模型和地址，避免使用上一家服务的配置。

以下五个模型已在 2026-11-07 用真实 API 验证通过。在界面中按服务商选择 **OpenAI** 或 **DeepSeek**；自建兼容服务选 **Other OpenAI-compatible API**。地址和凭证引用位于 **Advanced connection settings**：

| 模型 | Model name | API base URL | Credential reference |
| --- | --- | --- | --- |
| OpenAI Luna | `gpt-6-luna` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| OpenAI Sol | `gpt-6-sol` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| OpenAI Astra | `gpt-6-astra` | `https://api.openai.com/v1` | `OPENAI_API_KEY` |
| DeepSeek V4 Pro | `deepseek-v4-pro` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |
| DeepSeek V4 Flash（兼容名称） | `deepseek-v4-flash` | `https://api.deepseek.com` | `DEEPSEEK_API_KEY` |

`deepseek-v4-flash` 仍可调用，但按 [DeepSeek 官方说明](https://api-docs.deepseek.com/)，这个旧 ID 当前指向 DeepSeek-V4.1-Flash-1017；这里保留用户指定的 ID，不代表测试了已经下线的旧版模型。

实际跑通了两条测试流程：Luna 与 Sol 并行执行，交给 Astra 汇总；DeepSeek V4 Pro 与 V4 Flash 并行读取合成测试文件，再由 Astra 接收两份结果并汇总。后一条流程的三个任务各成功调用一次 `read_text` 工具。这验证了真实调用、工具执行和跨服务商结果传递，不是任务质量评测。

OpenAI 兼容服务默认使用 **Chat Completions**（基础地址后追加 `/chat/completions`）；Anthropic 使用 **Messages**（追加 `/messages`）。OpenAI 官方地址上的 `gpt-6*` 模型在启用工具时自动使用 **Responses**（追加 `/responses`），按 [OpenAI 工具调用说明](https://developers.openai.com/api/docs/guides/latest-model) 处理推理模型的工具续接。DeepSeek 工具续接保留接口要求的推理上下文，但不将其保存到任务结果或日志。填写 Base URL 时不要包含最终请求路径。第三方服务仍需兼容 Chat Completions 或 Messages；仅提供 Responses 或原生 Gemini 的第三方接口目前不能直接接入。

任务之间用执行连线控制先后顺序，用数据连线传递结果。独立任务可以并行，汇总任务等依赖完成后执行。AI designer 的规划模型单独配置，不会代替执行 Agent 的模型设置。生成画布后，仍需配置每个任务 Agent。

如需使用上述直接 API 配置，在运行包的 `.env` 中为这些引用填写真实密钥，然后运行 `python run.py --mode real`。该路径与默认的本地 Codex/Claude 模式分开；编辑器的后端配置不会把密钥复制进下载包。自定义凭证引用显示“未检查”时，表示健康检查没有报告该名称，不能据此判定密钥不存在；真正调用时后端会检查它。

## Git 协作

`.env.example` 中的凭证只能保留空值。真实 key 写入本地 `.env.local`，不要加入版本控制。依赖、构建产物、运行结果和 `artifacts/` 均由 `.gitignore` 排除；`.gitattributes` 统一仓库文件的换行格式。

本项目已设置 `core.hooksPath=.githooks`。其他克隆需要运行一次以下命令启用提交检查；提交前也可以手动扫描暂存文件：

```sh
git config core.hooksPath .githooks
npm run check:secrets
```

## 文件结构

| 位置 | 内容 |
| --- | --- |
| `src/` | React + TypeScript + React Flow 画布和配置界面 |
| `server.py`、`backend/` | 本地 HTTP 接口、规划、ZIP 组装 |
| `runtime/`、`run.py` | 导出包复用的固定执行器和 CLI |
| `examples/team-research.json` | 可编辑的示例工作流 |
| `tests/` | 执行器、权限和打包测试 |
| `docs/SCHEMA.md` | 工作流字段与执行语义 |
| `docs/VERIFICATION.md` | 实际验证结果与尚未验证的内容 |

## 校验与限制

```sh
npm run build
python -m unittest discover -s tests -v
npm run test:model
```

前端数据测试需要 Node.js 22.6+ 的 TypeScript stripping 支持。浏览器测试需要先在一个终端运行 `npm run dev`，然后在另一个终端运行：

```sh
npm run test:browser
```

Windows 会自动使用默认安装目录中的 Google Chrome。其它环境或没有该 Chrome 时，先运行 `npx playwright install chromium`，也可以将 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 环境变量设为已有浏览器的可执行文件路径。

合并后的版本已完成生产构建、**239 项 Python 验收（237 通过、2 个 Windows 符号链接权限相关用例跳过）**、**35 项前端数据测试**和 **66 项浏览器交互测试**。前端数据测试包含旧版项目迁移、连接预设、引导状态、独立项目存储和写入失败后的数据保留。浏览器测试包括真实 PDF 上传与文字提取、任务清单编辑、生成后保存、JSON/ZIP 导出、多 Agent 独立模型配置、凭证设置、首次访问引导、项目删除确认、独立标签页、损坏项目库恢复、刷新保存和 Check 返回画板，新增共享工作台侧栏切换、画布状态保留及图标悬停/键盘提示检查，也保留了实际拖拽、连线、导出教程复制及下载包独立运行的验证。离开生成页后，旧请求的延迟结果不会覆盖后来打开的项目。浏览器中的模型响应使用明确的测试数据，真实 API 验证单独记录。各轮结果和跳过项见 [验证记录](docs/VERIFICATION.md)。运行 `npm run test:browser` 会在本地 `artifacts/browser/` 生成需求上传、任务确认、桌面画布和小屏画布截图；这些文件不随仓库发布。

MVP 限定为单机、无环工作流。本地模式调用 Codex/Claude/OpenCode 提供编程与命令工具；直接 API 模式仍只支持读取文本/CSV、基础 CSV 汇总、写入 Markdown/JSON/CSV，不提供 shell 或代码执行。OpenCode 按负责人选择已配置的连接，负责人姓名本身不会提供凭证或授予文件访问权限。

前端保存采用浏览器本地存储；不是多人实时协作系统。执行器只在 API 返回实际用量时记录 token，不估造账单。人工审核是本地操作确认，未实现企业身份认证。

任务的验收要求会交给模型并供人工审核，不等于自动证明结果正确。需求导入支持文本型 PDF、TXT 和 Markdown；运行包处理的是提取后的 UTF-8 文本/CSV，不在运行时解析 PDF。自然语言局部修改、多人实时协作和跨电脑调度未实现；AI 草案可以在画布上完整编辑。

参考官方文档：[React Flow](https://reactflow.dev/learn)、[Vite](https://vite.dev/guide/)。
