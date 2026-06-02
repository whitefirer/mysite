#!/usr/bin/env python3
"""Hugo Markdown → 微信公众号 HTML 转换

用法: python3 convert.py <markdown_file.md>
输出: wechat-output.html (可直接粘贴到公众号编辑器)
"""

import sys
import re
import html
from pathlib import Path


def strip_frontmatter(text: str) -> tuple[dict, str]:
    """剥 Hugo frontmatter，返回 (meta, body)"""
    if not text.startswith('---\n'):
        return {}, text
    end = text.find('\n---\n', 4)
    if end == -1:
        return {}, text
    meta_raw = text[4:end]
    body = text[end+5:]
    meta = {}
    for line in meta_raw.strip().split('\n'):
        line = line.strip()
        if ':' in line:
            k, v = line.split(':', 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def clean_hugo(content: str) -> str:
    """清理 Hugo 特有语法"""
    # mermaid shortcode → 占位图
    content = re.sub(
        r'{{<\s*mermaid\s*>}}(.*?){{<\s*/mermaid\s*>}}',
        r'<pre style="background:#f5f5f5;padding:12px;text-align:center;color:#999">[图表: Mermaid 流程图]\n\1\n</pre>',
        content, flags=re.DOTALL
    )
    # 其他 shortcode 移除标签保留内容
    content = re.sub(r'{{<\s*\w+[^>]*>}}', '', content)
    content = re.sub(r'{{<\s*/\w+\s*>}}', '', content)
    # 相对链接补全域名
    content = re.sub(r'\(/posts/', '(https://whitefirer.org/posts/', content)
    content = re.sub(r'\(/(?!/)', '(https://whitefirer.org/', content)
    return content


def markdown_to_html(text: str) -> str:
    """Markdown → HTML"""
    from markdown_it import MarkdownIt
    from markdown_it.renderer import RendererHTML

    md = MarkdownIt('commonmark', {'html': True, 'linkify': True, 'typographer': True})
    md.enable(['table', 'strikethrough', 'linkify'])
    return md.render(text)


MAIN_STYLE = """
*{margin:0;padding:0;box-sizing:border-box}
body{max-width:100%;overflow-x:hidden}
#nice{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans","PingFang SC","Microsoft YaHei",sans-serif;font-size:16px;color:#3f3f3f;line-height:1.8;padding:0 16px;word-break:break-word}
#nice h1,#nice h2,#nice h3,#nice h4{font-weight:700;margin:1.4em 0 .6em;color:#2f2f2f}
#nice h1{font-size:1.6em;text-align:center}
#nice h2{font-size:1.35em;border-bottom:2px solid #4a90d9;padding-bottom:.3em}
#nice h3{font-size:1.15em}
#nice p{margin:.8em 0}
#nice strong{color:#2b2b2b}
#nice a{color:#4a90d9;text-decoration:none;border-bottom:1px dashed #4a90d9}
#nice blockquote{margin:1em 0;padding:.6em 1em;border-left:4px solid #4a90d9;background:#f5f7fa;color:#5a5a5a;font-size:.95em}
#nice code{font-family:"SF Mono",Menlo,Monaco,Consolas,monospace;font-size:.88em;background:#f0f0f0;padding:2px 6px;border-radius:3px;color:#c7254e}
#nice pre{margin:1em 0;padding:14px 16px;background:#282c34;border-radius:6px;overflow-x:auto;font-size:.85em;line-height:1.6}
#nice pre code{background:0 0;color:#abb2bf;padding:0;font-size:inherit}
#nice ul,#nice ol{margin:.6em 0;padding-left:2em}
#nice li{margin:.3em 0}
#nice table{width:100%;margin:1em 0;border-collapse:collapse;font-size:.9em}
#nice th,#nice td{padding:8px 12px;border:1px solid #dfe2e5;text-align:left}
#nice th{background:#f5f7fa;font-weight:600}
#nice tr:nth-child(even){background:#fafbfc}
#nice img{max-width:100%;height:auto;display:block;margin:.6em auto;border-radius:4px}
#nice hr{border:0;height:1px;background:#e0e0e0;margin:1.5em 0}
#nice .footnotes{font-size:.85em;color:#888;border-top:1px solid #eee;padding-top:1em;margin-top:2em}
pre code .kw{color:#c678dd}pre code .str{color:#98c379}
pre code .num{color:#d19a66}pre code .cm{color:#5c6370}
"""


def wrap_html(title: str, body_html: str) -> str:
    """包装为微信兼容 HTML"""
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>{html.escape(title)}</title></head>
<body>
<section id="nice">
<h1>{html.escape(title)}</h1>
{body_html}
</section>
<style>{MAIN_STYLE}</style>
</body>
</html>"""


def main():
    if len(sys.argv) < 2:
        print("用法: python3 convert.py <markdown_file.md>")
        sys.exit(1)

    filepath = Path(sys.argv[1])
    text = filepath.read_text(encoding='utf-8')
    meta, body = strip_frontmatter(text)
    title = meta.get('title', filepath.stem)
    body = clean_hugo(body)
    html_body = markdown_to_html(body)
    result = wrap_html(title, html_body)

    out = filepath.parent / 'wechat-output.html'
    out.write_text(result, encoding='utf-8')
    print(f"✅ {out} ({len(result)} bytes)")
    print(f"📋 打开 {out} 复制内容 → 粘贴到公众号编辑器")


if __name__ == '__main__':
    main()
