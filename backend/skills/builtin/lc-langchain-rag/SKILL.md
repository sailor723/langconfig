---
name: "Langchain Rag（LangChain 检索增强生成）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langchain-rag/SKILL.md
description: >-
  构建任何检索增强生成（RAG）系统时都要调用本技能。覆盖文档加载器、RecursiveCharacterTextSplitter、
  嵌入（OpenAI），以及向量库（Chroma、FAISS、Pinecone）。
tags:
  - "langchain"
  - "rag"
  - "langchain-skills"
  - "skills"
triggers:
  - "要构建检索增强生成（RAG）系统时"
  - "需要选文档加载器、文本分割器、嵌入或向量库时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "bash"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langchain-rag`（MIT，原样收录于
> `vendor/upstream-skills/langchain-skills/skills/langchain-rag/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


<overview>
检索增强生成（RAG）通过从外部知识源取回相关上下文，来增强 LLM 的响应。

**流水线：**
1. **索引（Index）**：加载 → 分块 → 嵌入 → 存储
2. **检索（Retrieve）**：查询 → 嵌入 → 搜索 → 返回文档
3. **生成（Generate）**：文档 + 查询 → LLM → 响应

**关键组件：**
- **文档加载器（Document Loaders）**：从文件、Web、数据库接入数据
- **文本分割器（Text Splitters）**：把文档切成块
- **嵌入（Embeddings）**：把文本转成向量
- **向量库（Vector Stores）**：存储并搜索嵌入
</overview>

<vectorstore-selection>

| 向量库 | 适用场景 | 持久化 |
|--------------|----------|-------------|
| **InMemory** | 测试 | 仅内存 |
| **FAISS** | 本地、高性能 | 磁盘 |
| **Chroma** | 开发 | 磁盘 |
| **Pinecone** | 生产、托管 | 云端 |

</vectorstore-selection>

---

## 完整 RAG 流水线

<ex-basic-rag-setup>
<python>
端到端的 RAG 流水线：加载文档、切成块、嵌入、存储、检索，然后生成响应。

```python
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# 1. Load documents
docs = [
    Document(page_content="LangChain is a framework for LLM apps.", metadata={}),
    Document(page_content="RAG = Retrieval Augmented Generation.", metadata={}),
]

# 2. Split documents
splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
splits = splitter.split_documents(docs)

# 3. Create embeddings and store
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = InMemoryVectorStore.from_documents(splits, embeddings)

# 4. Create retriever
retriever = vectorstore.as_retriever(search_kwargs={"k": 4})

# 5. Use in RAG
model = ChatOpenAI(model="gpt-4.1")
query = "What is RAG?"
relevant_docs = retriever.invoke(query)

context = "\n\n".join([doc.page_content for doc in relevant_docs])
response = model.invoke([
    {"role": "system", "content": f"Use this context:\n\n{context}"},
    {"role": "user", "content": query},
])
```
</python>
<typescript>
端到端的 RAG 流水线：加载文档、切成块、嵌入、存储、检索，然后生成响应。

```typescript
import { ChatOpenAI, OpenAIEmbeddings } from "@langchain/openai";
import { MemoryVectorStore } from "@langchain/classic/vectorstores/memory";
import { RecursiveCharacterTextSplitter } from "@langchain/textsplitters";
import { Document } from "@langchain/core/documents";

// 1. Load documents
const docs = [
  new Document({ pageContent: "LangChain is a framework for LLM apps.", metadata: {} }),
  new Document({ pageContent: "RAG = Retrieval Augmented Generation.", metadata: {} }),
];

// 2. Split documents
const splitter = new RecursiveCharacterTextSplitter({ chunkSize: 500, chunkOverlap: 50 });
const splits = await splitter.splitDocuments(docs);

// 3. Create embeddings and store
const embeddings = new OpenAIEmbeddings({ model: "text-embedding-3-small" });
const vectorstore = await MemoryVectorStore.fromDocuments(splits, embeddings);

// 4. Create retriever
const retriever = vectorstore.asRetriever({ k: 4 });

