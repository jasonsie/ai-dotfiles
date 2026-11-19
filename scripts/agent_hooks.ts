// Pi extension for ai-dotfiles' hooks. Pi has no hook files, so this one extension plays them
// all, handing each event to every feature's script in the shape scripts/agent_hooks.py reads:
// worktree-guard and small-commits before each tool call, worktree-guard and herdr-title when the
// session shuts down, and herdr-title each time the user submits a prompt (sent without waiting:
// it tags the agent's row in Herdr and must never slow a run). Linked into ~/.pi/agent/extensions/
// by scripts/install/skills.py; the link resolves back to scripts/, so the repo is one folder up.
// The footer shows the work name while the session has a worktree: the guard's reply carries `status`
// (a name, or null to clear it), on the session's next tool call after the worktree is made or deleted.
// A failed call is ignored: the extension never blocks a session on its own.
import { spawn, spawnSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repo = dirname(dirname(realpathSync(fileURLToPath(import.meta.url))));
// pre: asked before each tool call; prompt: told of each submitted prompt; end: asked at shutdown.
const features: { script: string; pre: boolean; prompt?: boolean; end: boolean; timeout: number }[] = [
  { script: join(repo, "skills", "worktree-guard", "scripts", "worktree_guard.py"), pre: true, end: true, timeout: 60_000 },
  { script: join(repo, "skills", "small-commits", "scripts", "small_commits.py"), pre: true, end: false, timeout: 30_000 },
  { script: join(repo, "skills", "herdr-title", "scripts", "herdr_title.py"), pre: false, prompt: true, end: true, timeout: 10_000 },
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

// Hand a payload to a script and move on: detached, no output read, every failure ignored.
function tell(script: string, kind: string, payload: Record<string, unknown>): void {
  try {
    const child = spawn("python3", [script, "hook", kind, "--cli", "pi"], { stdio: ["pipe", "ignore", "ignore"], detached: true });
    child.on("error", () => {});
    child.stdin?.on("error", () => {});
    child.stdin?.end(JSON.stringify(payload));
    child.unref();
  } catch {
    // never blocks the session
  }
}

function session(ctx: any): Record<string, unknown> {
  return { session_id: ctx.sessionManager?.getSessionId?.(), cwd: ctx.cwd, pid: process.pid, model: ctx.model?.id };
}

export default function (pi: any) {
  const notes = new Map<string, string>(); // the features' words to the model, shown with the tool's result

  pi.on("tool_call", (event: any, ctx: any) => {
    const said: string[] = [];
    for (const feature of features.filter((f) => f.pre)) {
      // Each feature sees the input as the one before it left it (worktree-guard may steer it).
      const reply = ask(feature.script, "pre", { ...session(ctx), tool_name: event.toolName ?? "", tool_input: event.input ?? {} }, feature.timeout);
      if (!reply) continue;
      if ("status" in reply) ctx.ui?.setStatus?.("worktree", reply.status ?? undefined);
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

  pi.on("before_agent_start", (event: any, ctx: any) => {
    try {
      const payload = { ...session(ctx), prompt: event.prompt ?? "", transcript_path: ctx.sessionManager?.getSessionFile?.() };
      for (const feature of features) if (feature.prompt) tell(feature.script, "prompt", payload);
    } catch {
      // never blocks the run
    }
  });

  pi.on("session_shutdown", (_event: any, ctx: any) => {
    for (const feature of features) if (feature.end) ask(feature.script, "end", session(ctx));
  });
}
