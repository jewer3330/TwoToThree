# P1 原生 IPv6 可达性实测报告

日期：2026-08-30

## 结论

当前不能建立 GPU2 → 主控的无中转原生 IPv6 数据通道。

- 主控具有全局单播 IPv6（`240e:` 前缀），默认 IPv6 路由存在。
- GPU2 仅具有 `fe80:` 链路本地地址和 `fd7a:115c:a1e0:` Tailscale ULA。
- GPU2 访问 IPv6-only 公网探测端点失败，说明当前网络没有可用的原生 IPv6 出站。
- GPU 注册地址 `100.69.5.47` 属于 Tailscale 地址，不是公网直连地址。

因此，在禁止 CDN、Cloudflare upload、Tailscale DERP 或其他中转的前提下，P1/P2 必须等待 GPU2 网络具备原生 IPv6。系统应保留产物并报告 `DIRECT_PATH_UNAVAILABLE`，不得静默回退。

## 网络侧解锁条件

1. GPU2 所在宽带/路由器开启 IPv6，并向 Windows 网卡下发全局单播地址。
2. GPU2 能访问 IPv6-only 站点，并能直接访问主控的公网 IPv6 地址和指定 HTTPS 端口。
3. 主控路由器仅向 GPU2 所需端口开放入站；使用 DDNS AAAA 和 TLS。
4. 连续完成 100 次健康检查及 10 次 100MB 文件 SHA-256 一致性测试。

## 当前处理

- P0 的 `legacy_scp` 暂时保留为明确标记的旧链路，不宣称其为公网直连。
- 不增加任何中转 fallback。
- P2 分块传输服务代码可以后续开发，但在上述物理条件满足前不得切换生产流量。
