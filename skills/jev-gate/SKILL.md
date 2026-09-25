---
name: jev-gate
description: Explain, validate, test, or extend the JEV OpenRouter-backed tool-call gate and its YAML-only gate policy. Use when the user asks about JEV gate behavior, policy changes, dry runs, or adding protected actions.
---

# JEV gate

This is one skill inside the larger Wttch plugin. Use the plugin's shared runtime
instead of adding a separate environment or dependency file to this skill.

1. Read `gate.yml` before changing behavior. Keep it limited to gate policy:
   defaults, matching rules, actions, reasons, and review instructions.
2. Keep model and transport settings out of YAML. Read them from
   `OPENROUTER_API_KEY`, `JEV_OPENROUTER_MODEL`, `JEV_OPENROUTER_BASE_URL`, and
   `JEV_OPENROUTER_TIMEOUT`.
3. Validate the policy with:

   ```bash
   python3 "${PLUGIN_ROOT}/runtime/run.py" validate-jev-policy --policy "${PLUGIN_ROOT}/skills/jev-gate/gate.yml"
   ```

4. Dry-run the hook by piping one `PreToolUse` JSON event into `jev-gate` on the
   same runtime. Never print or echo `OPENROUTER_API_KEY`.
5. Explain which rule matched, whether the outcome was static or reviewed by
   JEV, and whether fail-open behavior was used.
6. Order specific deny or review rules before broad allow rules. Use `deny` for
   deterministic prohibitions, `review` for contextual judgment, and `allow`
   only for clearly safe classes.
