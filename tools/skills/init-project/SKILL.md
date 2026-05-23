---
name: init-project
description: 在目前所在的專案資料夾建立 project-local .claude/CLAUDE.md。讓使用者多選 dimensions (frontend, backend, ...) 並把對應 skills 寫入 project context。Stage 2 bootstrap，不會動 ~/.claude/。
context: fork
---

# Init Project — Stage 2 bootstrap

## 觸發條件

- 使用者說 `/init-project`、「幫我初始化專案」、「init project」、「bootstrap project」
- 進入新的專案資料夾後想加上 workspace 層

## 你應該做的事

1. 確認當前工作目錄是「目標專案」而不是 `ai-cli-workspace` 本身——
   腳本自己也會擋，但提早確認可以給更好的錯誤訊息。
2. 從 `~/.ai-cli-workspace-path` 讀出 workspace 路徑（Stage 1 install
   會 pin 在那裡）：

   ```bash
   WS="$(cat ~/.ai-cli-workspace-path)"
   bash "$WS/scripts/init-project.sh"
   ```

3. 預設進入互動模式（gum 多選；無 gum 則 y/N fallback）。
   非互動可加 `--profile=<csv>`，或加 `--dry-run` 先預覽。
4. 結束後，提醒使用者：
   - 產生的 `<project>/.claude/CLAUDE.md` 是 additive layer，
     user-global rules 依然會先載入。
   - `<!-- USER-CONTENT-BELOW -->` 標記以下的內容會在後續 re-run 時保留。

## 範例

```bash
WS="$(cat ~/.ai-cli-workspace-path)"

# 互動式
bash "$WS/scripts/init-project.sh"

# 一次套 frontend 與 backend
bash "$WS/scripts/init-project.sh" --profile=frontend,backend

# 預覽不寫入
bash "$WS/scripts/init-project.sh" --profile=frontend --dry-run
```

## 不要做的事

- 不要試著手寫 `<project>/.claude/CLAUDE.md`——一律透過腳本以維持 SoT。
- 不要修改 `~/.claude/`、`~/.gemini/`、`~/.codex/`——那是 Stage 1 install.sh 的領域。
- 不要在 workspace repo 本身跑這個命令；腳本會偵測但仍以使用者明確指定目標為佳。
