---
title: "如何使用Hugo+Github+Netlify搭建博客"
subtitle: ""
description: ""
date: 2022-08-13T14:51:05+08:00
lastmod: 2022-09-05T14:51:05+08:00
slug: "how-to-settingup-blog-with-hugo-github-netlify"
author: "whitefirer"
authorLink: "https://whitefirer.org"
draft: true
hiddenFromHomePage: false

tags: ["tech", "cloud native"]
categories: ["Tech"]
toc:
    auto: false
---

### 背景
### 方案
{{< mermaid >}}
flowchart LR
Write[New Post] -->|Git Push| GitHub(Github Action)
GitHub -->|Build| Files[Static Files]
Files -->|Update| Pages[Github Pages]
Netlify <-->|Watch| Pages
Netlify -->|Deploy| Public
{{< /mermaid >}}

通过配置Github Action来编译构建我们的网站文件并发布到Github Pages，与此同时，通过Netlify监听Github仓库的变化，同步更新部署到Netlify App网站。

#### 构建流水线（Github Action）
Github Action的workflows配置文件如下：
```yaml
# mysite/.github/workflows/build-and-sync-website.yml
name: build

on:  # 触发时机
  workflow_dispatch: # 手动触发
  push: # 代码提交触发
    branches: # 在哪个分支
      - main	# 在main分支
  pull_request: # PR提交时触发

jobs: # 工作流
  build: # 工作名称
    runs-on: ubuntu-latest
    steps:
        - name: Checkout
          uses: actions/checkout@v2
          with:
              submodules: true
              fetch-depth: 0

        - name: Setup Hugo
          uses: peaceiris/actions-hugo@v2
          with:
              hugo-version: "latest"
              extended: true

        - name: Build Web
          run: hugo -v --gc

        - name: Deploy Web to Github Pages
          uses: peaceiris/actions-gh-pages@v3
          with:
              PERSONAL_TOKEN: ${{ secrets.BLOG_TOKEN }}
              EXTERNAL_REPOSITORY: whitefirer/whitefirer.github.io
              PUBLISH_BRANCH: main
              PUBLISH_DIR: ./public
              commit_message: ${{ github.event.head_commit.message }}

        # - uses: manyuanrong/setup-ossutil@v2.0
        #   with:
        #     # endpoint 可以去oss控制台上查看
        #     endpoint: "oss-cn-hongkong.aliyuncs.com"
        #     # 使用我们之前配置在secrets里面的accesskeys来配置ossutil
        #     access-key-id: ${{ secrets.ACCESS_KEY_ID }}
        #     access-key-secret: ${{ secrets.ACCESS_KEY_SECRET }}
        # - name: Deply Web To OSS
        #   run: ossutil cp public oss://blog-whitefirer/ -rf
```

#### HTTPS域名证书（Let's Encrypt CA）

### 总结
整个方案较简单，维护起来也容易，每次变更通过Git提交即可自动触发构建部署。
