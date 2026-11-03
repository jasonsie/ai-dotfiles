// Pi extension for ai-dotfiles' hooks. Pi has no hook files, so this one extension plays them
// all, handing each event to every feature's script in the shape scripts/agent_hooks.py reads:
// worktree-guard and small-commits before each tool call, worktree-guard when the session shuts
// down. Linked into ~/.pi/agent/extensions/ by scripts/install/skills.py; the link resolves back
// to scripts/, so the repo is one folder up.
// A failed call is ignored: the extension never blocks a session on its own.
import { spawnSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repo = dirname(dirname(realpathSync(fileURLToPath(import.meta.url))));
const features = [
  { script: join(repo, "skills", "worktree-guard", "scripts", "worktree_guard.py"), end: true, timeout: 60_000 },
  { script: join(repo, "skills", "small-commits", "scripts", "small_commits.py"), end: false, timeout: 30_000 },
];

function ask(script: string, kind: string, payload: Record<string, unknown>, timeout = 10_000): Record<string, any> | undefined {
  try {
    const run = spawnSync("python3", [script, "hook", kind, "--cli", "pi"], {
      input: JSON.stringify(payload),
      encoding: "utf8",
      timeout,
    });
    const out = run.status === 0 ? run.stdout.trim() : "";
    return out ? JSON.parse(out) : undefined;
  } catch {
    return undefined;
  }
}

function session(ctx: any): Record<string, unknown> {
  return { session_id: ctx.sessionManager?.getSessionId?.(), cwd: ctx.cwd, pid: process.pid, model: ctx.model?.id };
}

export default function (pi: any) {
  const notes = new Map<string, string>(); // the features' words to the model, shown with the tool's result

  pi.on("tool_call", (event: any, ctx: any) => {
    const said: string[] = [];
    for (const feature of features) {
      // Each feature sees the input as the one before it left it (worktree-guard may steer it).
      const reply = ask(feature.script, "pre", { ...session(ctx), tool_name: event.toolName ?? "", tool_input: event.input ?? {} }, feature.timeout);
      if (!reply) continue;
      if (reply.block) return { block: true, reason: reply.reason };
      if (reply.input && event.input) Object.assign(event.input, reply.input); // Pi: mutate the input in place
      if (reply.note) said.push(reply.note);
    }
    if (said.length) notes.set(event.toolCallId, said.join("\n"));
  });

  pi.on("tool_result", (event: any) => {
    const note = notes.get(event.toolCallId);
    if (!note) return;
    notes.delete(event.toolCallId);
    return { content: [...(event.content ?? []), { type: "text", text: note }] };
  });

  pi.on("session_shutdown", (_event: any, ctx: any) => {
    for (const feature of features) if (feature.end) ask(feature.script, "end", session(ctx));
  });
}
