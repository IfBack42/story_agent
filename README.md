# Story Illustration Agent

一个基于 LangChain、DeepSeek，并可调用本地/自建服务器或云端生图模型的故事插画 Agent。

> **项目状态：V1 已完成。** 当前版本定位为单用户、本地运行的多模态 Agent MVP，核心业务闭环已经跑通；后续事项属于工程化迭代，不影响 V1 的学习、演示和作品集交付。

当前版本完成的流程：

```text
用户提出生图要求
→ Agent 调用 Prompt Optimizer
→ 根据目标模型配置自动读取对应提示词模板和可选模型手册
→ Agent 根据请求调用本地/自建服务器模型或云端图片 API
→ 图片保存到当前故事文件夹的 pictures/
→ 返回图片路径、seed、尺寸和耗时
```

当前已支持按故事持久化会话：运行时使用 `InMemorySaver` 管理 Agent 状态，每轮结束后把完整消息保存到故事目录的 `conversation.json`。再次运行时按故事名称选择存档，程序会恢复原 `session_id` 和历史消息。

## 1. 项目结构

```text
story_agent/
├─ main.py                         # 主 Agent 入口
├─ story_session.py                # 故事创建、选择、读取和 JSON 保存
├─ tools/
│  ├─ prompt_optimizer_tool.py    # 提示词优化 Tool
│  ├─ local_image_tool.py         # 本地/自建服务器生图 Tool
│  ├─ localimgconfig/             # 一个本地模型一个配置文件
│  ├─ apiimgconfig/               # 一个云端模型 API 一个配置文件
│  └─ api_image_tool.py           # 统一云端生图 Tool
├─ prompt_guides/
│  ├─ agent_system_promt.txt      # 主 Agent 系统提示词（公开版）
│  ├─ llm_system_prompt_local.txt # 本地提示词优化规则
│  ├─ llm_system_prompt_api.txt   # 云端提示词优化规则（公开版）
│  └─ WAI_Illustrious_v15_Public_Guide.md # 本地 WAI 模型公开手册
├─ history_data/                   # 一个故事一个文件夹
│  └─ 故事名称__短会话ID/
│     ├─ conversation.json         # 故事名称、完整 session_id 和消息
│     └─ pictures/                 # 该故事生成的本地/云端图片
└─ examples/                       # 脱敏的演示对话和示例图片
```

## 2. 安装：先选择生图后端

Forge 不是本项目的必装项。先根据使用场景选择：

| 需求 | 选择 | 是否安装 Forge |
|---|---|---|
| 有 NVIDIA 显卡，希望本地运行、支持负面提示词和 OpenPose | 本地 Forge | 需要 |
| 没有合适显卡，或只想快速运行项目 | 云端图片 API | 不需要 |

两个方案都需要安装 Agent 自身的 Python 依赖；只有选择本地生图时，才继续安装 Forge。

### 2.1 安装 Agent 的 Python 环境（两种后端都需要）

当前项目验证环境：

```text
Python：3.10.18
Conda 环境：D:\A_Python\conda_envs\edu_rag
```

如果已经有 `edu_rag` 环境，进入项目目录后执行：

```powershell
& 'D:\A_Python\conda_envs\edu_rag\python.exe' -m pip install -r requirements.txt
```

换一台电脑时，也可以新建普通 Conda 环境：

```powershell
conda create -n story_agent python=3.10 -y
conda activate story_agent
python -m pip install -r requirements.txt
```

`requirements.txt` 只负责 Agent 项目，不负责安装 Forge。`openai`、`httpx` 等间接依赖会由 pip 自动安装。

### 2.2 配置 DeepSeek（两种后端都需要）

主 Agent 和 Prompt Optimizer 读取：

```text
dpsk_url
DEEPSEEK_API_KEY
```

只在当前 PowerShell 会话中临时设置：

```powershell
$env:dpsk_url = "你的 OpenAI 兼容接口地址"
$env:DEEPSEEK_API_KEY = "你的 API Key"
```

不要把真实 API Key 写进 Python 文件或提交到 Git。

### 2.3 方案 A：不安装 Forge，直接使用云端图片 API

云端生图只需要网络和图片 API Key，不需要显卡，也不需要 `image_generation/` 目录。

当前 `api_image_tool.py` 支持 302.AI 的 Seedream 5.0 Pro 和 Flux-2-Klein-9b，统一读取：

