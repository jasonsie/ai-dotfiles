#!/bin/bash
# The setup script of a Claude Code cloud environment: ai-dotfiles in every session started in it.
# Paste this file as is at claude.ai/code (environment selector, the environment's settings,
# Setup script), and set CLAUDE_CODE_PLUGIN_DIRS as the report's last line says. It runs as root
# before Claude Code starts. Its result is cached for about a week, so a change on main reaches new
# sessions within a week, or at once after any edit here, which rebuilds the cache. It never fails
# the session; the report is /opt/ai-dotfiles-setup.txt (docs/how-it-works.md, Cloud sessions).
rm -rf /opt/ai-dotfiles
if git clone --quiet --depth 1 https://github.com/jasonsie/ai-dotfiles /opt/ai-dotfiles; then
  bash /opt/ai-dotfiles/scripts/cloud/setup.sh || true
else
  echo "FAIL clone      https://github.com/jasonsie/ai-dotfiles" >/opt/ai-dotfiles-setup.txt
fi
exit 0
