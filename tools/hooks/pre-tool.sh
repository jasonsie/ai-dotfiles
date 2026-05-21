#!/bin/bash

# ============================================
# Claude Code Workspace — Pre-Commit Review Hook
# PreToolUse (Bash): 偵測 git commit 指令，
# 提醒使用 deep-review Skill 進行審查
# ============================================

# --- workspace-shim (cross-CLI compatibility) ---
WORKSPACE_CLI_NAME="${WORKSPACE_CLI_NAME:-claude}"
WORKSPACE_DIR="${WORKSPACE_DIR:-${CLAUDE_PROJECT_DIR:-}}"
export WORKSPACE_CLI_NAME WORKSPACE_DIR
# --- end shim ---

# 讀取 stdin JSON
INPUT=$(cat)

# 取得要執行的指令
COMMAND=$(echo "$INPUT" | grep -o '"command"\s*:\s*"[^"]*"' | head -1 | sed 's/.*:.*"\(.*\)"/\1/')

# 只處理 git commit 指令
case "$COMMAND" in
  *"git commit"*)
    # 檢查是否有 staged changes
    STAGED=$(git diff --cached --name-only 2>/dev/null)
    if [ -n "$STAGED" ]; then
      STAGED_COUNT=$(echo "$STAGED" | wc -l)
      echo "[pre-commit-review] Detected git commit with $STAGED_COUNT staged files."
      echo "[pre-commit-review] TIP: Use /deep-review skill for security + performance + style review before committing."
    fi
    ;;
esac

exit 0
