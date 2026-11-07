# KNOT

在自由画布上设计小组 AI 工作流，下载包含固定 Python 执行器的 ZIP，在自己的电脑上运行。任务、Agent、人类负责人分别配置；画布的节点和连线就是运行包使用的工作流。

升级到 KNOT 后，浏览器内旧版保存的项目和项目库会自动迁移，已有的新存档不会被覆盖。

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

新项目可在首页点击 **Add requirements** 直接上传 PDF，也可先创建项目；已有项目点击 **AI designer → Upload project requirements**。不需要先把 PDF 的内容手动整理成项目目标。Agents、项目设置和 AI designer 使用独立页面，点击 **Back** 返回画布。

1. 上传 PDF、TXT 或 Markdown 文件，检查并按需修改提取出的原文。
2. 填写规划模型的 API 模型 ID，点击 **Analyze requirements**。模型会整理项目目标、交付物、具体任务、验收要求，以及还缺少的信息。
3. 检查并修改任务清单，点击 **Generate workflow from requirements**。生成的积木和连线可以继续编辑；一次 Undo 可恢复生成前的工作流。

上传和文字提取在本地完成，不需要 API key。点击分析、生成或测试连接时才调用配置的模型。支持带可选择文字的 PDF；扫描件尚未提供 OCR，会明确提示换用文本 PDF 或粘贴文字。单个文件最多 5 MiB、PDF 最多 40 页、提取文字最多 60,000 字符，超过限制会提示，不会悄悄截断。

生成后，需求原文和确认后的任务清单会作为项目材料保存，随工作流 JSON 和运行包 ZIP 一起导出；不附带原始 PDF。只上传或关闭弹窗不会修改现有画布。完整操作和限制见 [需求文件使用说明](docs/REQUIREMENTS.md)。

验收时已在本地生成示例运行包、`report.md`、`summary.csv` 和运行验证摘要。这些产物位于 `artifacts/`，不提交到 Git；克隆仓库后可按下方命令重新生成。

运行 `python -m backend.export_example` 可用当前固定执行器重新生成示例 ZIP。这个命令只打包，不执行工作流，也不批准人工审核。上面的示例成果由验收时单独解压、运行并显式确认审核后生成。

如需重新执行整条演示验收，运行 `python scripts/verify_demo.py`。它会打包、解压到临时目录、确认审核前没有交付文件，再**明确模拟一次审核批准**，保存成果及包含 ZIP SHA-256 的验证摘要。这是开发验收脚本，不包含在用户下载的运行包中。

解压运行包后，Windows 运行 `start.bat`，macOS/Linux 运行 `sh start.sh`。运行到审核时退出码是 **2**，表示暂停。检查 `logs/run-state.json` 的草稿，明确批准后继续：

```sh
python run.py --mode mock --resume --review review --decision approve --reviewer member-3
```

拒绝时使用 `--decision reject`。新的一次运行应将 ZIP 解压到新的目录，已有运行状态不会被悄悄覆盖。真实执行时把命令中的模式改为 `real`。

## 模型与凭证

规划模型负责生成结构化草案；任务 Agent 各自使用单独配置的模型连接。支持 OpenAI 兼容接口与 Anthropic Messages；OpenAI 官方 GPT-6 模型执行带工具的任务时自动使用 Responses，模型名称由用户填写。

