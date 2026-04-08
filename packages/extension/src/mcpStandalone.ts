/**
 * Standalone MCP server for No Longer Vibe.
 *
 * This file is a separate entry point that does NOT import `vscode`.
 * It can be spawned by Claude Code via `.claude/mcp.json` as a plain
 * Node.js process communicating over stdio.
 *
 * Tools that need VS Code (highlights, CodeLens, etc.) return success
 * with a note suggesting the extension. Tools that interact with
 * the filesystem (mark_read, mark_flagged, show_blast_radius, etc.)
 * work fully standalone.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import * as fs from "node:fs";
import * as path from "node:path";
import { getSocketPath } from "./ipcProtocol";
import { IpcBridgeClient } from "./ipcClient";
import { cascadeExportsForConfirmed } from "./cascadeExports";

// --- Types (duplicated from types.ts to avoid pulling in vscode deps) ---

interface DependencyInfo {
  imports: string[];
  imported_by: string[];
}

interface ReadingOrderEntry {
  index: number;
  path: string;
  layer: string;
  reason: string;
  complexity: string;
  line_count: number;
  imports: string[];
  imported_by: string[];
  exports: string[];
}

interface CodebaseMap {
  version: string;
  repo_root: string;
  generated_at: string;
  content_hashes: Record<string, string>;
  total_files: number;
  reading_order: ReadingOrderEntry[];
  dependency_graph: Record<string, DependencyInfo>;
}

interface ProgressFile {
  status: string;
  read_at: string;
  note?: string;
  summary?: string;
  exports_read?: Record<string, { read_at: string; summary?: string | null }>;
}

interface ProgressJson {
  version: string;
  files: Record<string, ProgressFile>;
  stats: {
    total: number;
    confirmed: number;
    flagged: number;
    skimmed: number;
    unread: number;
  };
}

// --- All registered tool names ---

const TOOL_NAMES = [
  "highlight_range",
  "clear_highlights",
  "open_file",
  "mark_read",
  "mark_flagged",
  "set_codelens",
  "show_blast_radius",
  "clear_blast_radius",
  "update_progress_tree",
  "clear_all",
  "get_next_briefing",
  "get_read_status",
  "get_flagged_files",
  "complete_file",
  "mark_export_read",
] as const;

/**
 * Returns the list of all MCP tool names registered by the standalone server.
 */
export function getStandaloneToolNames(): readonly string[] {
  return TOOL_NAMES;
}

// --- Filesystem helpers ---

function getGuideDir(workspaceRoot: string): string {
  return path.join(workspaceRoot, ".codebase-guide");
}

function readProgressJson(workspaceRoot: string): ProgressJson | undefined {
  const progressPath = path.join(getGuideDir(workspaceRoot), "progress.json");
  if (!fs.existsSync(progressPath)) {
    return undefined;
  }
  const raw = fs.readFileSync(progressPath, "utf-8");
  return JSON.parse(raw) as ProgressJson;
}

function writeProgressJson(
  workspaceRoot: string,
  progress: ProgressJson,
): void {
  const guideDir = getGuideDir(workspaceRoot);
  if (!fs.existsSync(guideDir)) {
    fs.mkdirSync(guideDir, { recursive: true });
  }
  const progressPath = path.join(guideDir, "progress.json");
  fs.writeFileSync(progressPath, JSON.stringify(progress, null, 2) + "\n");
}

function readMapJson(workspaceRoot: string): CodebaseMap | undefined {
  const mapPath = path.join(getGuideDir(workspaceRoot), "map.json");
  if (!fs.existsSync(mapPath)) {
    return undefined;
  }
  const raw = fs.readFileSync(mapPath, "utf-8");
  return JSON.parse(raw) as CodebaseMap;
}

/**
 * Finds the file that exports the given symbol by scanning
 * reading_order entries.
 */
function findFileForSymbol(
  map: CodebaseMap,
  symbol: string,
): string | undefined {
  for (const entry of map.reading_order) {
    if (entry.exports.includes(symbol)) {
      return entry.path;
    }
  }
  return undefined;
}

/**
 * Computes the transitive blast radius for a file by walking
 * reverse dependency edges (imported_by) via BFS.
 */
function computeBlastRadius(map: CodebaseMap, filePath: string): string[] {
  const graph = map.dependency_graph;
  const visited = new Set<string>();
  const queue: string[] = [];

  const entry = graph[filePath];
  if (!entry) {
    return [];
  }

  for (const dep of entry.imported_by) {
    if (!visited.has(dep)) {
      visited.add(dep);
      queue.push(dep);
    }
  }

  while (queue.length > 0) {
    const current = queue.shift()!;
    const currentEntry = graph[current];
    if (!currentEntry) {
      continue;
    }

    for (const dep of currentEntry.imported_by) {
      if (!visited.has(dep)) {
        visited.add(dep);
        queue.push(dep);
      }
    }
  }

  return Array.from(visited);
}

