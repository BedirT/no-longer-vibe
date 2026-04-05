import * as vscode from "vscode";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

/** Highlight styles supported by the extension. */
export type HighlightStyle = "focus" | "context" | "warning" | "blast-radius";

/** A CodeLens entry for the set_codelens tool. */
export interface CodeLensEntry {
  line: number;
  text: string;
  command?: string;
}

/** Event emitted when an MCP tool is called. */
export interface McpToolEvent {
  tool: string;
  params: Record<string, unknown>;
}

/** All registered tool names. */
const TOOL_NAMES = [
  "highlight_range",
  "clear_highlights",
  "open_file",
  "mark_read",
  "mark_flagged",
  "set_codelens",
  "show_blast_radius",
  "update_progress_tree",
  "clear_all",
] as const;

/**
 * Returns the list of all MCP tool names registered by this server.
 */
export function getMcpToolNames(): readonly string[] {
  return TOOL_NAMES;
}

/**
 * Creates and configures an MCP server with all tool registrations.
 * Tools emit events via the returned EventEmitter so other extension
 * components can subscribe to tool invocations.
 */
export function createMcpServer(): {
  server: McpServer;
  toolEvents: vscode.EventEmitter<McpToolEvent>;
} {
  const toolEvents = new vscode.EventEmitter<McpToolEvent>();

  const server = new McpServer(
    {
      name: "no-longer-vibe",
      version: "0.1.0",
    },
    {
      capabilities: {
        tools: {},
      },
    },
  );

  registerHighlightRange(server, toolEvents);
  registerClearHighlights(server, toolEvents);
  registerOpenFile(server, toolEvents);
  registerMarkRead(server, toolEvents);
  registerMarkFlagged(server, toolEvents);
  registerSetCodelens(server, toolEvents);
  registerShowBlastRadius(server);
  registerUpdateProgressTree(server);
  registerClearAll(server, toolEvents);

  return { server, toolEvents };
}

/**
 * Starts the MCP server with stdio transport.
 * This should be called once during extension activation.
 */
export async function startMcpServer(
  server: McpServer,
): Promise<StdioServerTransport> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  return transport;
}

// --- Tool registrations ---

function registerHighlightRange(
  server: McpServer,
  toolEvents: vscode.EventEmitter<McpToolEvent>,
): void {
  server.tool(
    "highlight_range",
    "Highlight a range of lines in a file with a specified style",
    {
      file: z.string().describe("Relative file path"),
      startLine: z.number().int().min(1).describe("Start line number (1-based)"),
      endLine: z.number().int().min(1).describe("End line number (1-based, inclusive)"),
      style: z
        .enum(["focus", "context", "warning", "blast-radius"])
        .describe("Highlight style"),
    },
    (args) => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: args.file,
          startLine: args.startLine,
          endLine: args.endLine,
          style: args.style,
        },
      });

      return {
        content: [
          {
            type: "text" as const,
            text: `Highlighted ${args.file} lines ${String(args.startLine)}-${String(args.endLine)} with style '${args.style}'`,
          },
        ],
      };
    },
  );
}

function registerClearHighlights(
  server: McpServer,
  toolEvents: vscode.EventEmitter<McpToolEvent>,
): void {
  server.tool(
    "clear_highlights",
    "Clear highlights from a specific file or all files",
    {
      file: z.string().optional().describe("File path to clear, or omit to clear all"),
    },
    (args) => {
      const params: Record<string, unknown> = {};
      if (args.file) {
        params.file = args.file;
      }

      toolEvents.fire({ tool: "clear_highlights", params });

      const target = args.file ?? "all files";
      return {
        content: [
          {
            type: "text" as const,
            text: `Cleared highlights for ${target}`,
          },
        ],
      };
    },
  );
}