工作流中只允许保存环境变量名称，例如 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`，不要把真实 key 放进节点、prompt 或 JSON。模型设置中的 **API key → Save on this device** 会将凭证保存到本机 `.env.local` 并立即生效；密码框随后清空，浏览器本地存储和导出 ZIP 不包含 key。也可以自行设置后端环境变量。

选择 **DeepSeek** 会自动填写官方 API 地址、`DEEPSEEK_API_KEY` 引用和 `deepseek-flash` 模型 ID；可按账号实际支持的模型修改。DeepSeek 使用现有 OpenAI-compatible 适配器，工作流 schema 不变。参考 [DeepSeek 官方接入说明](https://api-docs.deepseek.com/)。点击 **Test connection** 会发送一条简短测试请求；常规服务限制为 16 个输出 token，OpenAI 官方接口上限为 512（包含推理 token），只有完整返回非空文本才显示成功。测试不发送项目材料。

模型字段必须填写 API 模型 ID。例如 GPT-6 Luna 的 ID 是 `gpt-6-luna`，不能填写带空格的展示名称 `GPT-6 Luna`。规划模型和 Agent 的模型字段都遵守这一规则；参见 [OpenAI 官方模型说明](https://developers.openai.com/api/docs/models/gpt-6-luna)。页面显示 `Credential detected` 只代表配置中有 key，不代表生成请求已成功。

开发后端启动时优先读取 `.env.local`，其次 `.env`，不覆盖已存在的进程环境变量。在设置页显式保存的新 key 会更新当前后端进程和 `.env.local`，无需重启。规划模型的非敏感连接设置保存在当前浏览器中。下载的运行包使用自己的 `.env`，凭证需在运行包所在电脑另外配置。

- **mock**：固定示例结果，验证调度、条件、权限和人工审核，不调用收费 API。
- **real**：调用真实 API。缺少模型、凭证或 API 调用失败时明确报错，不会切换到 mock。

已使用用户配置的 `gpt-6-luna` 完成真实需求分析和工作流生成：两页合成测试 PDF 提取出 3 项任务，生成 7 个节点、14 条连线。尚未执行这条工作流的真实 Agent 任务。完整验证状态见 [验证记录](docs/VERIFICATION.md)。本次调用的详细记录仅保留在本地 `artifacts/requirements-live-check.json`；可在界面上传自己的测试文档，再依次分析和生成，验证当前 API 配置。

## 不同任务使用不同 API 和模型

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

下载 **Export runner** 后，在运行包的 `.env` 中为上述引用填写真实密钥，然后运行 `python run.py --mode real`。默认 mock 模式只验证流程；编辑器的后端配置也不会把密钥复制进下载包。自定义凭证引用显示“未检查”时，表示健康检查没有报告该名称，不能据此判定密钥不存在；真正调用时后端会检查它。

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

已完成生产构建、**125 项 Python 验收（123 通过、2 个系统权限相关用例跳过）**、18 项前端数据测试和 **25 项浏览器交互测试**。前端数据测试包含旧版项目迁移、连接预设和写入失败后的数据保留。浏览器测试包括真实 PDF 上传与文字提取、任务清单编辑、生成后保存、JSON/ZIP 导出、多 Agent 独立模型配置、凭证设置、新首页恢复存档和返回导航，也保留了实际拖拽、连线和下载包独立运行的验证。离开生成页后，旧请求的延迟结果不会覆盖后来打开的项目。浏览器中的模型响应使用明确的测试数据，真实 API 验证单独记录。完整结果和跳过项见 [验证记录](docs/VERIFICATION.md)。运行 `npm run test:browser` 会在本地 `artifacts/browser/` 生成需求上传、任务确认、桌面画布和小屏画布截图；这些文件不随仓库发布。

MVP 限定为单机、无环工作流。支持读取文本/CSV、基础 CSV 汇总、写入 Markdown/JSON/CSV，不提供任意 shell、代码执行、联网搜索或浏览器工具。负责人成员信息不会授予凭证或文件访问权限。

前端保存采用浏览器本地存储；不是多人实时协作系统。执行器只在 API 返回实际用量时记录 token，不估造账单。人工审核是本地操作确认，未实现企业身份认证。

任务的验收要求会交给模型并供人工审核，不等于自动证明结果正确。需求导入支持文本型 PDF、TXT 和 Markdown；运行包处理的是提取后的 UTF-8 文本/CSV，不在运行时解析 PDF。自然语言局部修改、多人实时协作和跨电脑调度未实现；AI 草案可以在画布上完整编辑。

参考官方文档：[React Flow](https://reactflow.dev/learn)、[Vite](https://vite.dev/guide/)。
