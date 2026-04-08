import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";

// Do NOT mock vscode — the standalone server must not import it at all.
// We verify this implicitly: if the import succeeds without a vscode mock,
// the module is truly standalone.

describe("mcpStandalone", () => {
  let tmpDir: string;
  let guideDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "nlv-test-"));
    guideDir = path.join(tmpDir, ".codebase-guide");
    fs.mkdirSync(guideDir, { recursive: true });
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  describe("createStandaloneMcpServer", () => {
    it("creates without importing vscode", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      expect(server).toBeDefined();
    });

    it("registers all 15 tools", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const names = mod.getStandaloneToolNames();
      expect(names).toHaveLength(15);
      expect(names).toContain("highlight_range");
      expect(names).toContain("clear_highlights");
      expect(names).toContain("open_file");
      expect(names).toContain("mark_read");
      expect(names).toContain("mark_flagged");
      expect(names).toContain("set_codelens");
      expect(names).toContain("show_blast_radius");
      expect(names).toContain("clear_blast_radius");
      expect(names).toContain("update_progress_tree");
      expect(names).toContain("clear_all");
      expect(names).toContain("get_next_briefing");
      expect(names).toContain("get_read_status");
      expect(names).toContain("get_flagged_files");
      expect(names).toContain("complete_file");
      expect(names).toContain("mark_export_read");
      // Ensure server was created (suppress unused-variable lint)
      expect(server).toBeDefined();
    });
  });

  describe("mark_read tool", () => {
    it("creates progress.json and marks file as confirmed", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "mark_read", {
        path: "src/config.ts",
      });

      expect(result.isError).not.toBe(true);
      expect(result.content[0].text).toContain("src/config.ts");
      expect(result.content[0].text).toContain("confirmed");

      // Verify progress.json was written
      const progressPath = path.join(guideDir, "progress.json");
      expect(fs.existsSync(progressPath)).toBe(true);

      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      expect(progress.files["src/config.ts"].status).toBe("confirmed");
      expect(progress.files["src/config.ts"].read_at).toBeDefined();
    });

    it("updates existing progress.json without overwriting other entries", async () => {
      // Write an initial progress.json
      const progressPath = path.join(guideDir, "progress.json");
      const initial = {
        version: "1.0.0",
        files: {
          "src/other.ts": {
            status: "flagged",
            read_at: "2026-04-04T10:00:00Z",
            note: "check later",
          },
        },
        stats: { total: 0, confirmed: 0, flagged: 1, skimmed: 0, unread: 0 },
      };
      fs.writeFileSync(progressPath, JSON.stringify(initial));

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      await callTool(server, "mark_read", { path: "src/config.ts" });

      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      expect(progress.files["src/other.ts"].status).toBe("flagged");
      expect(progress.files["src/config.ts"].status).toBe("confirmed");
    });
  });

  describe("mark_flagged tool", () => {
    it("marks file as flagged with reason", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "mark_flagged", {
        path: "src/auth.ts",
        reason: "Dual token store seems unnecessary",
      });

      expect(result.isError).not.toBe(true);
      expect(result.content[0].text).toContain("src/auth.ts");
      expect(result.content[0].text).toContain("flagged");

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      expect(progress.files["src/auth.ts"].status).toBe("flagged");
      expect(progress.files["src/auth.ts"].note).toBe(
        "Dual token store seems unnecessary",
      );
    });
  });

  describe("show_blast_radius tool", () => {
    it("returns affected files from dependency graph", async () => {
      // Write a map.json with a dependency graph
      const mapJson = {
        version: "1.0.0",
        repo_root: tmpDir,
        generated_at: "2026-04-04T10:00:00Z",
        content_hashes: {},
        total_files: 3,
        layers: {
          foundation: { description: "base", files: ["src/config.ts"] },
          core: { description: "core", files: ["src/db.ts"] },
          features: { description: "feat", files: ["src/api.ts"] },
          integration: { description: "int", files: [] },
          entry: { description: "entry", files: [] },
        },
        reading_order: [
          {
            index: 0,
            path: "src/config.ts",
            layer: "foundation",
            reason: "base",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: ["src/db.ts"],
            exports: ["AppConfig"],
          },
          {
            index: 1,
            path: "src/db.ts",
            layer: "core",
            reason: "core",
            complexity: "medium",
            line_count: 50,
            imports: ["src/config.ts"],
            imported_by: ["src/api.ts"],
            exports: ["query"],
          },
          {
            index: 2,
            path: "src/api.ts",
            layer: "features",
            reason: "feat",
            complexity: "medium",
            line_count: 80,
            imports: ["src/db.ts"],
            imported_by: [],
            exports: ["handleRequest"],
          },
        ],
        dependency_graph: {
          "src/config.ts": {
            imports: [],
            imported_by: ["src/db.ts"],
          },
          "src/db.ts": {
            imports: ["src/config.ts"],
            imported_by: ["src/api.ts"],
          },
          "src/api.ts": {
            imports: ["src/db.ts"],
            imported_by: [],
          },
        },
      };
      fs.writeFileSync(
        path.join(guideDir, "map.json"),
        JSON.stringify(mapJson),
      );

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "show_blast_radius", {
        symbol: "AppConfig",
      });

      expect(result.isError).not.toBe(true);
      const text = result.content[0].text;
      // AppConfig is exported by src/config.ts
      // Blast radius: src/db.ts -> src/api.ts (transitive)
      expect(text).toContain("src/config.ts");
      expect(text).toContain("src/db.ts");
      expect(text).toContain("src/api.ts");
    });

    it("returns error when symbol is not found", async () => {
      // Empty map
      const mapJson = {
        version: "1.0.0",
        repo_root: tmpDir,
        generated_at: "2026-04-04T10:00:00Z",
        content_hashes: {},
        total_files: 0,
        layers: {
          foundation: { description: "", files: [] },
          core: { description: "", files: [] },
          features: { description: "", files: [] },
          integration: { description: "", files: [] },
          entry: { description: "", files: [] },
        },
        reading_order: [],
        dependency_graph: {},
      };
      fs.writeFileSync(
        path.join(guideDir, "map.json"),
        JSON.stringify(mapJson),
      );

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "show_blast_radius", {
        symbol: "nonExistent",
      });

      expect(result.content[0].text).toContain("not found");
    });

    it("returns error when map.json does not exist", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "show_blast_radius", {
        symbol: "something",
      });

      expect(result.content[0].text).toContain(
        "map.json not found",
      );
    });
  });

  describe("update_progress_tree tool", () => {
    it("returns progress stats from progress.json", async () => {
      const progressPath = path.join(guideDir, "progress.json");
      const progress = {
        version: "1.0.0",
        files: {
          "src/a.ts": { status: "confirmed", read_at: "2026-04-04T10:00:00Z" },
          "src/b.ts": { status: "flagged", read_at: "2026-04-04T10:00:00Z", note: "check" },
          "src/c.ts": { status: "skimmed", read_at: "2026-04-04T10:00:00Z" },
        },
        stats: { total: 5, confirmed: 1, flagged: 1, skimmed: 1, unread: 2 },
      };
      fs.writeFileSync(progressPath, JSON.stringify(progress));

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "update_progress_tree", {});

      expect(result.isError).not.toBe(true);
      const text = result.content[0].text;
      expect(text).toContain("confirmed");
      expect(text).toContain("flagged");
      expect(text).toContain("skimmed");
    });

    it("returns message when no progress.json exists", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "update_progress_tree", {});

      expect(result.content[0].text).toContain("No progress");
    });
  });

  describe("open_file tool", () => {
    it("returns isError when no IPC client (not connected to VS Code)", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "open_file", {
        path: "src/config.ts",
        line: 42,
      });

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain("not connected");
    });
  });

  describe("cascade confirmed status to exports", () => {
    function writeMapWithExports(dir: string): void {
      const mapJson = {
        version: "1.0.0",
        repo_root: dir,
        generated_at: "2026-04-04T10:00:00Z",
        content_hashes: {},
        total_files: 2,
        layers: {
          foundation: { description: "base", files: ["src/config.ts"] },
          core: { description: "core", files: ["src/models/user.ts"] },
          features: { description: "feat", files: [] },
          integration: { description: "int", files: [] },
          entry: { description: "entry", files: [] },
        },
        reading_order: [
          {
            index: 0,
            path: "src/config.ts",
            layer: "foundation",
            reason: "base",
            complexity: "low",
            line_count: 45,
            imports: [],
            imported_by: ["src/models/user.ts"],
            exports: ["AppConfig", "getConfig", "DEFAULT_CONFIG"],
          },
          {
            index: 1,
            path: "src/models/user.ts",
            layer: "core",
            reason: "core",
            complexity: "medium",
            line_count: 120,
            imports: ["src/config.ts"],
            imported_by: [],
            exports: ["User", "createUser"],
          },
        ],
        dependency_graph: {
          "src/config.ts": { imports: [], imported_by: ["src/models/user.ts"] },
          "src/models/user.ts": { imports: ["src/config.ts"], imported_by: [] },
        },
      };
      fs.writeFileSync(
        path.join(dir, ".codebase-guide", "map.json"),
        JSON.stringify(mapJson),
      );
    }

    it("mark_read cascades all exports to confirmed when map.json has exports", async () => {
      writeMapWithExports(tmpDir);

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      await callTool(server, "mark_read", { path: "src/config.ts" });

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      const entry = progress.files["src/config.ts"];

      expect(entry.exports_read).toBeDefined();
      expect(entry.exports_read["AppConfig"]).toBeDefined();
      expect(entry.exports_read["getConfig"]).toBeDefined();
      expect(entry.exports_read["DEFAULT_CONFIG"]).toBeDefined();
      expect(entry.exports_read["AppConfig"].read_at).toBeDefined();
    });

    it("mark_read does not overwrite existing exports_read entries", async () => {
      writeMapWithExports(tmpDir);

      // Pre-populate with an existing export read
      const progressPath = path.join(guideDir, "progress.json");
      const initial = {
        version: "1.0.0",
        files: {
          "src/config.ts": {
            status: "unread",
            read_at: "",
            exports_read: {
              AppConfig: {
                read_at: "2026-04-01T00:00:00Z",
                summary: "App configuration type",
              },
            },
          },
        },
        stats: { total: 2, confirmed: 0, flagged: 0, skimmed: 0, unread: 2 },
      };
      fs.writeFileSync(progressPath, JSON.stringify(initial));

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      await callTool(server, "mark_read", { path: "src/config.ts" });

      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      const entry = progress.files["src/config.ts"];

      // Existing entry preserved
      expect(entry.exports_read["AppConfig"].read_at).toBe("2026-04-01T00:00:00Z");
      expect(entry.exports_read["AppConfig"].summary).toBe("App configuration type");
      // New entries cascaded
      expect(entry.exports_read["getConfig"]).toBeDefined();
      expect(entry.exports_read["DEFAULT_CONFIG"]).toBeDefined();
    });

    it("complete_file with confirmed status cascades exports", async () => {
      writeMapWithExports(tmpDir);

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      await callTool(server, "complete_file", {
        path: "src/config.ts",
        status: "confirmed",
        summary: "Config with env overrides",
      });

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      const entry = progress.files["src/config.ts"];

      expect(entry.exports_read).toBeDefined();
      expect(entry.exports_read["AppConfig"]).toBeDefined();
      expect(entry.exports_read["getConfig"]).toBeDefined();
      expect(entry.exports_read["DEFAULT_CONFIG"]).toBeDefined();
    });

    it("complete_file with flagged status does NOT cascade exports", async () => {
      writeMapWithExports(tmpDir);

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      await callTool(server, "complete_file", {
        path: "src/config.ts",
        status: "flagged",
        note: "needs review",
      });

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      const entry = progress.files["src/config.ts"];

      expect(entry.exports_read).toBeUndefined();
    });

    it("complete_file with skimmed status does NOT cascade exports", async () => {
      writeMapWithExports(tmpDir);

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      await callTool(server, "complete_file", {
        path: "src/config.ts",
        status: "skimmed",
      });

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      const entry = progress.files["src/config.ts"];

      expect(entry.exports_read).toBeUndefined();
    });

    it("cascade works gracefully without map.json (no exports cascaded)", async () => {
      // No map.json written
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      await callTool(server, "mark_read", { path: "src/config.ts" });

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      const entry = progress.files["src/config.ts"];

      // No crash, no exports_read since no map data
      expect(entry.status).toBe("confirmed");
      expect(entry.exports_read).toBeUndefined();
    });

    it("cascade does not add exports for files not in reading_order", async () => {
      writeMapWithExports(tmpDir);

      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      await callTool(server, "mark_read", { path: "src/unknown.ts" });

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      const entry = progress.files["src/unknown.ts"];

      expect(entry.status).toBe("confirmed");
      expect(entry.exports_read).toBeUndefined();
    });
  });

  describe("visual tools report disconnection honestly", () => {
    it("highlight_range returns isError when no IPC client", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "highlight_range", {
        file: "src/main.ts",
        startLine: 10,
        endLine: 20,
        style: "focus",
      });

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain("not connected");
    });

    it("open_file returns isError when no IPC client", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "open_file", {
        path: "src/config.ts",
        line: 42,
      });

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain("not connected");
    });

    it("clear_highlights returns isError when no IPC client", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "clear_highlights", {});

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain("not connected");
    });

    it("set_codelens returns isError when no IPC client", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "set_codelens", {
        file: "src/main.ts",
        entries: [{ line: 1, text: "Called by: foo.ts" }],
      });

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain("not connected");
    });

    it("clear_blast_radius returns isError when no IPC client", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "clear_blast_radius", {});

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain("not connected");
    });

    it("clear_all returns isError when no IPC client", async () => {
      const mod = await import("../src/mcpStandalone");
      const server = mod.createStandaloneMcpServer(tmpDir);
      const result = await callTool(server, "clear_all", {});

      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain("not connected");
    });
  });
});

/**
 * Helper to invoke a tool handler directly on the McpServer,
 * bypassing MCP protocol transport for unit testing.
 */
async function callTool(
  server: { server: unknown },
  toolName: string,
  args: Record<string, unknown>,
): Promise<{
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}> {
  // Access the registered tools through the server's internal state.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const registeredTools = (server.server as any)._registeredTools as Record<
    string,
    {
      handler: (
        args: Record<string, unknown>,
        extra: unknown,
      ) => Promise<unknown>;
    }
  >;

  const tool = registeredTools[toolName];
  if (!tool) {
    throw new Error(`Tool '${toolName}' not registered`);
  }

  const result = await tool.handler(args, {});
  return result as {
    content: Array<{ type: string; text: string }>;
    isError?: boolean;
  };
}
