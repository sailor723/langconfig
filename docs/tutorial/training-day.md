# 训练当天：环境、账号、开场与收尾

这份是给**组织者**看的。学员只需要一条消息（见文末「发群里的消息」）。

## 环境

| 项 | 值 |
|---|---|
| 地址 | `http://8.216.101.189:8765/` |
| 账号 | `admin`（管理员）+ `user1` … `user10`（学员，member 角色） |
| 密码 | 训练前统一下发；管理员账号的密码单独管理 |
| 数据 | 51 个 agent（21 个公开）、68 个工具、44 个技能、29 个模型 |
| 数据库 | 原生 PostgreSQL 16（systemd 自启），每日 03:30 备份到 `/root/backups` |
| 嵌入模型 | Ollama + `nomic-embed-text:latest`（768 维，纯 CPU；`systemctl is-active ollama`） |

> 这台是**临时训练环境**，训练结束就收回公网端口。别放正式资料。

进机器：`ssh -i <阿里云下载的 .pem> root@8.216.101.189`。已关掉密码登录，那个 `.pem` 是唯一入口 —— 丢在 `~/Downloads` 里迟早被清理，挪到安全的地方。

装了新东西（比如这次补的 Ollama）一定要**重启后端才算数**：嵌入模型只在第一次需要时初始化，结果会被缓存，不重启就还是旧状态。重启约 40 秒，挑没人用的时候做。

## 多人边界（开场要讲清的一句话）

| 共享的 | 各自独立的 |
|---|---|
| agent 模板（51 个）、工具、技能、模型与 API key | 聊天记录、上传文件、生成的文件（在 `outputs/users/<id>/` 下） |

所以：**练习可以随便做，但不要改 agent 配置** —— 模板是共享的，一个人改了所有人受影响。要试配置改动，就让 Builder 复制一份私有 agent 再改。

## 开场前 3 分钟自检

```bash
# 1) 用一台非本机的电脑打开地址，确认能登录
# 2) 选 case-1-basic-agent，发一句「hi」，确认有回复
# 3) Settings → Models 确认 provider key 显示已验证（没配 key 全场会卡在这一步）

# 4) run book 里写的 13 个 agent id 在这个库里是否都还在
cd /root/langconfig/backend && .venv/bin/python scripts/verify_runbook_ids.py --ecs
# 期望 13/13 ok。少一条就说明库被重灌过（id 会重排），学员按 run book 找 agent 会找不到

# 5) 11 个账号逐个真登录一遍（别只看「用户存在」——user1 就是这么挂的）
PW='<共用密码>'
for u in admin user1 user2 user3 user4 user5 user6 user7 user8 user9 user10; do
  printf '%-8s %s\n' "$u" "$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    http://127.0.0.1:8765/api/auth/login -H 'Content-Type: application/json' \
    -d "{\"username\":\"$u\",\"password\":\"$PW\"}")"
done
# 开场前期望 11 行全 200；有 401 就重置那个账号：
# .venv/bin/python scripts/create_user.py <用户名> --reset-password '<共用密码>'
```

> **课中途出现 401 别急着重置。** UI 里有「修改密码」，一次训练里实测有 8 个学员自己改掉了
> （日志：`User userN changed their own password`）。重置会把这个人当前会话一起踢掉。
> 先问一句「你改过密码吗」，改过就用他自己那个。

命令行自检（可选，从任何一台机器）：

```bash
curl -s -o /dev/null -w 'ui:%{http_code}\n' -u 'user1:<密码>' http://8.216.101.189:8765/
# 200 = 界面通；401 = 密码不对；000 = 端口没开（查安全组）
```

## 训练中可能被问到的三件事

1. **「我的文件在哪？」** 每人一个工作区：`outputs/users/<你的 id>/agents/agent_<id>/`，上传在 `upload/`，产出在 `generated/`。
2. **「为什么我看不到同事的文件？」** 这是设计：不同 `users/<id>/` 之间互相不可见，agent 会主动拒绝跨账号路径。
3. **「agent 回答里带一句自我介绍？」** 首轮会带身份注入，属于正常行为，别把它当结果。

## 收尾清单（训练结束当天做）

```bash
# 1) 收回公网入口
ufw delete allow 8765/tcp
#    阿里云安全组：删掉 8765 入方向规则

# 2) 确认备份仍在
ls -lh /root/backups | tail -3

# 3) 改掉共用密码（10 个人共用一个密码等于一人泄露全体）
#    在 UI 里逐个改，或让每人自己登录后改
```

想长期开放的话，把 80/443 配好 HTTPS（`docs/installation/installation.md` 的 Caddy 段），再决定是否继续暴露 8765。

## 发群里的消息

```
明天训练环境（临时云端，用完即删）

地址：http://8.216.101.189:8765/
账号：user1 / user2 / … / user10（人名对应我另行分配）
密码：另行通知

三点说明：
1. 这是临时环境，只为这次训练准备，别放重要资料。
2. 每人账号独立 —— 上传文件、聊天记录、生成的文件只有自己能看到。
3. agent 配置是共享的，练习时只改自己的文件和对话，不要改 agent 设置。

浏览器会弹登录框，输账号密码即可。
```
