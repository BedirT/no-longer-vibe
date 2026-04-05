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
 * @param workspaceRoot - The root directory of the workspace.
 *   When omitted, defaults to the current working directory.
 */
export function createStandaloneMcpServer(workspaceRoot?: string): {
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
    (args) => {
      const result: Record<string, unknown> = {
        opened: true,
        path: args.path,
      };
      if (args.line !== undefined) {
        result.line = args.line;
      }
      return {
        content: [{ type: "text" as const, text: JSON.stringify(result) }],
      };
    },
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

      progress.files[args.path] = {
        status: "confirmed",
        read_at: new Date().toISOString(),
      };

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

  // --- Tools that return success but need extension for visual effect ---

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
    },
    (args) => {
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              success: true,
              note: "Install VS Code extension for visual highlighting",
              file: args.file,
              startLine: args.startLine,
              endLine: args.endLine,
              style: args.style,
            }),
          },
        ],
      };
    },
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
    () => {
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({ success: true }),
          },
        ],
      };
    },
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
    (args) => {
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({
              success: true,
              note: "Install VS Code extension for CodeLens",
              file: args.file,
              entries: args.entries.length,
            }),
          },
        ],
      };
    },
  );

  server.tool(
    "clear_blast_radius",
    "Clear the blast radius visualization",
    {},
    () => {
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({ success: true }),
          },
        ],
      };
    },
  );

  server.tool(
    "clear_all",
    "Reset all decorations, highlights, and visual state",
    {},
    () => {
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({ success: true }),
          },
        ],
      };
    },
  );

  return { server };
}

// --- Stats helper ---

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
  const server = createStandaloneMcpServer();
  const transport = new StdioServerTransport();
  server.server.connect(transport);
}