// --- Server creation ---

/**
 * Creates and configures a standalone MCP server with all tool
 * registrations. This server operates on the filesystem directly
 * and does not depend on VS Code.
 *
 * When an IPC bridge client is provided and connected, visual tools
 * (highlight_range, clear_highlights, etc.) are forwarded to the
 * VS Code extension for real visual effects. Otherwise they degrade
 * gracefully.
 *
 * @param workspaceRoot - The root directory of the workspace.
 *   When omitted, defaults to the current working directory.
 * @param ipcClient - Optional IPC bridge client for forwarding
 *   visual tool calls to the VS Code extension.
 */
export function createStandaloneMcpServer(
  workspaceRoot?: string,
  ipcClient?: IpcBridgeClient,
): {
  server: McpServer;
} {
  const root = workspaceRoot ?? process.cwd();

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

  /**
   * Forwards a visual tool call to the extension via IPC with lazy
   * reconnection. Returns the extension's result on success, or an
   * isError response when the extension is not connected.
   */
  async function forwardVisualTool(
    tool: string,
    args: Record<string, unknown>,
  ) {
    if (ipcClient) {
      await ipcClient.tryReconnect();
      if (ipcClient.isConnected()) {
        const result = await ipcClient.callTool(tool, args);
        if (result) return result;
        // Connected but call failed (timeout, socket error)
        return callFailedError(tool);
      }
    }
    return disconnectedError(tool);
  }

  // --- Tools that work standalone ---

  server.tool(
    "open_file",
    "Open a file and optionally scroll to a specific line",
    {
      path: z.string().describe("Relative file path"),
      line: z
        .number()
        .int()
        .min(1)
        .optional()
        .describe("Line number to scroll to"),
    },
    async (args) => forwardVisualTool("open_file", args),
  );

  server.tool(
    "mark_read",
    "Mark a file as read (confirmed), updating progress.json on disk",
    {
      path: z.string().describe("Relative file path"),
    },
    (args) => {
      const progress = readProgressJson(root) ?? {
        version: "1.0.0",
        files: {},
        stats: { total: 0, confirmed: 0, flagged: 0, skimmed: 0, unread: 0 },
      };

      const existingExportsRead = progress.files[args.path]?.exports_read;
      progress.files[args.path] = {
        status: "confirmed",
        read_at: new Date().toISOString(),
        exports_read: existingExportsRead,
      };

      cascadeConfirmedToExports(progress, args.path, root);
      recomputeStats(progress);
      writeProgressJson(root, progress);

      return {
        content: [
          {
            type: "text" as const,
            text: `Marked ${args.path} as confirmed in progress.json`,
          },
        ],
      };
    },
  );

  server.tool(
    "mark_flagged",
    "Mark a file as flagged for second pass, updating progress.json on disk",
    {
      path: z.string().describe("Relative file path"),
      reason: z.string().describe("Reason for flagging"),
    },
    (args) => {
      const progress = readProgressJson(root) ?? {
        version: "1.0.0",
        files: {},
        stats: { total: 0, confirmed: 0, flagged: 0, skimmed: 0, unread: 0 },
      };

      progress.files[args.path] = {
        status: "flagged",
        read_at: new Date().toISOString(),
        note: args.reason,
      };

      recomputeStats(progress);
      writeProgressJson(root, progress);

      return {
        content: [
          {
            type: "text" as const,
            text: `Marked ${args.path} as flagged: ${args.reason}`,
          },
        ],
      };
    },
  );

  server.tool(
    "show_blast_radius",
    "Show the blast radius of changes to a symbol — returns all transitively affected files",
    {
      symbol: z.string().describe("Symbol name to analyze"),
    },
    (args) => {
      const map = readMapJson(root);
      if (!map) {
        return {
          content: [
            {
              type: "text" as const,
              text: "map.json not found. Run /read-index first.",
            },
          ],
        };
      }

      const filePath = findFileForSymbol(map, args.symbol);
      if (!filePath) {
        return {
          content: [
            {
              type: "text" as const,
              text: `Symbol '${args.symbol}' not found in any file exports.`,
            },
          ],
        };
      }

      const affected = computeBlastRadius(map, filePath);
      const result = {
        symbol: args.symbol,
        sourceFile: filePath,
        affectedFiles: affected,
        affectedCount: affected.length,
      };

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(result, null, 2),
          },
        ],
      };
    },
  );

  server.tool(
    "update_progress_tree",
    "Return current progress stats from progress.json",
    {},
    () => {
      const progress = readProgressJson(root);
      if (!progress) {
        return {
          content: [
            {
              type: "text" as const,
              text: "No progress.json found. No files have been read yet.",
            },
          ],
        };
      }

      // Recount from the actual file entries
      const counts = { confirmed: 0, flagged: 0, skimmed: 0 };
      for (const entry of Object.values(progress.files)) {
        if (entry.status === "confirmed") counts.confirmed++;
        else if (entry.status === "flagged") counts.flagged++;
        else if (entry.status === "skimmed") counts.skimmed++;
      }

      const total = progress.stats.total || Object.keys(progress.files).length;
      const unread = total - counts.confirmed - counts.flagged - counts.skimmed;

      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(
              {
                total,
                confirmed: counts.confirmed,
                flagged: counts.flagged,
                skimmed: counts.skimmed,
                unread: Math.max(0, unread),
                files_read: Object.keys(progress.files).length,
              },
              null,
              2,
            ),
          },
        ],
      };
    },
  );

  // --- Reading session tools (context-efficient) ---

  server.tool(
    "get_next_briefing",
    "Get the next unread file briefing with all context needed for a reading session. Returns the file path, layer, complexity, imports with their read statuses and summaries, exports, and progress stats. Use this instead of reading map.json/progress.json directly.",
    {},
    () => {
      const map = readMapJson(root);
      if (!map) {
        return jsonResult({ status: "error", message: "map.json not found. Run /read-index first." });
      }
      const progress = readProgressJson(root);
      if (!progress) {
        return jsonResult({ status: "error", message: "progress.json not found. Run /read-index first." });
      }

      // Find next unread file
      const nextEntry = map.reading_order.find((entry) => {
        const fileProgress = progress.files[entry.path];
        return !fileProgress || fileProgress.status === "unread";
      });

      if (!nextEntry) {
        return jsonResult({ status: "all_read", progress: progress.stats });
      }

      // Build import details with statuses and summaries
      const imports = nextEntry.imports.map((imp) => {
        const impProgress = progress.files[imp];
        return {
          path: imp,
          status: impProgress?.status ?? "unread",
          summary: impProgress?.summary ?? null,
        };
      });

      return jsonResult({
        status: "ok",
        path: nextEntry.path,
        layer: nextEntry.layer,
        line_count: nextEntry.line_count,
        complexity: nextEntry.complexity,
        reason: nextEntry.reason,
        imports,
        imported_by: nextEntry.imported_by,
        exports: nextEntry.exports,
        progress: progress.stats,
      });
    },
  );

  server.tool(
    "get_read_status",
    "Get current reading progress summary. Returns total, confirmed, flagged, skimmed, unread counts, current layer, next file, and session count.",
    {},
    () => {
      const map = readMapJson(root);
      const progress = readProgressJson(root);
      if (!map || !progress) {
        return jsonResult({ status: "error", message: "map.json or progress.json not found. Run /read-index first." });
      }

      // Find current layer (first layer with unread files)
      const layers = map.reading_order.map((e) => e.layer);
      let currentLayer: string | null = null;
      let currentLayerTotal = 0;
      let currentLayerRead = 0;
      for (const entry of map.reading_order) {
        const fileProgress = progress.files[entry.path];
        if (!fileProgress || fileProgress.status === "unread") {
          if (!currentLayer) currentLayer = entry.layer;
        }
      }
      if (currentLayer) {
        for (const entry of map.reading_order) {
          if (entry.layer === currentLayer) {
            currentLayerTotal++;
            const fp = progress.files[entry.path];
            if (fp && fp.status !== "unread") currentLayerRead++;
          }
        }
      }

      // Find next file
      const nextEntry = map.reading_order.find((entry) => {
        const fp = progress.files[entry.path];
        return !fp || fp.status === "unread";
      });

      return jsonResult({
        total: progress.stats.total,
        confirmed: progress.stats.confirmed,
        flagged: progress.stats.flagged,
        skimmed: progress.stats.skimmed,
        unread: progress.stats.unread,
        current_layer: currentLayer,
        current_layer_pct: currentLayerTotal > 0
          ? Math.round((currentLayerRead / currentLayerTotal) * 100)
          : 0,
        next_file: nextEntry?.path ?? null,
        flagged_count: progress.stats.flagged,
        sessions: (progress as Record<string, unknown>).sessions ?? 0,
      });
    },
  );

  server.tool(
    "get_flagged_files",
    "Get all flagged files with their notes, summaries, and reading order context. Use this for the /read-flagged second pass.",
    {},
    () => {
      const map = readMapJson(root);
      const progress = readProgressJson(root);
      if (!map || !progress) {
        return jsonResult({ status: "error", message: "map.json or progress.json not found." });
      }

      const roLookup = new Map(map.reading_order.map((e) => [e.path, e]));
      const flagged: Array<Record<string, unknown>> = [];

      for (const [filePath, entry] of Object.entries(progress.files)) {
        if (entry.status !== "flagged") continue;
        const roEntry = roLookup.get(filePath);
        flagged.push({
          path: filePath,
          note: entry.note ?? null,
          summary: entry.summary ?? null,
          layer: roEntry?.layer ?? "unknown",
          line_count: roEntry?.line_count ?? 0,
          reading_order_index: roEntry?.index ?? -1,
          imports: roEntry?.imports ?? [],
          imported_by: roEntry?.imported_by ?? [],
          exports: roEntry?.exports ?? [],
        });
      }

      // Sort by reading order index
      flagged.sort((a, b) => (a.reading_order_index as number) - (b.reading_order_index as number));

      if (flagged.length === 0) {
        return jsonResult({ status: "none_flagged" });
      }

      return jsonResult({ status: "ok", flagged });
    },
  );

  server.tool(
    "complete_file",
    "Mark a file as confirmed, flagged, or skimmed with an optional note and summary. Updates progress.json atomically.",
    {
      path: z.string().describe("Relative file path"),
      status: z.enum(["confirmed", "flagged", "skimmed"]).describe("Completion status"),
      note: z.string().optional().describe("Optional note (e.g., why flagged)"),
      summary: z.string().optional().describe("One-line summary of the file"),
    },
    (args) => {
      const progress = readProgressJson(root) ?? {
        version: "1.0.0",
        files: {},
        stats: { total: 0, confirmed: 0, flagged: 0, skimmed: 0, unread: 0 },
      };

      const existingExportsReadForComplete = progress.files[args.path]?.exports_read;
      progress.files[args.path] = {
        status: args.status,
        read_at: new Date().toISOString(),
        note: args.note,
        summary: args.summary,
        exports_read: existingExportsReadForComplete,
      };

      if (args.status === "confirmed") {
        cascadeConfirmedToExports(progress, args.path, root);
      }
      recomputeStats(progress);
      writeProgressJson(root, progress);

      // Forward to VS Code extension for visual update if connected
      if (ipcClient?.isConnected()) {
        const toolName = args.status === "flagged" ? "mark_flagged" : "mark_read";
        const toolArgs = args.status === "flagged"
          ? { path: args.path, reason: args.note ?? "" }
          : { path: args.path };
        void ipcClient.callTool(toolName, toolArgs);
      }

      return jsonResult({
        status: "ok",
        path: args.path,
        marked_as: args.status,
        progress: progress.stats,
      });
    },
  );

  server.tool(
    "mark_export_read",
    "Mark a single export/symbol within a file as read, enabling partial file progress tracking. Updates exports_read in progress.json.",
    {
      path: z.string().describe("Relative file path"),
      export_name: z.string().describe("Name of the export/symbol to mark as read"),
      summary: z.string().optional().describe("Optional one-line summary of the export"),
    },
    (args) => {
      const progress = readProgressJson(root) ?? {
        version: "1.0.0",
        files: {},
        stats: { total: 0, confirmed: 0, flagged: 0, skimmed: 0, unread: 0 },
      };

      // Ensure the file entry exists
      if (!progress.files[args.path]) {
        progress.files[args.path] = {
          status: "unread",
          read_at: new Date().toISOString(),
        };
      }

      const fileEntry = progress.files[args.path];
      if (!fileEntry.exports_read) {
        fileEntry.exports_read = {};
      }

      fileEntry.exports_read[args.export_name] = {
        read_at: new Date().toISOString(),
        summary: args.summary,
      };

      writeProgressJson(root, progress);

      return jsonResult({
        status: "ok",
        path: args.path,
        export_name: args.export_name,
        exports_read: fileEntry.exports_read,
        progress: progress.stats,
      });
    },
  );

  // --- Tools that forward to extension when IPC connected, else degrade ---

  server.tool(
    "highlight_range",
    "Highlight a range of lines in a file with a specified style",
    {
      file: z.string().describe("Relative file path"),
      startLine: z
        .number()
        .int()
        .min(1)
        .describe("Start line number (1-based)"),
      endLine: z
        .number()
        .int()
        .min(1)
        .describe("End line number (1-based, inclusive)"),
      style: z
        .enum(["focus", "context", "warning", "blast-radius"])
        .describe("Highlight style"),
      importance: z
        .number()
        .min(0)
        .max(1)
        .optional()
        .describe("Importance weight (0.0-1.0). When provided with 'focus' style, renders opacity-tiered highlighting."),
    },
    async (args) => forwardVisualTool("highlight_range", args),
  );

  server.tool(
    "clear_highlights",
    "Clear highlights from a specific file or all files",
    {
      file: z
        .string()
        .optional()
        .describe("File path to clear, or omit to clear all"),
    },
    async (args) => forwardVisualTool("clear_highlights", args),
  );

  server.tool(
    "set_codelens",
    "Set CodeLens annotations on a file",
    {
      file: z.string().describe("Relative file path"),
      entries: z
        .array(
          z.object({
            line: z.number().int().min(1).describe("Line number"),
            text: z.string().describe("CodeLens text"),
            command: z
              .string()
              .optional()
              .describe("Optional command to execute"),
          }),
        )
        .describe("CodeLens entries to display"),
    },
    async (args) => forwardVisualTool("set_codelens", args),
  );

  server.tool(
    "clear_blast_radius",
    "Clear the blast radius visualization",
    {},
    async () => forwardVisualTool("clear_blast_radius", {}),
  );

  server.tool(
    "clear_all",
    "Reset all decorations, highlights, and visual state",
    {},
    async () => forwardVisualTool("clear_all", {}),
  );

  return { server };
}

