---
title: "slirp 上传卡死 300 秒：从应用层一路追到网络层的排查实录"
subtitle: "上传稍大的文件就挂起约 5 分钟——小图正常、localhost 正常、局域网 IP 卡死。一次从 sharp 假说、浏览器差异、multipart 解析，最终定位到 slirp TCP 缺陷的完整排查"
description: "TenBox 虚拟机（virtio-net 链 libslirp 用户态网络）里，单请求 body 超过 ~256KB 会 TCP 卡死约 300 秒。本文记录从应用层（sharp 挂起假说）→ 浏览器差异 → multipart 解析 → 网络层的完整排查过程，以及应用层分块上传的解决方案。"
date: 2026-08-13 23:00:00+08:00
lastmod: 2026-09-17 01:30:00+08:00
slug: "qemu-slirp-upload-hang"
author: "whitefirer"
authorLink: "https://whitefirer.org"
draft: true
hiddenFromHomePage: false

tags: ["tech", "tenbox", "slirp", "network", "debugging", "upload", "tcp"]
categories: ["Tech"]
---

## 现象

在本地开发环境（TenBox VM）里，网页应用的上传功能有个诡异规律：

- **小图（几 KB）：秒传成功**
- **稍大一点的图（几百 KB）：前端等 60-120 秒超时取消，服务端日志显示请求处理了约 5 分钟（300 秒）后返回 200，但素材库看不到图**
- 用 `localhost` 访问一切正常，用局域网 IP（`192.168.0.102`）访问必现
- 上传链路本身没问题——同样的请求换个浏览器测试工具就秒过

"稍大图从没成功过，只有小图成功过"——这个历史规律是整件事最重要的线索，可惜一开始没当回事。

## 排查历程

### 第一幕：怀疑应用层（sharp 图片处理）

最初看到"服务端处理 5 分钟"，第一反应是图片处理库 sharp（libvips）在虚拟机环境下的病理性慢路径。代码里明明有 15 秒超时保护，但注释写着"超时不取消底层操作"——如果 sharp 原生调用阻塞了事件循环，连超时定时器都跑不了，请求挂 5 分钟完全说得通。

于是做了"快路径"：AI 封面这种浏览器自产的 PNG 跳过 sharp 重处理，直接 magic bytes 鉴型 + 读 PNG 头 + 哈希。**结果还是挂 5 分钟**——sharp 假说排除。

### 第二幕：怀疑浏览器差异

用 playwright 的 Chromium 测试全部正常（几十毫秒），但用系统安装的 Chromium 复现出了异常——一度以为是浏览器 multipart 编码差异。为此把 multipart 解析从 Node 内置的 `req.formData()` 换成了 busboy 手动解析。**结果依然挂**——解析器假说排除。

### 第三幕：打点定位，真相浮现

在路由入口加打点日志，发现关键事实：

```
[upload] 进入 route cl=437671   ← 请求到达了，content-length 正常（437KB）
（然后没有任何后续打点）          ← 卡在读取请求体
```

**请求体（body）的 TCP 传输本身就没有完成**——服务端在等一个永远传不完的 body，300 秒是 Node 的固定超时。

### 第四幕：网络层实锤

用 curl 直接做传输实验：

```
localhost POST 500KB   → 46ms 完成
192.168.0.102 POST 500KB → 30 秒超时卡死
```

然后测出精确阈值：

```
256KB → 35ms 秒过
300KB → 卡死
```

**根因确认：slirp 用户态网络的 TCP 缺陷**。这台开发机是 TenBox VM（自研 C++ VMM，宿主机是 Windows，走 WHVP 后端），virtio-net 后端链 libslirp（`10.0.2.15`，网关 `10.0.2.2`）——libslirp 就是 QEMU 内置用户态网络栈的独立化版本，纯软件模拟 TCP。**它对超过 ~256KB 的连续 body 传输存在缺陷**（后经 2026-09-17 对照实验进一步限定：该缺陷为 WHVP/Windows 平台特有，详见文末附录）：TCP 发送窗口不增长，连接挂起约 300 秒。

为什么小图能过？小 body 落在单个 TCP 窗口内，一次发完不触发缺陷路径。

为什么 localhost 正常？localhost 走回环接口，完全不经过 slirp。

## 解决方案：应用层分块上传

网络层的根治（VM 网络改桥接）需要动宿主机配置、装 TAP 驱动、重启 VM——风险收益比不划算。于是从应用层绕开：

- **前端**：文件切成 **128KB/块**（远低于 256KB 阈值）顺序上传
- **服务端**：分块端点按会话收集，收齐后拼接，走原有处理流程（图片处理/去重/素材建档）
- **全入口接入**：封面选择器、编辑器粘贴/拖拽、头像上传、内容工作室——所有上传路径统一走分块工具

实测结果：**卡死的网络路径上，437KB 封面上传从 300 秒挂起变成 1.6 秒完成**。

## 经验教训

