# Remote access · 浏览器远程访问

> English follows the Chinese section.

插件本身不改变 DSH 的远程访问模型：**仅 owner、单用户**。参考部署（设计文档 §4）：

## 访问模型

| 访问者                           | 机制                                                                | 能力 |
| -------------------------------- | ------------------------------------------------------------------- | ---- |
| owner（任何浏览器，含手机/平板） | Caddy TLS + basic_auth 反代 → `dsh web`；DSH 内建 token→cookie 认证 | 全部 |

- 不需要 DSH 的 remote-peer 机制（那是给同 Host 上非 owner Peer 的），不装 LiveShare、无第三方 policy。
- 给第三方的只读方式 = 报告导出文件，不是共享页面。

## 认证时序

```text
浏览器 ──Caddy(TLS+basic_auth)──> dsh web (127.0.0.1:60333)
  GET /?token=…  → 交换签名 session cookie → 重定向干净 URL
  /api 调用 + /api/remote.mux (WS) 均验 cookie
```

- token URL 即进程凭据：仅经安全信道传递（SSH 读启动行或管理员复制）。
- WS 与 HTTP 同源：Caddy 原生转发 Upgrade；注意 2s 心跳要求代理不长期缓冲。

## 部署要点

```text
dsh --profile web --host 127.0.0.1 --port 60333 \
    --public-url https://dsh.example.com \
    --trusted-host dsh.example.com --no-open
```

- `--host` 只能绑具体 IP；`--trusted-host` 必须含浏览器可见 authority。
- 内核进程零端口；`portfolio.db` 0600；Caddy 之外不暴露任何端点。
- token/cookie 丢失 = 实例权限丢失：重启 dsh 轮换（见 troubleshooting）。

## 插件路由的认证

Dashboard 数据路由 `/api/debrief/dashboard` 经 `ctx.connection.fetch` 注册，
由 DSH 的浏览器认证（签名 cookie + Host/Origin fence）统一准入；插件不再
自建认证。静态页面/卡片渲染在已验证的浏览器会话内，无额外暴露面。

---

The plugin does not change DSH's remote-access model: **owner-only, single
user**. Reference deployment (design §4):

| Visitor                           | Mechanism                                                                    | Capability |
| --------------------------------- | ---------------------------------------------------------------------------- | ---------- |
| owner (any browser, incl. mobile) | Caddy TLS + basic_auth reverse proxy → `dsh web`; built-in token→cookie auth | Everything |

- The remote-peer mechanism is for non-owner peers on the same Host and is not
  used; LiveShare is not installed and there is no third-party policy.
- Read-only sharing with third parties = exported report files, never a shared page.

## Auth sequence

```text
Browser ──Caddy(TLS+basic_auth)──> dsh web (127.0.0.1:60333)
  GET /?token=… → signed session cookie → redirect to clean URL
  /api calls and /api/remote.mux (WS) all verify the cookie
```

- The token URL is a process credential: transfer it over secure channels only.
- WS and HTTP share one origin; Caddy forwards upgrades natively; the 2s
  gateway heartbeat requires a non-buffering proxy.

## Deployment essentials

```text
dsh --profile web --host 127.0.0.1 --port 60333 \
    --public-url https://dsh.example.com \
    --trusted-host dsh.example.com --no-open
```

- `--host` takes a concrete IP only; `--trusted-host` must name the
  browser-visible authority.
- The kernel process opens no port; `portfolio.db` is 0600; nothing is exposed
  beyond Caddy.
- Losing the token/cookie = losing the instance: rotate by restarting dsh (see
  troubleshooting).

## Plugin route authentication

The dashboard route `/api/debrief/dashboard` registers through
`ctx.connection.fetch` and is admitted by DSH's browser authentication (signed
cookie + Host/Origin fence); the plugin adds no authentication of its own.
Cards and pages render inside the authenticated browser session, adding no
extra surface.