// --- Helpers ---

function jsonResult(data: Record<string, unknown>) {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
  };
}

/**
 * Returns an MCP error response for visual tools when the VS Code
 * extension is not connected. Uses `isError: true` so Claude knows
 * the visual action did not happen.
 */
function disconnectedError(tool: string) {
  return {
    isError: true as const,
    content: [
      {
        type: "text" as const,
        text: `VS Code extension not connected — ${tool} had no visual effect. Ensure the No Longer Vibe extension is active in VS Code.`,
      },
    ],
  };
}

/**
 * Returns an MCP error response when the extension is connected but
 * a tool call failed (timeout, socket error, etc.).
 */
function callFailedError(tool: string) {
  return {
    isError: true as const,
    content: [
      {
        type: "text" as const,
        text: `VS Code extension is connected but ${tool} call failed. The extension may have encountered an error.`,
      },
    ],
  };
}

/**
 * When a file is marked "confirmed", cascades that status to all
 * exports that have no existing entry in exports_read.
 * Reads map.json to look up the file's exports.
 */
function cascadeConfirmedToExports(
  progress: ProgressJson,
  filePath: string,
  workspaceRoot: string,
): void {
  const map = readMapJson(workspaceRoot);
  if (!map) return;

  const entry = map.reading_order.find((e) => e.path === filePath);
  if (!entry || entry.exports.length === 0) return;

  const fileEntry = progress.files[filePath];
  if (!fileEntry) return;

  cascadeExportsForConfirmed(fileEntry, entry.exports, new Date().toISOString());
}

