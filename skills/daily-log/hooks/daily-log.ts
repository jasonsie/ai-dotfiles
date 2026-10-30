// Pi extension for the daily-log skill: Pi has no hooks, so this file plays the part of the
// PostToolUse and Stop hooks and hands each event to scripts/daily_log.py in this skill.
// Linked into ~/.pi/agent/extensions/ by scripts/install/skills.py; the link resolves back
// to skills/daily-log/hooks/, so the script is one folder up. Errors are swallowed so the
// extension never blocks a session.
import { spawnSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const script = join(dirname(dirname(realpathSync(fileURLToPath(import.meta.url)))), "scripts", "daily_log.py");

function ask(mode: "tool" | "stop", payload: Record<string, unknown>): Record<string, string> | undefined {
  try {
    const run = spawnSync("python3", [script, "hook", mode, "--cli", "pi"], {
      input: JSON.stringify(payload),
      encoding: "utf8",
      timeout: 10_000,
    });
    const out = run.status === 0 ? run.stdout.trim() : "";
    return out ? JSON.parse(out) : undefined;
  } catch {
    return undefined;
  }
}

function session(ctx: any): Record<string, unknown> {
  return { session_id: ctx.sessionManager?.getSessionId?.(), cwd: ctx.cwd };
}

export default function (pi: any) {
  pi.on("tool_result", (event: any, ctx: any) => {
    ask("tool", { ...session(ctx), tool_name: event.toolName ?? "" });
  });

  pi.on("agent_before_settle", (event: any, ctx: any) => {
    if (event.outcome !== "completed") return;
    const reply = ask("stop", session(ctx));
    if (!reply?.continue) return;
    // A bare `continue: true` is dropped when the assistant spoke last; the entry gives the
    // model a user-role message to answer.
    return {
      continue: true,
      entries: [{ type: "custom_message", customType: "daily-log", content: reply.continue, display: true }],
    };
  });
}
