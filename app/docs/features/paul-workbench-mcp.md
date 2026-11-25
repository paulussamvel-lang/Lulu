# Paul工作台 MCP

独立的本机 stdio 服务，使用现有工作台的选题库和文案精选库。服务可在桌面应用关闭时运行。资料目录需要由使用者明确指定。已有 macOS 安装的默认路径是 `~/Library/Application Support/Lulu`，保留目录名可让桌面应用继续读写同一份资料。

- 视频制作支持步骤查询、查选题、读取详情和保存单步制作记录。更新使用选题修订号。
- 文案精选支持查询项目、候选正文、新建项目和添加候选副本。新建和追加用修订号及 `request_id` 防止并发覆盖和重试重复。冲突后先刷新记录。
- 工作台资料文件沿用原目录。转录、下载、配音、AI 评分和飞书同步由桌面应用处理。

## 安装到独立环境

在仓库根目录，从一个新的本机目录创建虚拟环境。下面以 `uv` 和 Python 3.11 为例。

```sh
export PAUL_MCP_DIR="$HOME/.local/share/codex-mcp/paul-workbench/v1"
uv venv --python 3.11 "$PAUL_MCP_DIR/.venv"
uv pip install --python "$PAUL_MCP_DIR/.venv/bin/python" 'mcp==1.26.0'
"$PAUL_MCP_DIR/.venv/bin/python" -B app/packaging/install_paul_workbench_mcp.py
codex mcp add paul-workbench -- "$PAUL_MCP_DIR/.venv/bin/python" -I -B \
  -m paul_workbench_runtime.paul_workbench_mcp \
  --data-root "$HOME/Library/Application Support/Lulu"
```

使用 MCP 客户端连接后，先运行 `workflow_steps` 或 `topics_list` 验证工具能读取当前资料。生效配置可用 `codex mcp get paul-workbench` 核对。