```text
AI_302_API_KEY
```

可以设置环境变量：

```powershell
$env:AI_302_API_KEY = "你的 302.AI API Key"
```

也可以在 `story_agent/.env` 中写入：

```text
AI_302_API_KEY=你的API Key
```

当前 `main.py` 同时绑定一个本地/自建服务器模型和云端图片 API。Agent 在调用提示词优化 Tool 时必须同时声明目标后端与模型：

```python
{
    "prompt": "需要优化的画面描述",
    "image_backend": "cloud",
    "image_model": "seedream"
}
```

一句话理解：`image_backend` 决定去哪个注册表查，`image_model` 决定取哪一张模型配置表，配置表中的 `prompt_system_file` 和 `prompt_guide_file` 才决定使用哪套提示词规则。

- `local + wai`：配置选择 `llm_system_prompt_local.txt` 和 WAI 手册，并允许独立负面提示词；
- `local + qwen_image_2_1`：读取千问配置登记的模板和手册；当前启用独立负面提示词，并用 `true_cfg_scale=2.0` 让它生效；
- `cloud + seedream/flux`：各自配置当前都选择 `llm_system_prompt_api.txt`。

因此不是 LLM 自由挑模板。LLM 只决定要调用哪个已注册生图模型；代码再按该模型配置确定模板。优化阶段与生图阶段的模型名必须一致。

调用云端生图 Tool 时，再用 `api_model` 选择具体模型：

```text
api_model="seedream" → Seedream 5.0 Pro，直接返回图片 URL
api_model="flux"     → Flux-2-Klein-9b，提交任务后自动轮询结果
```

模型地址、尺寸、默认请求参数和调用协议统一放在 `tools/apiimgconfig/`；Seedream 和 Flux 各自使用独立文件，API Key 不写入配置文件。

云端方案的特点：

- 不支持 OpenPose；
- 没有独立的 `negative_prompt` 参数；
- 使用 `image_type` 二选一；Seedream 使用 `1664×2496 / 2496×1664`，Flux 使用 `832×1216 / 1216×832`；
- 按次计费，并带有平台内容审核；
- 图片仍会下载到 `story_agent/pictures/`。

可以先直接运行 `tools/api_image_tool.py` 做测试。它会先检查 Key，然后真实调用一次云端生图接口，因此会产生费用。

### 2.4 方案 B：需要本地生图时安装 Forge

本项目当前的 Forge 目录为：

```text
D:\A_Python\跟着黑马学ai\image_generation\stable-diffusion-webui-forge
```

当前已验证的 Forge 环境：

```text
Python：3.10.21
PyTorch：2.3.1+cu121
CUDA：12.1
Conda 环境：D:\A_Python\conda_envs\forge
```

Agent 的 `edu_rag` 和 Forge 的 `forge` 是两个独立环境，不要把 Forge 的大量依赖装进 `edu_rag`。

#### 安装方法一：Forge 官方一键包

Forge 官方为 Windows 提供包含 Git 和 Python 的一键包，CUDA 12.1 + PyTorch 2.3.1 版本与本项目当前环境一致。下载后解压，先运行包内的 `update.bat`，再运行 `run.bat`。

官方地址：<https://github.com/lllyasviel/stable-diffusion-webui-forge>

为了让本项目通过 HTTP 调用 Forge，还必须在启动参数中加入：

```text
--api
```

#### 安装方法二：按本项目当前结构安装

先安装 Git 和 Conda，然后执行：

```powershell
Set-Location -LiteralPath 'D:\A_Python\跟着黑马学ai\image_generation'
git clone https://github.com/lllyasviel/stable-diffusion-webui-forge.git
conda create -p 'D:\A_Python\conda_envs\forge' python=3.10.21 -y
```

编辑 Forge 根目录中的 `webui-user.bat`：

```bat
@echo off
set PYTHON=D:\A_Python\conda_envs\forge\python.exe
set GIT=
set VENV_DIR=-
set COMMANDLINE_ARGS=--api
call webui.bat
```

含义：

- `PYTHON`：指定独立的 Forge Python；
- `VENV_DIR=-`：不再额外创建一层 venv；
- `--api`：开放本项目所需的 HTTP API。

第一次运行 `webui-user.bat` 时，Forge 会安装自己的依赖，等待完成即可。

#### 放置模型

把主模型放入：

```text
image_generation/stable-diffusion-webui-forge/models/Stable-diffusion/
```

