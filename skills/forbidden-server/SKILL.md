---
name: forbidden-server
description: 通过 PreToolUse Hook 对项目配置的 IP、域名或其他目标实施 block/warn 保护。
---

# 禁止目标 Hook

在项目根目录创建 `.agents/wttch/forbidden-server.yml`。它是规则列表，每项包含要匹配的 `target`、处理方式 `action` 和说明 `description`：

```yaml
- target: 192.168.2.29
  action: block
  description: 未单独授权时禁止访问的服务器
- target: production.example.internal
  action: warn
  description: 生产环境操作前提醒确认影响
```

Hook 在每次工具调用前扫描其输入。命中 `block` 时拒绝工具调用；命中 `warn` 时放行，但向执行者附加风险提示。一个调用命中多条规则时，`block` 优先。

`target` 是精确字符串片段，可用于 IP、域名、URL 片段或主机别名；配置为空或不存在时不施加限制。不要在 `description` 中记录凭据。