function recomputeStats(progress: ProgressJson): void {
  let confirmed = 0;
  let flagged = 0;
  let skimmed = 0;

  for (const entry of Object.values(progress.files)) {
    if (entry.status === "confirmed") confirmed++;
    else if (entry.status === "flagged") flagged++;
    else if (entry.status === "skimmed") skimmed++;
  }

  progress.stats.confirmed = confirmed;
  progress.stats.flagged = flagged;
  progress.stats.skimmed = skimmed;
  progress.stats.unread = Math.max(
    0,
    progress.stats.total - confirmed - flagged - skimmed,
  );
}

// --- Main entry point (only runs when executed directly) ---

function isMainModule(): boolean {
  // When bundled by esbuild into a CJS file, require.main === module
  // works. When running under vitest/ts-node, we skip auto-start.
  try {
    return require.main === module;
  } catch {
    return false;
  }
}

if (isMainModule()) {
  const root = process.cwd();
  const socketPath = getSocketPath(root);
  const client = new IpcBridgeClient(socketPath);

  // Always pass the client so visual tools can lazily reconnect
  // even if the initial connection fails (extension not yet active).
  client.connect().then(() => {
    const server = createStandaloneMcpServer(root, client);
    const transport = new StdioServerTransport();
    server.server.connect(transport);
  });
}
