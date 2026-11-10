# 宿主层面的坑 —— 换一个宿主就作废

这些不是流程缺陷，是**这台机器工具层**的病理。写在这里而不是正文里，因为它们会变：宿主修好之后，正文里那些
"用别的方法再验一次"就成了噪音。

每一条都来自一次真实交付的测量，不是推测。

## P1. 写盘可能落进"镜像树"，而回执说成功

用宿主的绝对路径写文件时，文件可能落进工作区里的镜像目录 `./Users/<name>/...`，回执却报
`Updated file …/ontology/01-structure.ttl`，紧接着 `wc -l` 回 `No such file or directory`。

- 症状：回执成功、文件不在；`find <workspace>/Users -type f` 才找得到。
- 对策：**永远用工作区相对路径**写；写完立刻 `wc -l`；发现镜像树就用 `mv` 搬回并 `rm -rf` 掉镜像目录。

## P2. 结果可能被截断

转录里的 `result` 有长度上限。旧记录上限 500 字符——一次 260 次调用的会话里 190 条被切断，只有 70 条还留着
`[Command succeeded…]` 标记，其中一条实验的结论永远拿不回来。

- 现状：上限提到 20 000，并写入 `result_length` / `result_truncated`；**历史记录仍是旧的**。
- 对策：读 `result_truncated`；只引用活下来的部分；长输出的证据**重跑一次**，不要引用被截断的残片。

## P3. 状态字段会说谎

`status` 曾经 260/260 全是 `completed`，其中 8 条是真失败（超时、`No such file`、`ModuleNotFoundError`、
`ERROR: column …`）。现在写入时按文本判 `failed`，历史记录没回填。

- 对策：失败判定只信文本标记；不要用 `status` 过滤。

## P4. 有的调用什么都没做

`result` 为空、参数里缺关键键（`write_file` 只发了 `content` 没发 `file_path`），却仍算完成、状态 `completed`。

- 对策：把「`result` 为空」当独立一类查；它既不是成功也不是失败。改完立刻用一次独立的读操作确认。

## P5. 单次执行有硬超时（实测 120 秒）

`find /` 这类全盘扫描会撞上 `Command timed out after 120 seconds`。

- 对策：把扫描范围收窄到工作区或具体目录；长任务拆成几步，每步都能单独失败。

## P6. 管道会吞掉退出码

`... | tail` 让 `[stderr] ERROR` 与 `[Command succeeded with exit code 0]` 同屏。

- 对策：不要用管道收尾来判断成败；先看完整输出里的标记，再取最后一行之外的信息。
