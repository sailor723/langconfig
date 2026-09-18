import json
import os

# 定义 Notebook 5 的内容
notebook_5_content = {
 "cells": [
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "# 第五部分：DeepAgent Skills 与渐进式披露 (Progressive Disclosure)\n",
    "### *Alex 的终极方案：拥有“翻书”能力的智能体*\n",
    "\n",
    "Alex 终于意识到，把所有规则塞进脑子（Mega-Prompt）是行不通的。他采用了 DeepAgent 的 **Skills** 架构。\n",
    "\n",
    "**核心原理：**\n",
    "1. **元数据注入 (Metadata Injection)**：Agent 初始化时只加载技能的名字和描述。这就像给 Agent 一张**“技能目录”**。\n",
    "2. **按需读取 (On-demand Reading)**：只有当 Agent 认为某个技能对当前任务有用时，它才会调用内置工具去读取 `SKILL.md` 的**“详细手册”**。\n",
    "\n",
    "在这个笔记本中，我们将：\n",
    "1. **实现流式追踪器**：实时截获并打印 Agent 接收到的 System Prompt，看它是如何动态变化的。\n",
    "2. **流式任务执行 (Streaming)**：由于复杂任务运行时间较长，我们将开启流式模式，实时观察 Agent 的思考轨迹。\n",
    "3. **验证性能**：看 Agent 如何在不浪费 Token 的情况下，精准完成财务与市场的跨部门分析。"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "import os\n",
    "import pandas as pd\n",
    "from dotenv import load_dotenv\n",
    "from langchain.agents import create_agent\n",
    "from langchain.chat_models import init_chat_model\n",
    "from langchain_core.tools import tool\n",
    "from langchain_experimental.utilities import PythonREPL\n",
    "from langchain_core.callbacks import BaseCallbackHandler\n",
    "\n",
    "load_dotenv(override=True)\n",
    "\n",
    "# 1. 准备技能目录 (如果之前没有生成)\n",
    "os.makedirs(\"skills/finance_pro\", exist_ok=True)\n",
    "os.makedirs(\"skills/market_wizard\", exist_ok=True)\n",
    "\n",
    "finance_skill = \"\"\"---\n",
    "name: finance_pro\n",
    "description: 专业财务技能。处理各地区(EMEA, US, APAC)的专项税率逻辑，并能识别表现不佳(UNDER_PERFORMING)的警告。\n",
    "---\n",
    "# 财务核算规则\n",
    "- 税率：EMEA(15%), US(8%), APAC(12%)。\n",
    "- 逻辑：如果一个 Region 的总收入低于 500，必须在总结中明确标出 'UNDER_PERFORMING'。\n",
    "\"\"\"\n",
    "\n",
    "market_skill = \"\"\"---\n",
    "name: market_wizard\n",
    "description: 市场分析技能。用于清洗带符号的金额字符串，并将 market 映射为 Region。\n",
    "---\n",
    "# 市场清洗规则\n",
    "- 将 'market' 列重命名为 'Region'。\n",
    "- 必须移除价格列中的 '$' 和 ',' 并转为 float。\n",
    "- 输出必须包含一段中文总结。\n",
    "\"\"\"\n",
    "\n",
    "with open(\"skills/finance_pro/SKILL.md\", \"w\", encoding=\"utf-8\") as f: f.write(finance_skill)\n",
    "with open(\"skills/market_wizard/SKILL.md\", \"w\", encoding=\"utf-8\") as f: f.write(market_skill)\n",
    "\n",
    "print(\"✅ 技能文件夹已就绪。\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 2. 实现“深度窃听器” (Deep Tracer)\n",
    "我们将创建一个自定义回调，它会在 Agent 每次请求 LLM 时打印出发送过去的 System Prompt。这是观察“渐进式披露”最好的窗口。"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "class DeepAgentTracer(BaseCallbackHandler):\n",
    "    def on_chat_model_start(self, serialized, messages, **kwargs):\n",
    "        print(\"\\n\" + \"🔍\"*10 + \" [DEEP TRACE: 正在检查发送给 AI 的提示词] \" + \"🔍\"*10)\n",
    "        for msg in messages:\n",
    "            if msg.type == \"system\":\n",
    "                # 打印前 1000 个字符，你会在这里看到 DeepAgent 自动注入的 <available_skills> 列表\n",
    "                print(f\"[SYSTEM PROMPT]:\\n{msg.content}\\n\")\n",
    "        print(\"-\"*80 + \"\\n\")\n",
    "\n",
    "    def on_tool_start(self, serialized, input_str, **kwargs):\n",
    "        print(f\"🛠️  [工具调用]: {serialized['name']}\")\n",
    "        print(f\"📦 [输入参数]: {input_str}\\n\")\n",
    "\n",
    "tracer = DeepAgentTracer()\n",
    "print(\"追踪器已激活。\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 3. 初始化流式 Agent\n",
    "我们将开启流式模式，这样当 Agent 在进行长链条推理时，我们能实时看到输出。"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "model = init_chat_model(\n",
    "    model=\"agnes-2.0-flash\",\n",
    "    model_provider=\"openai\",\n",
    "    base_url=os.getenv(\"AGNES_BASE_URL\"),\n",
    "    api_key=os.getenv(\"AGNES_API_KEY\"),\n",
    "    streaming=True # 开启流式\n",
    ")\n",
    "\n",
    "repl = PythonREPL()\n",
    "\n",
    "@tool\n",
    "def python_analyst(code: str):\n",
    "    \"\"\"执行 Python 分析。你可以访问 enterprise_data/ 下的文件。\"\"\"\n",
    "    return repl.run(code)\n",
    "\n",
    "# 这里的 system_prompt 非常精简，Alex 不再背书，只是充当向导\n",
    "CLEAN_SYSTEM_PROMPT = \"\"\"\n",
    "你是一位 GlobalCorp 专家助手。\n",
    "你拥有专业技能库。当你收到任务时，请先检查可用技能列表。\n",
    "如果需要具体部门的规则（如财务或市场），请务必先使用内置的 read_skill 工具阅读相关的 SKILL.md 手册。\n",
    "\"\"\"\n",
    "\n",
    "agent = create_agent(\n",
    "    model,\n",
    "    tools=[python_analyst],\n",
    "    system_prompt=CLEAN_SYSTEM_PROMPT,\n",
    "    skills=\"./skills\"  # DeepAgent 自动扫描此目录并注入元数据\n",
    ")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 4. 执行并观察：渐进式披露的实况转播\n",
    "请注意观察：\n",
    "1. **第一步**：你会看到 LLM 的输入中包含了技能的 `name` 和 `description`，但没有具体规则。\n",
    "2. **第二步**：你会看到 Agent 发现需要财务规则，调用了 `read_skill`。\n",
    "3. **第三步**：再次发送给 LLM 的输入中，`finance_pro` 的全文被加载了进来。"
   ]
  },
  {
   "cell_type": "code",
   "execution_count": None,
   "metadata": {},
   "outputs": [],
   "source": [
    "query = \"请读取 modern_marketing.csv，应用正确的财务税率计算净收入，并检查是否有 Region 表现不佳？\"\n",
    "inputs = {\"messages\": [(\"human\", query)]}\n",
    "config = {\"callbacks\": [tracer], \"recursion_limit\": 20}\n",
    "\n",
    "print(\"--- 开始流式执行 (带深度追踪) ---\\n\")\n",
    "\n",
    "# 使用 .stream 方法获取流式输出\n",
    "for chunk in agent.stream(inputs, config=config):\n",
    "    # 在这里，我们可以根据 chunk 的类型决定如何显示\n",
    "    # DeepAgent 编译后的图通常会返回包含 messages 的字典\n",
    "    if \"messages\" in chunk:\n",
    "        last_msg = chunk[\"messages\"][-1]\n",
    "        # 打印 AI 的实时文本内容\n",
    "        if hasattr(last_msg, \"content\") and last_msg.content:\n",
    "            print(f\"[AI]: {last_msg.content}\")"
   ]
  },
  {
   "cell_type": "markdown",
   "metadata": {},
   "source": [
    "## 5. 结论：为什么 Alex 终于成功了？\n",
    "\n",
    "观察追踪日志，你会发现 Skills 模式的三个核心优势：\n",
    "\n",
    "1. **Token 效率**：初始请求非常短（只有目录）。比起 Notebook 4 的全量注入，我们节省了大量的“背景 Token”。\n",
    "2. **零干扰**：如果用户问的是天气，Agent 根本不会去读财务手册，从而避免了不相关规则带来的幻觉。\n",
    "3. **解耦与动态性**：如果你现在去修改 `skills/finance_pro/SKILL.md`，Agent 在下一次调用 `read_skill` 时会立刻获得新知识，而无需重启或重新训练模型。\n",
    "\n",
    "### Alex 的最终寄语：\n",
    "“不要试图让 Agent 成为一个全知全能的神。要让它成为一个善于学习、懂得按需获取知识的**专业工作者**。这就是 DeepAgent Skills 的真谛。”"
   ]
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": ".venv",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 3
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython3",
   "version": "3.13.12"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}

# 写入文件
with open("05_DeepAgent_Skills_Streaming.ipynb", "w", encoding="utf-8") as f:
    json.dump(notebook_5_content, f, ensure_ascii=False, indent=1)

print("✅ 终极版 Notebook 5 已生成！请尽情享受流式追踪带来的震撼。")