# TeamBlocks

在自由画布上设计小组 AI 工作流，下载包含固定 Python 执行器的 ZIP，在自己的电脑上运行。任务、Agent、人类负责人分别配置；画布的节点和连线就是运行包使用的工作流。

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

1. 创建项目，填写项目名、小组人数、任务目标和最终交付物。
2. 选择 **Start from scratch** 搭建空白画布，或 **Generate with AI** 使用已配置的规划模型。没有 API 凭证时，可以使用明确标注的演示模板。
3. 从左侧拖入积木，在画布上移动、连接、配置。执行连线表示何时开始，数据连线表示可以读取哪些上游结果。
4. 修改任务、Agent、负责人或权限；保存后刷新，或导入/导出工作流 JSON。
5. 运行检查并下载 ZIP，解压到新的目录，按包内 README 运行。

示例为三人校园可持续出行调研。两项任务并行执行，汇总结果经过人工审核后生成 `report.md` 和 `summary.csv`。示例材料是虚构的教学输入，不能作为真实调研数据。

## 从需求文件生成工作流

新项目可先填写项目名和人数，再点击 **Upload project requirements** 上传 PDF；已有项目点击 **AI designer → Upload project requirements**。不需要先把 PDF 的内容手动整理成项目目标。

1. 上传 PDF、TXT 或 Markdown 文件，检查并按需修改提取出的原文。
2. 填写规划模型的 API 模型 ID，点击 **Analyze requirements**。模型会整理项目目标、交付物、具体任务、验收要求，以及还缺少的信息。
3. 检查并修改任务清单，点击 **Generate workflow from requirements**。生成的积木和连线可以继续编辑；一次 Undo 可恢复生成前的工作流。

上传和文字提取在本地完成，不需要 API key。点击分析、生成时才调用配置的规划模型。支持带可选择文字的 PDF；扫描件尚未提供 OCR，会明确提示换用文本 PDF 或粘贴文字。单个文件最多 5 MiB、PDF 最多 40 页、提取文字最多 60,000 字符，超过限制会提示，不会悄悄截断。

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

规划模型负责生成结构化草案；任务 Agent 各自使用单独配置的模型连接。支持 OpenAI Chat Completions 与 Anthropic Messages 两种 API 适配方式，模型名称由用户填写。

工作流中只允许保存环境变量名称，例如 `OPENAI_API_KEY`，不要把真实 key 放进节点、prompt、JSON 或浏览器。真实 key 在启动后端或运行包的环境中配置；参考 `.env.example` 和导出包内的 `.env.example`。

模型字段必须填写 API 模型 ID。例如 GPT-6 Luna 的 ID 是 `gpt-6-luna`，不能填写带空格的展示名称 `GPT-6 Luna`。规划模型和 Agent 的模型字段都遵守这一规则；参见 [OpenAI 官方模型说明](https://developers.openai.com/api/docs/models/gpt-6-luna)。页面显示 `Credential detected` 只代表配置中有 key，不代表生成请求已成功。

开发后端优先读取 `.env.local`，其次 `.env`，不覆盖已存在的进程环境变量。运行包使用自己的 `.env`。编辑器只有凭证引用输入框，不接收或展示真实 key。

- **mock**：固定示例结果，验证调度、条件、权限和人工审核，不调用收费 API。
- **real**：调用真实 API。缺少模型、凭证或 API 调用失败时明确报错，不会切换到 mock。

已使用用户配置的 `gpt-6-luna` 完成真实需求分析和工作流生成：两页合成测试 PDF 提取出 3 项任务，生成 7 个节点、14 条连线。尚未执行这条工作流的真实 Agent 任务。完整验证状态见 [验证记录](docs/VERIFICATION.md)。本次调用的详细记录仅保留在本地 `artifacts/requirements-live-check.json`；可在界面上传自己的测试文档，再依次分析和生成，验证当前 API 配置。

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

已完成生产构建、**94 项 Python 验收（93 通过、1 个系统权限相关用例跳过）**、10 项前端数据测试和 **15 项浏览器交互测试**。浏览器测试包括真实 PDF 上传与文字提取、任务清单编辑、生成后保存和 JSON/ZIP 导出，也保留了实际拖拽、连线和下载包独立运行的验证。浏览器中的模型响应使用明确的测试数据，真实 API 验证单独记录。完整结果和跳过项见 [验证记录](docs/VERIFICATION.md)。运行 `npm run test:browser` 会在本地 `artifacts/browser/` 生成需求上传、任务确认、桌面画布和小屏画布截图；这些文件不随仓库发布。

MVP 限定为单机、无环工作流。支持读取文本/CSV、基础 CSV 汇总、写入 Markdown/JSON/CSV，不提供任意 shell、代码执行、联网搜索或浏览器工具。负责人成员信息不会授予凭证或文件访问权限。

前端保存采用浏览器本地存储；不是多人实时协作系统。执行器只在 API 返回实际用量时记录 token，不估造账单。人工审核是本地操作确认，未实现企业身份认证。

任务的验收要求会交给模型并供人工审核，不等于自动证明结果正确。需求导入支持文本型 PDF、TXT 和 Markdown；运行包处理的是提取后的 UTF-8 文本/CSV，不在运行时解析 PDF。自然语言局部修改、多人实时协作和跨电脑调度未实现；AI 草案可以在画布上完整编辑。

参考官方文档：[React Flow](https://reactflow.dev/learn)、[Vite](https://vite.dev/guide/)。
