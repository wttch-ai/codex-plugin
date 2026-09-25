---
name: plugin-settings
description: 查看、启用、关闭或重置 Wttch Codex 插件的功能设置。适用于配置插件、修改功能开关、检查当前设置或向配置清单添加新项目的场景。
---

# Plugin Settings

Manage runtime feature switches through `runtime/settings.py`. Keep gate matching
policy in `skills/jev-gate/gate.yml`; do not put feature switches or API keys there.

## Manage settings

Run these commands from the plugin root, or replace `runtime/settings.py` with its
`${PLUGIN_ROOT}` path:

```bash
python3 runtime/settings.py list-settings
python3 runtime/settings.py set-setting <key> <on|off>
python3 runtime/settings.py reset-settings
```

List settings accept their documented type. For example:

```bash
python3 runtime/settings.py set-setting blocked_models 'gpt-6-luna,gpt-6-sol,gpt-6-astra'
```

Before changing a setting, list the catalog and resolve the user's wording to an
exact key. Report the old and new value. Do not change settings the user did not
request. The user settings file is local and is created at
`~/.config/wttch-codex-plugin/settings.json`; `WTTCH_PLUGIN_SETTINGS_FILE` may
override that path for testing.

Never write `OPENROUTER_API_KEY` into the settings file, repository, command
arguments, output, or logs. It remains an environment variable or secret-store
value.

## Add a switch

`config/features.json` is the authoritative switch catalog. Add one entry with a
unique snake_case `key`, a user-facing `label`, a precise `description`, supported
`type`, and matching `default`. The current supported types are `boolean` and
`string_list`. Then update the runtime component that consumes the setting and add
a behavioral test. Catalog-only settings that nothing reads are not complete
features.

Validate both default behavior and a user override. Existing settings files may
omit new keys; the catalog default must apply automatically.