// 5. Use in RAG
const model = new ChatOpenAI({ model: "gpt-4.1" });
const query = "What is RAG?";
const relevantDocs = await retriever.invoke(query);

const context = relevantDocs.map(doc => doc.pageContent).join("\n\n");
const response = await model.invoke([
  { role: "system", content: `Use this context:\n\n${context}` },
  { role: "user", content: query },
]);
```
</typescript>
</ex-basic-rag-setup>

---

## 文档加载器

<ex-loading-pdf>
<python>
加载一个 PDF 文件，把每一页提取成一个独立的文档。

```python
from langchain_community.document_loaders import PyPDFLoader

loader = PyPDFLoader("./document.pdf")
docs = loader.load()
print(f"Loaded {len(docs)} pages")
```
</python>
<typescript>
加载一个 PDF 文件，把每一页提取成一个独立的文档。

```typescript
import { PDFLoader } from "@langchain/community/document_loaders/fs/pdf";

const loader = new PDFLoader("./document.pdf");
const docs = await loader.load();
console.log(`Loaded ${docs.length} pages`);
```
</typescript>
</ex-loading-pdf>

<ex-loading-web-pages>
<python>
抓取一个 Web URL 的内容并解析成文档。

```python
from langchain_community.document_loaders import WebBaseLoader

loader = WebBaseLoader("https://docs.langchain.com")
docs = loader.load()
```
</python>
<typescript>
用 Cheerio 抓取一个 Web URL 的内容并解析成文档。

```typescript
import { CheerioWebBaseLoader } from "@langchain/community/document_loaders/web/cheerio";

const loader = new CheerioWebBaseLoader("https://docs.langchain.com");
const docs = await loader.load();
```
</typescript>
</ex-loading-web-pages>

<ex-loading-directory>
<python>
用 glob 模式加载一个目录下的全部文本文件。

```python
from langchain_community.document_loaders import DirectoryLoader, TextLoader

# Load all text files from directory
loader = DirectoryLoader(
    "path/to/documents",
    glob="**/*.txt",  # Pattern for files to load
    loader_cls=TextLoader
)
docs = loader.load()
```
</python>
</ex-loading-directory>

---

## 文本分割

<ex-text-splitting>
<python>
用 RecursiveCharacterTextSplitter 把文档切成块，块大小与重叠都可配置。

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,        # Characters per chunk
    chunk_overlap=200,      # Overlap for context continuity
    separators=["\n\n", "\n", " ", ""],  # Split hierarchy
)

splits = splitter.split_documents(docs)
```
</python>
</ex-text-splitting>

---

## 向量库

<ex-chroma-vectorstore>
<python>
创建一个可持久化的 Chroma 向量库，并从磁盘重新加载它。

```python
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

vectorstore = Chroma.from_documents(
    documents=splits,
    embedding=OpenAIEmbeddings(),
    persist_directory="./chroma_db",
    collection_name="my-collection",
)

# Load existing
vectorstore = Chroma(
    persist_directory="./chroma_db",
    embedding_function=OpenAIEmbeddings(),
    collection_name="my-collection",
)
```
</python>
<typescript>
创建一个连接到运行中 Chroma 服务器的 Chroma 向量库。

```typescript
import { Chroma } from "@langchain/community/vectorstores/chroma";
import { OpenAIEmbeddings } from "@langchain/openai";

const vectorstore = await Chroma.fromDocuments(
  splits,
  new OpenAIEmbeddings(),
  { collectionName: "my-collection", url: "http://localhost:8000" }
);
```
</typescript>
</ex-chroma-vectorstore>

<ex-faiss-vectorstore>
<python>
创建一个 FAISS 向量库，存到磁盘，再重新加载。

```python
from langchain_community.vectorstores import FAISS

vectorstore = FAISS.from_documents(splits, embeddings)
vectorstore.save_local("./faiss_index")

# Only load FAISS indexes that you created and fully control.
# The Python FAISS loader uses pickle-backed metadata, so never load
# downloaded, shared, or otherwise untrusted index directories.
loaded = FAISS.load_local(
    "./faiss_index",
    embeddings,
    allow_dangerous_deserialization=True,
)
```
</python>
<typescript>
创建一个 FAISS 向量库，存到磁盘，再重新加载。

