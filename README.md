# AI CLI Workspace

> **繁體中文** · [English below](#english)

服務 [Claude Code](https://code.claude.com)、[Gemini CLI](https://github.com/google-gemini/gemini-cli)、[Codex CLI](https://github.com/openai/codex) 的共用個人工作區
（fork 自 [`zeuikli/claude-code-workspace`](https://github.com/zeuikli/claude-code-workspace)）。
Claude Code 為 first-class 支援，內建四層載入框架、Advisor 模式與全域自動化 Hooks；Gemini / Codex 目前同步 rules 與 entry context（skills、agents 適配後續迭代）。

> 本 repository 的專案脈絡定義於 [`CONTEXT.md`](./CONTEXT.md)。跨專案的全域指示另由 [`tools/instructions/AGENTS.md`](./tools/instructions/AGENTS.md) 統一提供。

---

## 快速開始

在此 repository 中執行，先預覽、再安裝三個 CLI 的共用全域指示：

```bash
bash scripts/install.sh --instructions-only --dry-run
bash scripts/install.sh --instructions-only
```

此模式不更動模型、權限、hooks、MCP 或登入設定。完整能力安裝請見下一節。

### 跨 CLI 安裝

本 workspace 同時支援 Claude Code、Gemini CLI、Codex CLI。`scripts/install.sh` 是冪等的入口點：

```bash
bash scripts/install.sh                       # 預設 --target=all
bash scripts/install.sh --target=claude       # 僅安裝 Claude
bash scripts/install.sh --target=gemini       # 僅安裝 Gemini
bash scripts/install.sh --target=codex        # 僅安裝 Codex
bash scripts/install.sh --dry-run             # 不寫入，僅顯示變更
bash scripts/install.sh --force               # 強制覆寫即使內容相同
```

完整安裝會重新產生各 CLI 設定；只要統一全域指示時，請使用 `--instructions-only`。

### Shared global instructions

One source, loaded through each CLI's native user-level entry file:

```text
tools/instructions/AGENTS.md
  ├── ~/.claude/CLAUDE.md   (symlink)
  ├── ~/.gemini/GEMINI.md   (symlink)
  └── ~/.codex/AGENTS.md    (symlink)
```

Edit the source once; all three entries immediately read the same content on
reload. Project rules and CLI-specific settings remain separate. Existing entry
files are backed up before migration; unknown content requires review and
`--replace-instructions`. See [migration, verification, and rollback](docs/global-instructions.md).

### `tools/` Canonical 結構

所有跨 CLI 內容的真理之源在 `tools/`，**不要直接編輯 `.claude/`、`~/.gemini/`、`~/.codex/`**（它們是生成物）：

```
tools/
├── skills/      # SKILL.md 格式，三 CLI 共用
├── agents/      # Markdown agent specs，adapters 包裝至每個 CLI
├── rules/       # 跨 CLI 規則 + manifest.yaml（標註每條規則目標 CLI）
├── commands/    # Markdown 命令；Claude 直讀 .md、Gemini 轉 .toml
├── mcp/         # MCP server registry（neutral schema）
├── hooks/       # Hook scripts + manifest.yaml（事件名稱跨 CLI 對應）
└── settings/    # 每個 CLI 的設定模板
```

詳見 [`tools/README.md`](./tools/README.md) 與 [`docs/2026-05-21-cross-ai-cli-workspace-research.md`](./docs/2026-05-21-cross-ai-cli-workspace-research.md)。

---

## 四層載入框架

`/load-plan` 的設計依據 — 每層有明確的目的與成本：

| 層級 | 觸發 | 內容 | 預估成本 |
|------|------|------|---------|
| 🔴 **真實載入** | SessionStart Hook | `session-init.sh` + `CLAUDE.md` 本體 | ~708 tok |
| 🟡 **自動載入** | 每次 session | `core.md` + `subagent-strategy.md` + `context-management.md` | ~1,184 tok |
| 🟢 **按需載入** | 說出觸發詞 | 16 skills + 6 rules（按需，說了才載入）| 0 ～ 2,000 tok |
| ⚪ **不必載入** | 手動 Read | docs/archive、reference docs | — |

**設計原則**：每次 session 固定消耗 ~1,892 tokens（CLAUDE.md ~423 + 3 rules ~1,184 + 85% cache 折扣後實付 ~284），其餘零成本直到真正需要。

---

## 涵蓋領域

| 領域 | 指令 | 適用情境 |
|------|------|---------|
| 🖥 程式開發 | `/debug` `/perf` `/map` `/deep-review` `/frontend-design` | 除錯、效能、重構、UI |
| 📣 行銷策略 | `/marketing` | GTM、A/B 測試、競品分析 |
| ✍️ 文案撰寫 | `/writing` | 文案、SEO、Email、Landing Page |
| 🔍 研究分析 | `/research` `/research-best-practices` | 市場調查、文獻整理 |
| 📋 專案管理 | `/pm` `/agent-team` | Sprint、狀態報告、多 Agent |
| 🔧 Workspace | `/prime` `/retro` `/context-report` `/load-plan` | 冷啟、回顧、成本分析 |

---

## 效能優化

| 優化項目 | 效果 |
|---|---|
| Fetch 時間戳快取（TTL=300s）| 暖啟動 20–40ms（vs 300–800ms，-88%）|
| Sparse-checkout 初始 clone | 傳輸量 -40–60%，初始 clone 500–800ms（vs 1,000–1,500ms）|
| DEDUP 雙重載入保護 | workspace 本體執行時節省 ~708 tok |
| O(1) stat 日誌大小檢查 | 每次 prompt hook 省 ~18ms vs O(n) wc -l |

---

## 核心架構

### Advisor 模式（三層模型）

| 角色 | 模型 | 職責 |
|------|------|------|
| 執行者 | Sonnet 4.6 | 日常任務：實作、測試、搜尋 |
| 搜尋 | Haiku 4.5 | 探索 10+ 檔案的研究任務 |
| 顧問 | Opus 4.7 | 僅在架構決策、安全審計、邊界判斷時介入 |

### 自動化 Hooks（10 種事件）

| Hook | 用途 |
|------|------|
| `SessionStart` | 拉取最新設定；防止 double-load（當專案即 workspace 時） |
| `UserPromptSubmit` | 注入 Sub Agent 委派提醒 |
| `PreToolUse(bash)` | Commit 前強制執行 `/deep-review` |
| `PostToolUse(Edit/Write)` | 自動驗證 .sh/.json/.py 語法 |
| `PreCompact/PostCompact` | Auto Memory 保存提醒 |

### 記憶管理

- **官方 Auto Memory**（`autoMemoryEnabled: true`）— 跨 session 自動累積，`/memory` 查看
- `/compact <hint>` 壓縮時 Auto Memory 不受影響

---

## 本機安裝與跨專案共用

在此 repository 執行 `bash scripts/install.sh --instructions-only`，三個 CLI 即可
透過原生的使用者層級指示檔跨專案讀取同一份內容，不需要 SessionStart Hook。

**不要**再用 `echo` / `printf > ~/.claude/CLAUDE.md` 的舊式安裝範例；重導向會
沿著 symlink 覆寫所有 CLI 共用的來源。舊版自訂 bootstrap hook 也應移除。

---

## 分支說明

| 分支 | 用途 |
|------|------|
| `main` | 穩定的日常工作環境（預設使用） |
| `blog-archive` | Anthropic 官方部落格歸檔（凍結；不再自動更新） |

> CLI 文件（Claude Code / Codex / Gemini / Antigravity CLI）由 `.github/workflows/sync-cli-docs.yml` 每週同步至 `main` 的 `docs/claude/`、`docs/codex/upstream/`、`docs/gemini/upstream/`、`docs/agy/`。

---

<a name="english"></a>

## English

A shared personal workspace for [Claude Code](https://code.claude.com), [Gemini CLI](https://github.com/google-gemini/gemini-cli), and [Codex CLI](https://github.com/openai/codex)
(forked from [`zeuikli/claude-code-workspace`](https://github.com/zeuikli/claude-code-workspace)).
Claude Code is first-class with a **4-tier load framework**, Advisor Strategy, and automated hooks;
Gemini and Codex currently receive synchronized rules and entry context (skills / agents adaptation pending).
This repository's project context lives in [`CONTEXT.md`](./CONTEXT.md).
Cross-project defaults live in [`tools/instructions/AGENTS.md`](./tools/instructions/AGENTS.md).

### Quick Start

Run from this checkout to unify global instructions without changing CLI settings:

```bash
bash scripts/install.sh --instructions-only --dry-run
bash scripts/install.sh --instructions-only
```

Use `--target=claude|gemini|codex` to select one CLI. See
[global instructions](docs/global-instructions.md) for backups and verification.
Omit `--instructions-only` only when you also want the full configuration install.

### Performance Optimizations

| Optimization | Impact |
|---|---|
| Fetch timestamp caching (TTL=300s) | Warm-start 20–40ms (vs 300–800ms, -88%) |
| Sparse-checkout initial clone | Transport -40–60%, init 500–800ms (vs 1,000–1,500ms) |
| DEDUP protection against double-load | Saves ~708 tok when workspace is the project itself |
| O(1) stat for log size check | ~18ms faster per prompt hook vs O(n) wc -l |

### 4-Tier Load Framework

| Tier | Trigger | Content | Est. Cost |
|------|---------|---------|-----------|
| 🔴 **Real-time** | SessionStart Hook | `session-init.sh` + `CLAUDE.md` | ~708 tok |
| 🟡 **Auto** | Every session | 3 core rules (language/git/subagent/context) | ~1,184 tok |
| 🟢 **On-demand** | Say trigger keyword | 16 skills + 6 rules | 0–2,000 tok |
| ⚪ **Skip** | Manual Read only | docs/archive, reference docs | — |

**Design principle**: Fixed overhead of ~1,892 tokens per session (~284 effective with 85% prompt caching). Everything else costs zero until needed.

### Domain Coverage

| Domain | Commands | Use Cases |
|--------|----------|-----------|
| 🖥 Development | `/debug` `/perf` `/map` `/deep-review` `/frontend-design` | Bugs, performance, refactoring, UI |
| 📣 Marketing | `/marketing` | Campaigns, GTM, A/B testing, competitive analysis |
| ✍️ Content | `/writing` | Copywriting, SEO, email marketing, landing pages |
| 🔍 Research | `/research` `/research-best-practices` | Market research, literature reviews |
| 📋 PM | `/pm` `/agent-team` | Sprints, status reports, multi-agent tasks |
| 🔧 Workspace | `/prime` `/retro` `/context-report` `/load-plan` | Cold-start, retro, cost analysis |

### Advisor Strategy (3-Tier Model)

| Role | Model | Responsibility |
|------|-------|---------------|
| Executor | Sonnet 4.6 | Daily tasks: implementation, testing, search |
| Explorer | Haiku 4.5 | Research tasks spanning 10+ files |
| Advisor | Opus 4.7 | Architecture decisions, security audits only |

### Cross-Project Usage

The native user-level instruction files apply across projects; no bootstrap hook
is needed. Keep this checkout at a stable path, and edit only the shared source.
Remove old custom hooks that write `~/.claude/CLAUDE.md`: shell redirection follows
the symlink and would overwrite the shared source for all three CLIs.

---

## License

MIT License
