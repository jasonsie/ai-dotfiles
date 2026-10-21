// Pi extension for the `learn` skill: Pi has no hooks, so this file plays the part of the
// prompt and end-of-turn hooks and hands each event to learn_hook.py next to it.
// Linked into ~/.pi/agent/extensions/ by scripts/install-hooks.py. Errors are swallowed so
// the extension never blocks a session.
import { spawnSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const script = join(dirname(realpathSync(fileURLToPath(import.meta.url))), "learn_hook.py");

function ask(mode: "prompt" | "stop", payload: Record<string, unknown>): Record<string, string> | undefined {
  try {
    const run = spawnSync("python3", [script, mode, "--cli", "pi"], {
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
  pi.on("before_agent_start", (event: any, ctx: any) => {
    const reply = ask("prompt", { ...session(ctx), prompt: event.prompt ?? "" });
    if (!reply?.context) return;
    return { message: { customType: "learn-cue", content: reply.context, display: false } };
  });

  pi.on("agent_before_settle", (event: any, ctx: any) => {
    if (event.outcome !== "completed") return;
    const reply = ask("stop", session(ctx));
    if (!reply?.continue) return;
    // A bare `continue: true` is dropped when the assistant spoke last; the entry gives the
    // model a user-role message to answer.
    return {
      continue: true,
      entries: [{ type: "custom_message", customType: "learn-plan-done", content: reply.continue, display: true }],
    };
  });
}
