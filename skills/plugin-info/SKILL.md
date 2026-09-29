---
name: plugin-info
description: 显示 Wttch 插件已配置的项目和来源，但不显示任何配置值或密钥。
---

# Plugin Info

显示当前工作目录中 Wttch 插件的配置索引。运行共享 runtime：

```bash
python3 "${PLUGIN_ROOT}/runtime/bootstrap.py" "${PLUGIN_ROOT}/runtime/plugin_info.py"
```

输出中的字段含义如下：

- `working_directory_config_fields`：项目 `.agents/wttch/config.yml` 中已存在的字段路径；
- `environment_variables`：当前进程中已设置、且被 Wttch 插件读取的环境变量名；

只报告输出中的名称和来源。不要读取、推断、回显或要求用户提供任何配置值，包括
API Key、模型标识、地址、超时和功能开关值。
