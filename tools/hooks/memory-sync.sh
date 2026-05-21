#!/bin/bash
set -e

# ============================================
# Claude Code Workspace — Memory Sync
# 將 Memory.md 的變更推送回 GitHub
# ============================================

# CONFIG_REPO kept for reference; remote URL is read from git config at runtime

# --- workspace-shim (cross-CLI compatibility) ---
WORKSPACE_CLI_NAME="${WORKSPACE_CLI_NAME:-claude}"
WORKSPACE_DIR="${WORKSPACE_DIR:-${CLAUDE_PROJECT_DIR:-}}"
export WORKSPACE_CLI_NAME WORKSPACE_DIR
# --- end shim ---

# --- 定位 workspace 目錄 ---
# 優先採用 shim 設定的 WORKSPACE_DIR（來自 CLAUDE_PROJECT_DIR），讓 hook 在任意專案都能運作。
# 僅在 shim 未提供且偵測到 cloud remote 時 fallback 到 /tmp。
if [ -z "${WORKSPACE_DIR:-}" ]; then
  if [ "$CLAUDE_CODE_REMOTE" = "true" ]; then
    WORKSPACE_DIR="/tmp/claude-code-workspace"
  else
    echo "[memory-sync] WORKSPACE_DIR unset and no project context, skipping"
    exit 0
  fi
fi

# 確認目錄存在
if [ ! -d "$WORKSPACE_DIR/.git" ]; then
  echo "[memory-sync] Workspace not found at $WORKSPACE_DIR, skipping"
  exit 0
fi

cd "$WORKSPACE_DIR"

# --- 檢查 Memory.md 是否有變更 ---
if git diff --quiet HEAD -- Memory.md 2>/dev/null && git diff --quiet --staged -- Memory.md 2>/dev/null; then
  # 沒有變更，不需要同步
  exit 0
fi

# --- 拉取最新，避免衝突 ---
git fetch --quiet origin main 2>/dev/null || true
git stash --quiet 2>/dev/null || true
git rebase --quiet origin/main 2>/dev/null || true
git stash pop --quiet 2>/dev/null || true

# --- Commit 並推送 ---
git add Memory.md
git commit --quiet -m "Auto-sync Memory.md — $(date '+%Y-%m-%d %H:%M')" 2>/dev/null || true

# 推送（含重試機制）
MAX_RETRIES=4
RETRY_DELAY=2
for i in $(seq 1 $MAX_RETRIES); do
  if git push --quiet origin main 2>/dev/null; then
    echo "[memory-sync] Memory.md synced to GitHub"
    exit 0
  fi
  echo "[memory-sync] Push failed, retrying in ${RETRY_DELAY}s... ($i/$MAX_RETRIES)"
  sleep $RETRY_DELAY
  RETRY_DELAY=$((RETRY_DELAY * 2))
done

echo "[memory-sync] Push failed after $MAX_RETRIES retries"
exit 1