function registerOpenFile(
  server: McpServer,
  toolEvents: vscode.EventEmitter<McpToolEvent>,
): void {
  server.tool(
    "open_file",
    "Open a file and optionally scroll to a specific line",
    {
      path: z.string().describe("Relative file path"),
      line: z.number().int().min(1).optional().describe("Line number to scroll to"),
    },
    (args) => {
      const params: Record<string, unknown> = { path: args.path };
      if (args.line !== undefined) {
        params.line = args.line;
      }

      toolEvents.fire({ tool: "open_file", params });

      const suffix = args.line !== undefined ? ` at line ${String(args.line)}` : "";
      return {
        content: [
          {
            type: "text" as const,
            text: `Opened ${args.path}${suffix}`,
          },
        ],
      };
    },
  );
}

function registerMarkRead(
  server: McpServer,
  toolEvents: vscode.EventEmitter<McpToolEvent>,
): void {
  server.tool(
    "mark_read",
    "Mark a file as read (confirmed), updating its decoration to green",
    {
      path: z.string().describe("Relative file path"),
    },
    (args) => {
      toolEvents.fire({
        tool: "mark_read",
        params: { path: args.path },
      });

      return {
        content: [
          {
            type: "text" as const,
            text: `Marked ${args.path} as read`,
          },
        ],
      };
    },
  );
}

function registerMarkFlagged(
  server: McpServer,
  toolEvents: vscode.EventEmitter<McpToolEvent>,
): void {
  server.tool(
    "mark_flagged",
    "Mark a file as flagged for second pass, updating its decoration to orange",
    {
      path: z.string().describe("Relative file path"),
      reason: z.string().describe("Reason for flagging"),
    },
    (args) => {
      toolEvents.fire({
        tool: "mark_flagged",
        params: { path: args.path, reason: args.reason },
      });

      return {
        content: [
          {
            type: "text" as const,
            text: `Flagged ${args.path}: ${args.reason}`,
          },
        ],
      };
    },
  );
}

function registerSetCodelens(
  server: McpServer,
  toolEvents: vscode.EventEmitter<McpToolEvent>,
): void {
  server.tool(
    "set_codelens",
    "Set CodeLens annotations on a file, overriding automatic caller/callee annotations",
    {
      file: z.string().describe("Relative file path"),
      entries: z
        .array(
          z.object({
            line: z.number().int().min(1).describe("Line number"),
            text: z.string().describe("CodeLens text"),
            command: z.string().optional().describe("Optional command to execute"),
          }),
        )
        .describe("CodeLens entries to display"),
    },
    (args) => {
      toolEvents.fire({
        tool: "set_codelens",
        params: {
          file: args.file,
          entries: args.entries,
        },
      });

      return {
        content: [
          {
            type: "text" as const,
            text: `Set ${String(args.entries.length)} CodeLens entries on ${args.file}`,
          },
        ],
      };
    },
  );
}

function registerShowBlastRadius(server: McpServer): void {
  server.tool(
    "show_blast_radius",
    "Show the blast radius of changes to a symbol (stub - not yet implemented)",
    {
      symbol: z.string().describe("Symbol name to analyze"),
    },
    () => {
      return {
        content: [
          {
            type: "text" as const,
            text: "show_blast_radius is not implemented yet",
          },
        ],
      };
    },
  );
}

function registerUpdateProgressTree(server: McpServer): void {
  server.tool(
    "update_progress_tree",
    "Refresh the sidebar progress tree view (stub - not yet implemented)",
    () => {
      return {
        content: [
          {
            type: "text" as const,
            text: "update_progress_tree is not implemented yet",
          },
        ],
      };
    },
  );
}

function registerClearAll(
  server: McpServer,
  toolEvents: vscode.EventEmitter<McpToolEvent>,
): void {
  server.tool(
    "clear_all",
    "Reset all decorations, highlights, and visual state",
    () => {
      toolEvents.fire({ tool: "clear_all", params: {} });

      return {
        content: [
          {
            type: "text" as const,
            text: "Cleared all decorations and visual state",
          },
        ],
      };
    },
  );
}