本项目当前默认使用：

```text
waiNSFWIllustrious_v150.safetensors
```

如需 OpenPose，把匹配的 ControlNet 模型放入：

```text
image_generation/stable-diffusion-webui-forge/models/ControlNet/
```

本项目使用的 SDXL OpenPose ControlNet 下载地址：

- [xinsir/controlnet-openpose-sdxl-1.0 模型页面](https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0)
- [直接下载 diffusion_pytorch_model.safetensors](https://huggingface.co/xinsir/controlnet-openpose-sdxl-1.0/resolve/main/diffusion_pytorch_model.safetensors?download=true)

该模型是专门用于姿势骨架控制的 **SDXL OpenPose ControlNet**，与当前项目的 `openpose_full` 预处理器和 SDXL 主模型方向一致。它是 ControlNet 辅助模型，不能替代 `waiNSFWIllustrious_v150.safetensors` 主 checkpoint。

当前本机文件名为：

```text
diffusion_pytorch_model.safetensors
```

代码识别到的模型名称为 `diffusion_pytorch_model [d0333a45]`。如果下载到的模型名称或哈希不同，需要同步修改 `tools/localimgconfig/wai.py` 中的 `reference_defaults["model"]`。

模型文件不包含在 `requirements.txt` 中，需要根据模型许可证自行下载。

#### 启动并检查 Forge

```powershell
Set-Location -LiteralPath 'D:\A_Python\跟着黑马学ai\image_generation\stable-diffusion-webui-forge'
.\webui-user.bat
```

看到下面的地址后表示网页服务已经启动：

```text
http://127.0.0.1:7860
```

可以使用只读接口检查 API：

```powershell
Invoke-RestMethod 'http://127.0.0.1:7860/sdapi/v1/samplers'
```

能返回采样器列表，就说明 Agent 可以连接 Forge。

#### Forge 网页端基本用法

1. 浏览器打开 `http://127.0.0.1:7860`；
2. 在顶部选择 checkpoint；
3. 进入 `txt2img`；
4. 输入正面提示词和负面提示词；
5. 设置尺寸、步数、CFG 和 seed；
6. 点击 Generate 生成图片；
7. 使用 OpenPose 时，展开 ControlNet，上传参考图，选择 `openpose_full` 和对应模型，将 Control Mode 设为 `Balanced`。

本项目调用 Forge 时的默认值位于 `tools/local_image_tool.py`：

```text
Forge 地址：http://127.0.0.1:7860
Checkpoint：waiNSFWIllustrious_v150.safetensors
人物剧情：832 × 1216（竖图）
场景剧情：1216 × 832（横图）
采样器：Euler a
步数：25
CFG：6.0
ControlNet 模式：Balanced
```

## 3. 运行主 Agent

### 3.1 故事名称与会话 ID

一句话理解：故事名称给人看，`session_id` 给程序识别，`conversation.json` 保存真正的历史内容。

```text
history_data/
└─ 鲸鱼小姐的故事__7c94c940/
   ├─ conversation.json
   └─ pictures/
```

文件夹后面的短 ID 用来避免同名故事冲突；完整随机 UUID 保存在 JSON 中，并作为 LangGraph 的 `thread_id`。用户选择故事时不需要输入 ID。

### 3.2 启动多轮对话

打开 `main.py`，可以在文件底部修改模型配置：

```python
if __name__ == "__main__":
    local_image_model = "wai"
    local_image_port = None
    local_image_mode = "txt2img"
    run_chat_loop(
        local_image_model=local_image_model,
        local_image_port=local_image_port,
        local_image_mode=local_image_mode,
    )
```

程序会先列出现有故事。输入序号恢复旧故事，直接回车后输入名称即可创建新故事：

```text
现有故事：
  [1] 鲸鱼小姐的故事（3 轮）

输入故事序号继续，直接回车创建新故事：
>
请输入新故事名称：
> 雪原车站

已进入故事：雪原车站
session_id：...
故事目录：...\history_data\雪原车站__短ID

用户：故事主角叫小雨，她穿红色风衣。
...
```

每轮回答完成后立即更新 `conversation.json`。本地 Forge 和云端 API 生成的图片都会进入当前故事的 `pictures/`。

### 3.3 实际运行演示

2026-09-27 使用公开版提示词完成了一次本地端到端验收，演示故事为“雪原车站演示”。测试流程如下：

```text
创建新故事并输入人物设定
→ 第二轮保持设定并请求生成插画
→ Prompt Optimizer 选择 WAI 公开规则与公开模型手册
→ Agent 调用本地 WAI，未使用云端接口
→ 图片保存到当前故事的 pictures/
→ 输入 q 退出
→ 重新运行并选择同名故事
→ 成功恢复 2 轮历史并准确回答人物设定
```

本次本地生图结果：

| 项目 | 实际结果 |
|---|---|
| 本地生图后端 | WAI NSFW Illustrious v15.0 / Forge |
| 图片尺寸 | 1024×1400 |
| seed | 2531283182 |
| 生图耗时 | 约 59 秒 |
| 云端 API | 未调用 |
| 会话恢复 | 重启后成功恢复人物、职业、衣着、相机与场景设定 |

![雪原车站演示生成结果](examples/demo/snow_station_demo.png)

完整的脱敏对话摘录见 [examples/demo/conversation_excerpt.md](examples/demo/conversation_excerpt.md)。真实 `history_data/` 不作为演示材料提交。

建议在提示词中明确写出“生成图片”或“画一张图”。如果只要求讲故事，Agent 可能只返回文字，不调用生图 Tool。

直接在 IDE 中运行 `main.py`，或者执行：

```powershell
& 'D:\A_Python\conda_envs\edu_rag\python.exe' 'D:\A_Python\跟着黑马学ai\Edu_RAG\langchain\story_agent\main.py'
```

正常执行时会看到类似进度：

```text
[Agent] 已收到请求，正在判断下一步操作……
[进度 1/2] 正在读取模型手册并优化正面、负面提示词……
[进度 1/2] 提示词优化完成。
[进度 2/2] 正在调用已配置的本地生图模型，请稍候……
[进度 2/2] 本地生图模型已完成处理。
```

主程序使用两路流式事件：

```python
agent.stream(agent_input, stream_mode=["messages", "updates"])
```

- `messages`：逐段打印主 Agent 的模型输出，实现真正的 token 流式显示；
- `updates`：读取 Tool 调用和完成事件，显示提示词优化、Forge 生图等执行进度；
- 只打印 `langgraph_node == "model"` 的文本片段，避免把提示词优化器在 Tool 内部产生的结构化 JSON 一并输出；
- `run_agent()` 已经负责打印模型回答，主程序不要再 `print(run_agent(...))`，否则最终回答会重复出现。

### 图片类型与尺寸

两个生图 Tool 都会要求 Agent 为每张图片选择 `image_type`，不让模型自由填写宽高：

```text
WAI character → 1024×1400；scene → 1400×1024
千问 character → 1024×1408；scene → 1408×1024
```

上面是本地 Forge 的显存友好尺寸。云端 Seedream 保持相同方向，使用对应的 2K 尺寸：

```text
image_type="character" → 人物剧情，1664×2496 竖图
image_type="scene"     → 场景剧情，2496×1664 横图
```

- 人物是画面重点，例如人物特写、全身动作或角色互动：选择 `character`；
- 环境和横向空间是重点，例如城市、房间全景或自然景观：选择 `scene`。

尺寸选择发生在每次生图 Tool 调用时，因此连续生成不同类型的图片时可以自动切换比例。

## 4. 选择模型与参考图模式

WAI 普通文生图：

```python
LOCAL_IMAGE_MODEL = "wai"
LOCAL_IMAGE_MODE = "txt2img"
```

WAI OpenPose：

```python
LOCAL_IMAGE_MODEL = "wai"
LOCAL_IMAGE_MODE = "openpose"
```

千问文生图或图生图：

```python
LOCAL_IMAGE_MODEL = "qwen_image_2_1"
LOCAL_IMAGE_PORT = 6006
LOCAL_IMAGE_MODE = "txt2img"  # 改成 "img2img" 就启用参考图
```

模式由 `main.py` 的 `LOCAL_IMAGE_MODE` 在程序启动时固定，Agent 不负责选择，也看不到参考图路径。选择 `openpose` 或 `img2img` 后，每次 Tool 真正执行都会直接在终端询问本次参考图路径，不会复用上一张图片。WAI 的参考图用于提取 OpenPose 骨架；千问的参考图会作为图像条件传给 Qwen-Image-2.1。

## 5. 测试完整链路

公开仓库直接通过 `main.py` 验证完整链路：

```text
用户请求 → Agent 选择 Tool → Prompt Optimizer → 本地模型或云端 API → 保存图片
```

按第 2 节配置环境变量，按第 4 节选择本地模型与参考图模式。如果使用 Forge，先确认 Forge 已通过 `--api` 启动。然后在项目根目录运行：

```powershell
python main.py
```

新建一个临时故事，再输入一条明确的生图请求，例如：

```text
请先优化提示词，再调用本地生图工具，生成一张雪原车站的横向场景插画。
```

该流程会真实调用 DeepSeek 和所选的生图后端，因此可能产生 API 费用并生成图片。如果只想排查某个 Tool，按下一节单独运行对应文件。

## 6. 单独测试各 Tool

### 提示词优化 Tool

直接运行：

```text
tools/prompt_optimizer_tool.py
```

它会读取文件底部的测试输入，真实调用一次 DeepSeek，并打印结构化结果和耗时。

### 本地/自建服务器生图 Tool

直接运行：

```text
tools/local_image_tool.py
```

它会先检查 Forge、采样器、调度器和 ControlNet 资源，然后继续执行文件底部的生图自测。运行前应先检查测试提示词和 `TEST_POSE_IMAGE`。

## 7. 输出位置

本项目生成的图片保存在：

```text
story_agent/pictures/
```

Forge 自己也可能在它的输出目录保存一份图片。出现两份文件是正常现象，不是重复调用。

每次生成结果会返回：

```text
图片绝对路径
seed
图片尺寸
生成耗时
ControlNet 是否启用
```

`seed=-1` 表示随机种子。需要复现图片时，把返回的 seed 写回测试配置。

## 8. 常用修改位置

| 需求 | 修改位置 |
|---|---|
| 修改主 Agent 测试提示词 | `main.py` 底部的 `test_prompt` |
| 修改主 Agent 系统提示词 | `prompt_guides/agent_system_promt.txt` |
| 修改某模型使用哪套提示词规则 | 该模型配置中的 `prompt_system_file/prompt_guide_file` |
| 修改本地 tags 提示词规则 | `prompt_guides/llm_system_prompt_local.txt` |
| 修改自然语言提示词规则 | `prompt_guides/llm_system_prompt_api.txt` |
| 选择本地模型、端口和模式 | `main.py` 底部的 `local_image_model/local_image_port/local_image_mode` |
| 修改 DeepSeek 模型 | `main.py` 中的 `MODEL_NAME` |
| 修改 WAI 参数、尺寸、checkpoint、OpenPose | `tools/localimgconfig/wai.py` |
| 修改千问参数、尺寸和端口 | `tools/localimgconfig/qwen_image_2_1.py` |
| 注册或移除本地模型 | `tools/localimgconfig/__init__.py` |
| 修改 Seedream API 参数 | `tools/apiimgconfig/seedream.py` |
| 修改 Flux API 参数 | `tools/apiimgconfig/flux.py` |
| 注册或移除云端模型 API | `tools/apiimgconfig/__init__.py` |
| 修改 WAI 模型提示词规则 | `prompt_guides/WAI_Illustrious_v15_Public_Guide.md` |

## 9. 如何注册新的生图模型

先建立一个简单概念：**配置文件描述“这个模型是谁、住在哪里、默认参数和提示词模板是什么”，Tool 描述“请求怎样发送、结果怎样取回”。**

如果新模型和已有模型使用完全相同的接口协议，一般只需新增配置文件；如果请求体、鉴权或返回结果不同，还要给 Tool 增加一个协议适配器。

### 9.1 注册本地或自建服务器模型

“本地模型”不一定真的运行在本机。只要模型由自己启动服务、自己控制端口，就放在 `tools/localimgconfig/`；远程 GPU 服务器上的千问也属于这一类。

第一步，在 `tools/localimgconfig/` 中为模型新建独立文件，例如 `my_forge_model.py`：

```python
from .base import LocalImageModelConfig


MY_FORGE_MODEL_CONFIG = LocalImageModelConfig(
    key="my_forge_model",              # 调用时填写的 model_name
    display_name="My Forge Model",      # 日志里显示的名字
    protocol="forge",                   # 当前支持 forge / qwen
    default_port=7860,
    txt2img_path="/sdapi/v1/txt2img",
    image_sizes={
        "character": (1024, 1400),
        "scene": (1400, 1024),
    },
    prompt_system_file="llm_system_prompt_local.txt",
    prompt_guide_file="WAI_Illustrious_v15_Public_Guide.md",
    supports_negative_prompt=True,
    supported_modes=("txt2img",),
    checkpoint="模型文件名.safetensors",
    request_defaults={
        "sampler_name": "Euler a",
        "scheduler": "automatic",
        "steps": 30,
        "cfg_scale": 6.0,
        "n_iter": 1,
        "batch_size": 1,
        "send_images": True,
        "save_images": True,
    },
)
```

第二步，在 `tools/localimgconfig/__init__.py` 中导入并注册：

```python
from .my_forge_model import MY_FORGE_MODEL_CONFIG

LOCAL_IMAGE_MODELS = {
    # 原有模型……
    MY_FORGE_MODEL_CONFIG.key: MY_FORGE_MODEL_CONFIG,
}
```

第三步，在 `main.py` 里选择：

```python
local_image_model = "my_forge_model"
local_image_port = None       # None 使用配置里的 default_port
local_image_mode = "txt2img"
```

模式规则：

- WAI/Forge 普通生成使用 `txt2img`；需要姿势参考时使用 `openpose`。
- 千问普通生成使用 `txt2img`；需要参考图编辑时使用 `img2img`。
- 选择 `openpose` 或 `img2img` 后，Tool 每次执行都会重新询问参考图路径。
- 远程模型通常先通过 SSH 把远程端口映射成本机端口，再把该本机端口传给 `local_image_port`。

如果新服务既不兼容 Forge，也不兼容当前千问的 `/txt2img`、`/img2img` 协议，就不能只写配置；还需要在 `local_image_tool.py` 中增加新的 payload 构造和响应解析逻辑。

### 9.2 注册云端模型 API

第一步，在 `tools/apiimgconfig/` 中为云端模型新建独立文件，例如 `my_cloud_model.py`：

```python
from .base import CloudImageApiConfig


MY_CLOUD_CONFIG = CloudImageApiConfig(
    key="my_cloud",
    display_name="My Cloud Image Model",
    model="平台要求的模型 ID",
    endpoint="https://example.com/v1/images/generations",
    protocol="direct_url",       # 当前已有 direct_url / async_task
    image_sizes={
        "character": (1024, 1536),
        "scene": (1536, 1024),
    },
    prompt_system_file="llm_system_prompt_api.txt",
    prompt_guide_file=None,
    supports_negative_prompt=False,
    request_defaults={
        "response_format": "url",
    },
)
```

第二步，在 `tools/apiimgconfig/__init__.py` 中导入并注册：

```python
from .my_cloud_model import MY_CLOUD_CONFIG

CLOUD_IMAGE_APIS = {
    # 原有 API……
    MY_CLOUD_CONFIG.key: MY_CLOUD_CONFIG,
}
```

第三步，调用云端 Tool 时传模型短名称：

```python
api_model = "my_cloud"
```

`api_model` 使用普通字符串，合法值由 `CLOUD_IMAGE_APIS` 注册表校验，因此新增模型后不需要再修改 Tool 的类型注解。

`prompt_system_file` 和可选的 `prompt_guide_file` 都指向 `prompt_guides/` 目录中的文件。`supports_negative_prompt=False` 时，优化器会强制清空负面提示词，避免把无效参数继续传下去。

云端 API 尤其要检查以下四项是否和已有协议一致：

1. API Key 放在哪个请求头；
2. 请求 JSON 使用哪些字段；
3. 接口是立即返回图片，还是先返回任务 ID；
4. 最终图片 URL 位于返回 JSON 的哪个字段。

只有这四项都兼容时才能直接复用现有协议。否则应在 `api_image_tool.py` 中增加新的调用函数和协议分支，不能只改 endpoint 就假定可以工作。API Key 始终放在环境变量或 `.env`，不要写进模型配置文件。

### 9.3 注册后先做什么检查

不要立刻让 Agent 自动调用，先单独检查：

```python
from tools.localimgconfig import get_local_image_config
from tools.apiimgconfig import get_cloud_api_config

print(get_local_image_config("wai"))
print(get_cloud_api_config("seedream"))
```

确认模型名、端口、接口地址、尺寸、提示词文件和默认参数正确后，再按第 5 节运行 `main.py` 测试完整链路。

## 10. 常见问题

### 缺少 dpsk_url 或 DEEPSEEK_API_KEY

说明环境变量没有传入当前运行进程。检查 IDE Run Configuration，或者在同一个 PowerShell 会话中设置环境变量后再运行。

### 连不上 Forge

确认：

- Forge 已启动；
- 启动参数包含 `--api`；
- 实际端口是 `7860`；
- 浏览器或防火墙没有阻断本地接口。

### ControlNet 模型或预处理器缺失

直接运行 `local_image_tool.py` 查看体检结果，再核对：

```text
预处理器：openpose_full
ControlNet 模型：diffusion_pytorch_model [d0333a45]
```

### 输入参考图后提示文件不存在

使用完整的本地绝对路径。路径外层有引号也可以，程序会自动去除；路径无效时会要求重新输入。

### Agent 没有生图

当前 Agent 只在用户明确提出生图要求时调用工具。请在 `test_prompt` 中写明“生成图片”“画一张插画”等指令。

## 11. V1 完成范围

V1 已经完成以下核心闭环：

- 主 Agent 能根据用户意图编写或续写故事，并自主选择提示词优化、本地生图或云端生图 Tool；
- Prompt Optimizer 会根据目标后端和模型注册配置，自动选择对应的系统提示词与模型手册；
- 本地后端支持 WAI 文生图、WAI OpenPose、Qwen-Image 文生图与 img2img；
- 云端后端支持 Seedream 和 Flux，并能处理立即返回与异步轮询两种 API 协议；
- 支持主 Agent 文本、Tool 调用和生图阶段的流式进度输出；
- 支持多轮对话、随机 `session_id`、故事名称选择、JSON 持久化和程序重启后恢复；
- 每个故事拥有独立目录，`conversation.json` 与本地/云端生成图片统一归档；
- 模型、端口、尺寸、提示词模板和 API 协议通过注册配置管理，便于继续扩展新模型。

因此，当前版本可以作为：

- LangChain Agent、Tool、Memory 与持久化机制的综合学习项目；
- 可在本机实际使用的单用户故事插画工具；
- 展示 Agent 工作流、模型路由和工程拆分能力的作品集 MVP。

## 12. 已知限制与后续计划

以下内容属于 V1 之后的工程化迭代，不作为当前版本继续延期的理由。

### 12.1 自动化测试

目前主要依赖手动链路测试，尚未建立正式测试套件。后续优先覆盖：

- 故事创建、会话隔离、JSON 保存与重启恢复；
- WAI、Qwen-Image、Seedream、Flux 的模型配置与路由；
- OpenPose/img2img 参考图输入；
- 本地与云端图片输出目录；
- 网络异常、配置缺失、API 拒绝和损坏存档等失败路径。

### 12.2 长会话上下文管理

当前会把完整历史消息恢复给 Agent。故事持续很长后，可能增加延迟、Token 消耗并超过模型上下文限制。后续计划采用：

```text
较早历史 → 压缩为角色、世界观和剧情状态摘要
最近若干轮 → 保留完整消息
关键设定   → 单独结构化保存
```

### 12.3 数据库存储

当前 JSON 方案直观、便于学习和本地调试，但只适合单进程使用，不处理并发写入和复杂检索。需要多用户或长期运行时，可迁移到 SQLite/PostgreSQL checkpointer，并保留现有 `story_name + session_id` 设计。

### 12.4 异常恢复与可观测性

当前已经处理常见网络和 Tool 错误，但还需要进一步补充：

- 单轮失败后不中断整个聊天循环；
- 可控的重试、退避和超时策略；
- 使用 `logging` 代替分散的 `print()`；
- 记录模型、Tool、耗时和错误类型，便于排查问题；
- 云端付费调用的额度提醒或二次确认。

### 12.5 Web 与多用户部署

当前版本是本地 CLI，不包含 Web UI、用户认证、权限隔离、限流和并发控制。如果后续需要部署，可增加 FastAPI/前端界面，并让每个用户只能访问自己的故事和图片。

### 12.6 当前数据约束

- `history_data/` 包含真实对话、图片和本地绝对路径，应作为运行时私有数据，不应提交到公开仓库；
- `history_data` 下旧演示遗留的散落 JSON 不会自动迁移，程序只扫描包含 `conversation.json` 的故事文件夹；
- API Key 必须继续放在环境变量或本地 `.env` 中，不能写入代码、JSON 存档或提交记录。