1. **"小文件能传大文件不能"是最有价值的线索**——它直接指向传输层而非应用层。如果早做阈值实验，能省掉两轮应用层排查
2. **next dev 的请求日志只在响应完成后打印**——挂起的请求在日志里不可见，必须自己在路由入口加打点
3. **打点要打在"进入"位置**：入口打点证明"请求到达了"，后续打点缺失才能定位"卡在哪一步"。这次正是 `[upload] 进入 route` 出现而后续打点全部缺失，才把矛头从 sharp 转向 body 传输
4. **localhost 正常 ≠ 局域网 IP 正常**：本机回环路径绕开了很多网络栈问题，测试一定要覆盖真实访问路径
5. **应用层绕开 vs 网络层治本**：分块上传是"绕过缺陷"而非"修复缺陷"——>256KB 的响应下载等其他场景同样会卡。治本需要改 VM 网络模式，作为后续事项记录

## 附：治本方案（网络层，2026-09-16 更新）

> 补充背景：这台开发机是 TenBox VM（自研 C++ VMM，WHVP/HVF/KVM 三后端），virtio-net 后端链的是 libslirp——和 QEMU 用户态网络是同一个栈。2026-09 共享存储池（JuiceFS→RustFS）落地后，slirp 又贡献了两个新数据点：**下载方向缺陷**（hostfwd 入向连接的回包走 guest 出站，实测下载 0.83MB/s vs 上传 26MB/s）和 **tailscale UDP 打洞失败**（双 VM 各自在 slirp NAT 后，直连建立不了，全程走杭州 DERP 中继）。再加上"每个新服务端口都要手工加转发"的日常痛点，网络层治本从"等以后"变成了正式路线。

> **平台范围（2026-09-17 对照实验）**：本缺陷（hostfwd 入站 >256KB body 卡死）在 Windows/WHVP 生产端稳定复现（宿主 curl 打转发端口：200KB 秒过、500KB 挂满超时、服务端永远读不满 body、连接悬尸）；但同一套代码在 **KVM 后端完全不复现**——v0.8.1 与 v0.8.2 两个版本、loopback 与跨机 LAN 两种拓扑、256KB→50MB 全档位含并发全部秒过。
>
> **治愈（2026-09-17 同日）**：Windows 宿主将 `tenbox-vm-runtime` 换成上游 main（0.8.2+）重编版本并重启 VM 后，同一拓扑 200KB/500KB/10MB 全部秒过——缺陷在 0.8.1→main 的 net 修复（socket 可读性检测）中被治愈。该 bug 仅存于 0.8.1 及更早版本，且只在 Windows/WHVP 平台的行为下触发（KVM 后端即便带病的 0.8.1 也不显现）。**处置：Windows 宿主升级到 0.8.2+ runtime 即根治；gvproxy 平替的剩余价值在吞吐、端口转发自动化与 tailscale 打洞，"治病"需求已消失。**

分三阶段，每阶段独立可交付：

### 阶段一：gvproxy 平替 slirp（治慢、治病）

[gvisor-tap-vsock](https://github.com/containers/gvisor-tap-vsock)（gvproxy）：Google gVisor 的用户态 TCP/IP 栈，和 slirp 同为**免驱动、免特权**的用户态 NAT，但 ICMP 可用、UDP 可靠、吞吐高一个量级、无 upload-hang 这族怪病（Lima/Podman machine/crc 的生产选择）。TenBox 接法：virtio-net 设备的以太帧流从 libslirp 改道 gvproxy 的 QEMU 兼容 socket（`--listen-qemu`）——设备代码是自己的，改道点很直白。验证：本用例（>256KB body）回归 + 存储池场景实测。

### 阶段二：端口转发的自动化（治"手动开端口"）

gvproxy 仍是 NAT，入向还要转发——但两层缓解：

- **范围转发**：一条规则转一段（如 `30000-32000`），把"每个工作台/服务加一条"的日常操作一次性消掉（slirp hostfwd 语法本身支持，暴露到配置/界面即可，不依赖阶段一）
- **动态转发**：gvproxy 有控制 API，VM 内新监听端口可自动建转发规则，"手动"二字消掉

### 阶段三：bridged 可选后端（治概念，但分层）

TAP/bridge 让 VM 拿真 LAN IP，**端口转发概念消失**，tailscale 直连也随之解锁。但它和 TenBox 的沙盒定位有张力，正确姿势是把网络暴露做成沙盒策略的显式维度：

- **离线 / NAT（默认）/ Bridged（opt-in）** 三档；bridged 配 guest 防火墙默认拒入 + UI 明示"对局域网可见"
- 用法分野：**agent 沙盒 VM 永远 NAT/离线；自己的基础设施 VM（存储、服务节点）才 bridged**——同一套定位，两类负载各取所需
- Windows/WHVP 下的桥接不走 TAP 驱动老路（兼容性差），走 Hyper-V 可扩展交换机或 packet filter，细节待 spike

**选择逻辑不变**：当年选应用层分块是对的（风险收益比）；现在路由线上是因为负载变了——存储池把网络从"开发便利性"变成了"生产热路径"。