```typescript
import { FaissStore } from "@langchain/community/vectorstores/faiss";

const vectorstore = await FaissStore.fromDocuments(splits, embeddings);
await vectorstore.save("./faiss_index");

const loaded = await FaissStore.load("./faiss_index", embeddings);
```
</typescript>
</ex-faiss-vectorstore>

---

## 检索

<ex-similarity-search>
<python>
执行相似度搜索，取回带相关度分数的结果。

```python
# Basic search
results = vectorstore.similarity_search(query, k=5)

# With scores
results_with_score = vectorstore.similarity_search_with_score(query, k=5)
for doc, score in results_with_score:
    print(f"Score: {score}, Content: {doc.page_content}")
```
</python>
<typescript>
执行相似度搜索，取回带相关度分数的结果。

```typescript
// Basic search
const results = await vectorstore.similaritySearch(query, 5);

// With scores
const resultsWithScore = await vectorstore.similaritySearchWithScore(query, 5);
for (const [doc, score] of resultsWithScore) {
  console.log(`Score: ${score}, Content: ${doc.pageContent}`);
}
```
</typescript>
</ex-similarity-search>

<ex-mmr-search>
<python>
用 MMR（Maximal Marginal Relevance，最大边际相关性）在搜索结果里平衡相关性与多样性。

```python
# MMR balances relevance and diversity
retriever = vectorstore.as_retriever(
    search_type="mmr",
    search_kwargs={"fetch_k": 20, "lambda_mult": 0.5, "k": 5},
)
```
</python>
</ex-mmr-search>

<ex-metadata-filtering>
<python>
给文档加上元数据，并按元数据属性过滤搜索结果。

```python
# Add metadata when creating documents
docs = [
    Document(
        page_content="Python programming guide",
        metadata={"language": "python", "topic": "programming"}
    ),
]

# Search with filter
results = vectorstore.similarity_search(
    "programming",
    k=5,
    filter={"language": "python"}  # Only Python docs
)
```
</python>
</ex-metadata-filtering>

<ex-rag-with-agent>
<python>
创建一个把 RAG 当作工具来回答问题的智能体。

```python
from langchain.agents import create_agent
from langchain.tools import tool

@tool
def search_docs(query: str) -> str:
    """Search documentation for relevant information."""
    docs = retriever.invoke(query)
    return "\n\n".join([d.page_content for d in docs])

agent = create_agent(
    model="gpt-4.1",
    tools=[search_docs],
)

result = agent.invoke({
    "messages": [{"role": "user", "content": "How do I create an agent?"}]
})
```
</python>
<typescript>
创建一个把 RAG 当作工具来回答问题的智能体。

```typescript
import { createAgent } from "langchain";
import { tool } from "@langchain/core/tools";
import { z } from "zod";

const searchDocs = tool(
  async (input) => {
    const docs = await retriever.invoke(input.query);
    return docs.map(d => d.pageContent).join("\n\n");
  },
  {
    name: "search_docs",
    description: "Search documentation for relevant information.",
    schema: z.object({ query: z.string() }),
  }
);

const agent = createAgent({
  model: "gpt-4.1",
  tools: [searchDocs],
});

const result = await agent.invoke({
  messages: [{ role: "user", content: "How do I create an agent?" }],
});
```
</typescript>
</ex-rag-with-agent>

<boundaries>
### 你能配置什么

- 块大小 / 重叠
- 嵌入模型
- 结果数量（k）
- 元数据过滤器
- 搜索算法：相似度、MMR

### 你不能配置什么

- 嵌入维度（由模型决定）
- 在同一个库里混用不同模型的嵌入
</boundaries>

<fix-chunk-size>
<python>
块大小 500-1500 通常比较合适。

```python
# WRONG: Too small (loses context) or too large (hits limits)
splitter = RecursiveCharacterTextSplitter(chunk_size=50)
splitter = RecursiveCharacterTextSplitter(chunk_size=10000)

# CORRECT
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
```
</python>
<typescript>
块大小 500-1500 通常比较合适。

