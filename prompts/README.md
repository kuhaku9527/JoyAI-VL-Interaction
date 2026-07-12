# Character / Persona Prompts

角色 / persona 提示词集中放在这里，被 `services/webinfer` 适配器在每次
构造主模型请求时自动读入，拼到 system prompt 之前。

## 目录约定

| 项 | 值 |
| --- | --- |
| 默认发现目录 | `<repo-root>/prompts/` |
| 额外路径环境变量 | `CHARACTER_PROMPT_PATH`（POSIX `:` 或逗号 `,` 分隔） |
| 额外路径 CLI 参数 | `--character-prompt PATH`（可多次） |
| 关闭注入 | `--no-character-prompt` 或 `ENABLE_CHARACTER_PROMPT=0` |
| 支持的后缀 | `.txt` / `.md` |

## 文件命名

- 任意 `*.txt` 或 `*.md` 文件都会被读取。
- 同一目录里多个文件会**按文件名字典序**合并（Windows 下大小写不敏感）。
- 推荐用角色代号 + `.txt` 的命名（例：`bt-7274.txt`），方便排序。

## 加载顺序

1. `<repo>/prompts/` 下的所有支持后缀文件。
2. `CHARACTER_PROMPT_PATH` 中列出的额外文件 / 目录。
3. CLI 传入的 `--character-prompt` 路径。

每段 prompt 之间用 `---` 分隔，**整体**被包进一个
`<character_profile>` … `</character_profile>` 块，加在 system prompt
的最前面。原始 system prompt 保持原样（仍包含 `</silence>` / `</response>`
/ `</delegate>` 三选一决策格式），并在末尾追加一行"始终以角色身份回应"
的提醒。

## 运行时热重载

```bash
# 查看当前生效的角色文件
curl http://127.0.0.1:8070/v1/prompts/active

# 编辑文件后让缓存失效
curl -X POST http://127.0.0.1:8070/v1/prompts/reload
```

`/v1/prompts/reload` 会重新扫盘、刷新 mtime，并清空内部的 system prompt
缓存。**编辑文件后不需要重启适配器**（webinfer 同时也会在请求到来时按
mtime 检查缓存，但显式 reload 更可靠）。

## 编写建议

- 保持简洁：200-800 token 通常足够，再长容易稀释决策指令。
- 不要重复原本 system prompt 中的"Stay silent / Speak / Delegate"规则；
  角色描述应该补充人设，而不是改写决策格式。
- 多角色并存：可以放多个文件，按字典序合并；第一个文件最先被读入。
- 占位符：`bt-7274.txt` 自带 Markdown 模板与 `TODO BT7274` 标记，方便
  用编辑器跳转替换。
