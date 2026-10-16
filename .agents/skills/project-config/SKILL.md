---
name: project-config
description: 维护 wttch-codex-plugin 仓库的配置结构。新增、重命名、删除或改变项目配置字段时使用；必须同步更新 plugin-utils 的规范配置示例、文档和测试。仅适用于当前仓库，不是随插件分发的 Skill。
---

# Project Config

只管理 `wttch-codex-plugin` 当前仓库。插件项目配置的规范示例固定为
`skills/plugin-utils/example/config.yml`；不要在仓库根目录或其他 Skill 中创建重复的
完整配置模板。

## 维护规则

1. 修改任何由 `.agents/wttch/config.yml` 提供的字段前，先查找全部读取器、校验器、
   文档和测试，确认字段的作用域、类型、默认行为及兼容性。
2. 新增配置字段时，必须在 `skills/plugin-utils/example/config.yml` 中加入一个安全、
   可理解的示例值和必要注释。重命名、移动或删除字段时也必须同步修改示例。
3. 示例必须覆盖插件当前支持的完整配置结构，但只能使用明显无效的凭据占位符和非敏感
   演示值。禁止写入真实 API Key、Token、Cookie、服务器凭据或私钥。
4. 同步更新 `skills/plugin-utils/SKILL.md` 和 README 中受影响的路径、字段说明和初始化
   步骤。其他 Skill 只引用该示例，不复制完整模板。
5. 配置 Schema 或必填字段变化时，增加或更新测试，使代码支持的字段与规范示例保持一致。
6. 验证示例 YAML 可解析、相关测试通过，并执行 `git diff --check`。不要为了验证而读取或
   输出用户项目中的真实配置值。

环境变量、命令行参数和只在源码内部使用的常量不属于 `.agents/wttch/config.yml` 示例；
只有当它们被迁移为项目配置字段时，才加入规范示例。