```typescript
// WRONG: Too small or too large
const splitter = new RecursiveCharacterTextSplitter({ chunkSize: 50 });

// CORRECT
const splitter = new RecursiveCharacterTextSplitter({ chunkSize: 1000, chunkOverlap: 200 });
```
</typescript>
</fix-chunk-size>

<fix-chunk-overlap>
<python>
用重叠（块大小的 10-20%）来维持边界处的上下文。

```python
# WRONG: No overlap - context breaks at boundaries
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=0)

# CORRECT: 10-20% overlap
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
```
</python>
</fix-chunk-overlap>

<fix-persist-vectorstore>
<python>
用可持久化的向量库代替内存向量库，以免数据丢失。

```python
# WRONG: InMemory - lost on restart
vectorstore = InMemoryVectorStore.from_documents(docs, embeddings)

# CORRECT
vectorstore = Chroma.from_documents(docs, embeddings, persist_directory="./chroma_db")
```
</python>
<typescript>
用可持久化的向量库代替内存向量库，以免数据丢失。

```typescript
// WRONG: Memory - lost on restart
const vectorstore = await MemoryVectorStore.fromDocuments(docs, embeddings);

// CORRECT
const vectorstore = await Chroma.fromDocuments(docs, embeddings, { collectionName: "my-collection" });
```
</typescript>
</fix-persist-vectorstore>

<fix-consistent-embeddings>
<python>
索引与查询必须使用同一个嵌入模型。

```python
# WRONG: Different embeddings for index and query - incompatible!
vectorstore = Chroma.from_documents(docs, OpenAIEmbeddings(model="text-embedding-3-small"))
retriever = vectorstore.as_retriever(embeddings=OpenAIEmbeddings(model="text-embedding-3-large"))

# CORRECT: Same model
embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
vectorstore = Chroma.from_documents(docs, embeddings)
retriever = vectorstore.as_retriever()  # Uses same embeddings
```
</python>
<typescript>
索引与查询必须使用同一个嵌入模型。

```typescript
const embeddings = new OpenAIEmbeddings({ model: "text-embedding-3-small" });
const vectorstore = await Chroma.fromDocuments(docs, embeddings);
const retriever = vectorstore.asRetriever();  // Uses same embeddings
```
</typescript>
</fix-consistent-embeddings>

<fix-faiss-deserialization>
<python>
只对可信的本地索引开启 FAISS 反序列化。Python 的 FAISS 索引带有 pickle 形式的元数据，而不可信的 pickle 文件在加载时可以执行任意代码。

```python
# WRONG: Loading a downloaded, shared, cloud-hosted, or third-party-controlled
# FAISS index with dangerous deserialization enabled.
loaded_store = FAISS.load_local(
    "./untrusted_faiss_index",
    embeddings,
    allow_dangerous_deserialization=True,
)

# CORRECT: Only opt in when the index directory was created by you and has
# remained under your control.
loaded_store = FAISS.load_local(
    "./faiss_index",
    embeddings,
    allow_dangerous_deserialization=True,
)
```

如果你无法保证一个已持久化索引的来源，就不要用 `allow_dangerous_deserialization=True` 加载它。改用可信的源文档重建索引，或者换一个对不可信文件不需要 pickle 反序列化的向量库 / 后端。
</python>
</fix-faiss-deserialization>

<fix-dimension-mismatch>
<python>
确保嵌入维度与向量库索引的维度一致。

```python
# WRONG: Index has 1536 dimensions but using 512-dim embeddings
pc.create_index(name="idx", dimension=1536, metric="cosine")
vectorstore = PineconeVectorStore.from_documents(
    docs, OpenAIEmbeddings(model="text-embedding-3-small", dimensions=512), index=pc.Index("idx")
)  # Error: dimension mismatch!

# CORRECT: Match dimensions
embeddings = OpenAIEmbeddings()  # Default 1536
```
</python>
</fix-dimension-mismatch>

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的宣称。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
