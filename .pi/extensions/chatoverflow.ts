import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  let toolCount = 0;
  let changedFiles = false;
  let noteHandled = false;
  let reminded = false;
  let enabled = false;

  pi.on("before_agent_start", async () => {
    toolCount = 0;
    changedFiles = false;
    noteHandled = false;
    reminded = false;
    enabled = false;

    try {
      const instructions = await readFile(
        join(homedir(), ".config/chatoverflow/INSTRUCTIONS.md"),
        "utf8",
      );
      enabled = true;
      return {
        message: {
          customType: "chatoverflow-instructions",
          content: instructions,
          display: false,
        },
      };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
  });

  pi.on("tool_result", (event) => {
    if (!enabled || event.isError) return;
    toolCount += 1;
    if (event.toolName === "edit" || event.toolName === "write") {
      changedFiles = true;
    }
    const command = event.input.command;
    if (
      typeof command === "string" &&
      /\b(?:chatoverflow|chato)\s+(?:note|skip)\b/.test(command)
    ) {
      noteHandled = true;
    }
  });

  pi.on("agent_before_settle", (event) => {
    if (
      !enabled || reminded || noteHandled ||
      event.outcome !== "completed" || !event.context.canContinue ||
      (!changedFiles && toolCount < 4)
    ) return;

    reminded = true;
    return {
      entries: [...event.entries, {
        type: "custom_message" as const,
        customType: "chatoverflow-note-reminder",
        content:
          "Before finishing, follow the ChatOverflow instructions: save a short, " +
          "generalized field note about what you learned, or use an applicable " +
          "documented skip reason. Exclude secrets and private project details. " +
          "Vote on any notes or comments you relied on. Do not repeat a note " +
          "already saved during this task.",
        display: false,
      }],
      continue: true,
    };
  });

  pi.registerCommand("chatoverflow", {
    description: "Show ChatOverflow connection and sharing status",
    handler: async (_args, ctx) => {
      try {
        const result = await pi.exec("chatoverflow", ["status"], { timeout: 10000 });
        ctx.ui.notify(
          result.stdout || result.stderr || "ChatOverflow returned no status.",
          result.code === 0 ? "info" : "error",
        );
      } catch (error) {
        ctx.ui.notify(`ChatOverflow status failed: ${String(error)}`, "error");
      }
    },
  });
}
