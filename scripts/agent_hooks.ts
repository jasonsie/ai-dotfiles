// Pi extension for ai-dotfiles' hooks. Pi has no hook files, so this one extension plays them
// all, handing each event to every feature's script in the shape scripts/agent_hooks.py reads:
// worktree-guard and small-commits before each tool call, worktree-guard and herdr-title when the
// session shuts down (with its reason), and herdr-title each time input arrives (with its source:
// typed or an extension's), each time a run settles (with the last reply and how the run ended)
// and when a session resumes. herdr-title's calls are sent without waiting: they label the agent's
// row in Herdr and must never slow a run. Linked into ~/.pi/agent/extensions/ by
// scripts/install/skills.py; the link resolves back to scripts/, so the repo is one folder up.
// The footer shows the work name while the session has a worktree: the guard's reply carries `status`
// (a name, or null to clear it), on the session's next tool call after the worktree is made or deleted.
// A failed call is ignored: the extension never blocks a session on its own.
import { spawn, spawnSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const repo = dirname(dirname(realpathSync(fileURLToPath(import.meta.url))));
// pre: asked before each tool call; prompt, stop, start: told of each input, each settled run and
// each resumed session; end: asked at shutdown.
type Feature = { script: string; pre: boolean; prompt?: boolean; stop?: boolean; start?: boolean; end: boolean; timeout: number };
const features: Feature[] = [
  { script: join(repo, "skills", "worktree-guard", "scripts", "worktree_guard.py"), pre: true, end: true, timeout: 60_000 },
  { script: join(repo, "skills", "small-commits", "scripts", "small_commits.py"), pre: true, end: false, timeout: 30_000 },
  { script: join(repo, "skills", "herdr-title", "scripts", "herdr_title.py"), pre: false, prompt: true, stop: true, start: true, end: true, timeout: 10_000 },
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

  // The raw input, before Pi expands a skill into it, also when it arrives queued during a run.
  pi.on("input", (event: any, ctx: any) => {
    try {
      const payload = { ...session(ctx), prompt: event.text ?? "", source: event.source ?? "",
                        transcript_path: ctx.sessionManager?.getSessionFile?.() };
      for (const feature of features) if (feature.prompt) tell(feature.script, "prompt", payload);
    } catch {
      // never blocks the input
    }
  });

  // The last turn's reply and outcome, sent once the run has settled: retries and queued work are over.
  let reply = "";
  let outcome = "completed";
  pi.on("turn_end", (event: any) => {
    const message = event.message ?? {};
    if (message.role === "assistant") {
      const text = (message.content ?? []).filter((part: any) => part?.type === "text").map((part: any) => part.text).join("\n");
      if (text) reply = text;
    }
    outcome = event.outcome ?? "completed";
  });

  pi.on("agent_settled", (_event: any, ctx: any) => {
    try {
      if (ctx.isIdle && !ctx.isIdle()) return;
      const payload = { ...session(ctx), last_assistant_message: reply, outcome, transcript_path: ctx.sessionManager?.getSessionFile?.() };
      for (const feature of features) if (feature.stop) tell(feature.script, "stop", payload);
    } catch {
      // never blocks the session
    }
    reply = "";
    outcome = "completed";
  });

  pi.on("session_start", (event: any, ctx: any) => {
    if (event.reason !== "resume") return;
    for (const feature of features) if (feature.start) tell(feature.script, "start", { ...session(ctx), source: "resume" });
  });

  pi.on("session_shutdown", (event: any, ctx: any) => {
    for (const feature of features) if (feature.end) ask(feature.script, "end", { ...session(ctx), reason: event?.reason ?? "" });
  });
}
