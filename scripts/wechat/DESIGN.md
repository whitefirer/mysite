# Hugo → 微信公众号 转换管道

公众号：赛博闲谭
作者：whitefirer

## 用法

```
"把这篇文章转公众号" → Claude Code 读 Hugo MD → 预处理 → 微信 HTML → 手动粘贴
```

## 架构

```
Hugo .md
    ↓
Python 预处理管道 (convert.py)
    ├── 剥 frontmatter
    ├── mermaid → mmdc → PNG
    ├── asciinema → asciicast2gif → GIF
    ├── 相对链接补全
    ├── Hugo shortcode 清理
    ├── 系列导航删除
    └── 署名追加
    ↓
干净 Markdown
    ↓
markdown2wechat API (POST /api/convert)
    ↓
微信兼容 HTML
    ↓
手动粘贴到公众号后台
```

自己写预处理管道，排版引擎调 markdown2wechat API。
不自己写排版——微信 CSS 兼容是体力活，mdnice 主题已验证。

## 预处理清单

| 操作 | 工具 | 说明 |
|------|------|------|
| 剥 frontmatter | Python | title → 公众号标题 |
| `{{< mermaid >}}` | mmdc CLI | SVG → PNG base64 内嵌 |
| `{{< asciinema >}}` | asciicast2gif | 转 GIF，或插入占位链接 |
| 相对链接 | regex | `/posts/xxx/` → `https://whitefirer.org/posts/xxx/` |
| Hugo shortcode | regex | 移除 `{{< raw >}}` `{{< tab >}}` 等标签 |
| 系列导航删除 | regex | 删 `*本文是「...」系列...*` 和 `<div class="post-series-nav">...</div>` |
| 署名追加 | 文本 | 末尾加 `— whitefirer` 或 `赛博闲谭` |
| mdnice 属性清理 | regex | 删 `data-website="https://www.mdnice.com"` |

## 不做的事

- 不发 API（个人号无权限）
- 不自动发布（需手动粘贴）
- 不管理图片 CDN（以后再说）

## 核心依赖

- markdown2wechat (MIT, Next.js) — 排版引擎，爬 mdnice 主题
- mermaid-cli (`@mermaid-js/mermaid-cli`) — `mmdc` 命令
- asciicast2gif — asciinema → GIF
- Python 标准库 — frontmatter 解析、正则、HTTP 调 API

## 文件

```
scripts/wechat/
├── DESIGN.md       # 本文件
├── convert.py      # 主转换脚本（Hugo MD → 干净 MD → 调 API → HTML）
├── themes/         # 自定义主题（markdown2wechat 导入）
└── requirements.txt
```
