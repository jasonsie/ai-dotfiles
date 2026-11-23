// Pi extension for ai-dotfiles' hooks. Pi has no hook files, so this extension hands each event to
// the door, `ai-dotfiles hook <kind> --cli pi` (lib/door.py), in the shape scripts/agent_hooks.py
// reads; the door runs every feature whose feature.json wants it, in order, in one process. It asks
// before each tool call and when the session shuts down (with its reason), and waits for the reply;
// it tells of each input (with its source: typed or an extension's), each settled run (with the last
// reply and how the run ended) and each resumed session without waiting, so a feature that labels
// Herdr's rows never slows a run. Linked into ~/.pi/agent/extensions/ by scripts/install/skills.py;
// the link resolves back to scripts/, and the door it calls is the one beside it.
// The footer shows the work name while the session has a worktree: worktree-guard's reply carries
// `status` (a name, or null to clear it) on the session's next tool call after the worktree is made
// or deleted. A failed call is ignored: the extension never blocks a session on its own.
import { spawn, spawnSync } from "node:child_process";
import { realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const door = join(dirname(realpathSync(fileURLToPath(import.meta.url))), "ai-dotfiles");
// The door answers within its own time for each event (agent_hooks.py TIMEOUTS); this only ends one that hangs.
const LIMIT = 65_000;

function ask(kind: string, payload: Record<string, unknown>): Record<string, any> | undefined {
  try {
    const run = spawnSync(door, ["hook", kind, "--cli", "pi"], { input: JSON.stringify(payload), encoding: "utf8", timeout: LIMIT });
    const out = run.status === 0 ? run.stdout.trim() : "";
    return out ? JSON.parse(out) : undefined;
  } catch {
    return undefined;
  }
}

// Hand a payload to the door and move on: detached, no output read, every failure ignored.
function tell(kind: string, payload: Record<string, unknown>): void {
  try {
    const child = spawn(door, ["hook", kind, "--cli", "pi"], { stdio: ["pipe", "ignore", "ignore"], detached: true });
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
    const reply = ask("pre", { ...session(ctx), tool_name: event.toolName ?? "", tool_input: event.input ?? {} });
    if (!reply) return;
    if ("status" in reply) ctx.ui?.setStatus?.("worktree", reply.status ?? undefined);
    if (reply.block) return { block: true, reason: reply.reason };
    if (reply.input && event.input) Object.assign(event.input, reply.input); // Pi: mutate the input in place
    if (reply.note) notes.set(event.toolCallId, reply.note);
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
      tell("prompt", { ...session(ctx), prompt: event.text ?? "", source: event.source ?? "",
                       transcript_path: ctx.sessionManager?.getSessionFile?.() });
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
      tell("stop", { ...session(ctx), last_assistant_message: reply, outcome, transcript_path: ctx.sessionManager?.getSessionFile?.() });
    } catch {
      // never blocks the session
    }
    reply = "";
    outcome = "completed";
  });

  pi.on("session_start", (event: any, ctx: any) => {
    // Pi starts every launch with reason startup, a resumed session's too (pi -c, pi --session,
    // Herdr's restore); an in-app /resume says resume. A session with no kept state changes nothing.
    if (event.reason !== "resume" && event.reason !== "startup") return;
    tell("start", { ...session(ctx), source: "resume" });
  });

  pi.on("session_shutdown", (event: any, ctx: any) => {
    ask("end", { ...session(ctx), reason: event?.reason ?? "" });
  });
}
