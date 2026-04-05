import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import { CodeLensProvider } from "../src/codeLensProvider";
import type { CodebaseMap } from "../src/types";
import {
  __clearDecorationState,
  __resetCodeLensProviders,
  Uri,
  Range,
} from "./__mocks__/vscode";

/**
 * Helper to build a minimal CodebaseMap for testing.
 */
function makeMap(overrides?: Partial<CodebaseMap>): CodebaseMap {
  return {
    version: "1.0.0",
    repo_root: "/mock/workspace",
    generated_at: "2026-04-04T10:00:00Z",
    content_hashes: {
      "src/config.ts": "a3f2b8c1",
      "src/models/user.ts": "d4e5f6a7",
      "src/services/db.ts": "b1c2d3e4",
    },
    total_files: 3,
    layers: {
      foundation: {
        description: "No or minimal internal dependencies",
        files: ["src/config.ts"],
      },
      core: {
        description: "Depends only on foundation",
        files: ["src/models/user.ts", "src/services/db.ts"],
      },
      features: { description: "Business logic", files: [] },
      integration: { description: "Composes features", files: [] },
      entry: { description: "App entry points", files: [] },
    },
    reading_order: [
      {
        index: 0,
        path: "src/config.ts",
        layer: "foundation",
        reason: "No dependencies.",
        complexity: "low",
        line_count: 45,
        imports: [],
        imported_by: ["src/models/user.ts", "src/services/db.ts"],
        exports: ["AppConfig", "getConfig", "DEFAULT_CONFIG"],
      },
      {
        index: 1,
        path: "src/models/user.ts",
        layer: "core",
        reason: "Depends on config.",
        complexity: "medium",
        line_count: 120,
        imports: ["src/config.ts"],
        imported_by: [],
        exports: ["User", "createUser"],
      },
      {
        index: 2,
        path: "src/services/db.ts",
        layer: "core",
        reason: "Depends on config.",
        complexity: "medium",
        line_count: 80,
        imports: ["src/config.ts"],
        imported_by: ["src/models/user.ts"],
        exports: ["getDb", "closeDb"],
      },
    ],
    dependency_graph: {
      "src/config.ts": {
        imports: [],
        imported_by: ["src/models/user.ts", "src/services/db.ts"],
      },
      "src/models/user.ts": {
        imports: ["src/config.ts"],
        imported_by: [],
      },
      "src/services/db.ts": {
        imports: ["src/config.ts"],
        imported_by: ["src/models/user.ts"],
      },
    },
    ...overrides,
  };
}

/**
 * Helper to create a mock TextDocument.
 */
function makeMockDocument(
  filePath: string,
  content: string,
): {
  uri: { fsPath: string; path: string };
  getText: () => string;
  lineAt: (line: number) => { text: string };
  lineCount: number;
  fileName: string;
} {
  const lines = content.split("\n");
  return {
    uri: Uri.file(filePath),
    getText: () => content,
    lineAt: (line: number) => ({ text: lines[line] ?? "" }),
    lineCount: lines.length,
    fileName: filePath,
  };
}

describe("CodeLensProvider", () => {
  let provider: CodeLensProvider;

  beforeEach(() => {
    __clearDecorationState();
    __resetCodeLensProviders();
    provider = new CodeLensProvider();
  });

  afterEach(() => {
    provider.dispose();
    __clearDecorationState();
    __resetCodeLensProviders();
  });

  describe("constructor and lifecycle", () => {
    it("creates a CodeLensProvider instance", () => {
      expect(provider).toBeDefined();
    });

    it("provides an onDidChangeCodeLenses event", () => {
      expect(provider.onDidChangeCodeLenses).toBeDefined();
    });

    it("dispose does not throw", () => {
      provider.dispose();
      expect(true).toBe(true);
    });

    it("dispose can be called multiple times", () => {
      provider.dispose();
      provider.dispose();
      expect(true).toBe(true);
    });
  });

  describe("updateMapData", () => {
    it("accepts a CodebaseMap", () => {
      const map = makeMap();
      provider.updateMapData(map);
      // Should not throw
      expect(true).toBe(true);
    });

    it("accepts undefined to clear data", () => {
      provider.updateMapData(makeMap());
      provider.updateMapData(undefined);
      // Should not throw
      expect(true).toBe(true);
    });

    it("fires onDidChangeCodeLenses when data is updated", () => {
      const listener = vi.fn();
      provider.onDidChangeCodeLenses(listener);
      provider.updateMapData(makeMap());
      expect(listener).toHaveBeenCalled();
    });

    it("fires onDidChangeCodeLenses when data is cleared", () => {
      provider.updateMapData(makeMap());
      const listener = vi.fn();
      provider.onDidChangeCodeLenses(listener);
      provider.updateMapData(undefined);
      expect(listener).toHaveBeenCalled();
    });
  });

  describe("provideCodeLenses", () => {
    it("returns empty array when no map data is loaded", () => {
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        "export function getConfig() {}",
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result).toEqual([]);
    });

    it("returns empty array for files not in the map", () => {
      provider.updateMapData(makeMap());
      const doc = makeMockDocument(
        "/mock/workspace/src/unknown.ts",
        "export function foo() {}",
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result).toEqual([]);
    });

    it("returns CodeLens items for exported function declarations", () => {
      provider.updateMapData(makeMap());
      const content = [
        "// Comment",
        "export function getConfig() {",
        "  return {};",
        "}",
        "export const AppConfig = {};",
      ].join("\n");
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });

    it("does not return CodeLens for non-exported functions", () => {
      provider.updateMapData(makeMap());
      const content = [
        "function helperInternal() {}",
        "export function getConfig() { return {}; }",
      ].join("\n");
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      // Only getConfig is exported in the map, helperInternal should not get a CodeLens
      const titles = result.map((cl: { command?: { title: string } }) => cl.command?.title ?? "");
      const hasHelper = titles.some((t: string) => t.includes("helperInternal"));
      expect(hasHelper).toBe(false);
      // But getConfig should have one
      expect(result.length).toBeGreaterThanOrEqual(1);
    });

    it("places CodeLens on the correct line for each function", () => {
      provider.updateMapData(makeMap());
      const content = [
        "// line 0",
        "export function getConfig() {",    // line 1
        "  return {};",
        "}",
        "",
        "export const DEFAULT_CONFIG = () => ({});", // line 5 — arrow fn
      ].join("\n");
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      const lines = result.map((cl: { range: Range }) => cl.range.start.line);
      expect(lines).toContain(1); // getConfig
      expect(lines).toContain(5); // DEFAULT_CONFIG
    });
  });

  describe("CodeLens text format", () => {
    it("shows callers in the format 'Called by: file1.ts, file2.ts'", () => {
      provider.updateMapData(makeMap());
      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
      const title = result[0].command?.title ?? "";
      // config.ts is imported_by user.ts and db.ts
      expect(title).toContain("Called by:");
      expect(title).toContain("user.ts");
      expect(title).toContain("db.ts");
    });

    it("shows 'Called by: none (potential dead code)' for 0 callers", () => {
      provider.updateMapData(makeMap());
      const content = "export function createUser() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/models/user.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
      const title = result[0].command?.title ?? "";
      expect(title).toContain("Called by: none (potential dead code)");
    });

    it("shows callees in the format '| Calls: func1, func2'", () => {
      // user.ts imports config.ts, so its CodeLens should show "Calls: config.ts"
      provider.updateMapData(makeMap());
      const content = "export function createUser() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/models/user.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
      const title = result[0].command?.title ?? "";
      expect(title).toContain("Calls:");
      expect(title).toContain("config.ts");
    });

    it("omits the Calls section when there are no callees", () => {
      provider.updateMapData(makeMap());
      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
      const title = result[0].command?.title ?? "";
      // config.ts has no imports, so no "Calls:" section
      expect(title).not.toContain("Calls:");
    });

    it("truncates callers with '... +N more' when more than 5", () => {
      const manyCallers = Array.from(
        { length: 8 },
        (_, i) => `src/caller${String(i)}.ts`,
      );
      const map = makeMap({
        reading_order: [
          {
            index: 0,
            path: "src/target.ts",
            layer: "foundation",
            reason: "Test",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: manyCallers,
            exports: ["doStuff"],
          },
        ],
        dependency_graph: {
          "src/target.ts": {
            imports: [],
            imported_by: manyCallers,
          },
        },
      });
      provider.updateMapData(map);
      const content = "export function doStuff() {}";
      const doc = makeMockDocument(
        "/mock/workspace/src/target.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
      const title = result[0].command?.title ?? "";
      expect(title).toContain("... +3 more");
    });

    it("truncates callees with '... +N more' when more than 5", () => {
      const manyImports = Array.from(
        { length: 7 },
        (_, i) => `src/dep${String(i)}.ts`,
      );
      const map = makeMap({
        reading_order: [
          {
            index: 0,
            path: "src/target.ts",
            layer: "features",
            reason: "Test",
            complexity: "high",
            line_count: 200,
            imports: manyImports,
            imported_by: [],
            exports: ["process"],
          },
        ],
        dependency_graph: {
          "src/target.ts": {
            imports: manyImports,
            imported_by: [],
          },
        },
      });
      provider.updateMapData(map);
      const content = "export function process() {}";
      const doc = makeMockDocument(
        "/mock/workspace/src/target.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
      const title = result[0].command?.title ?? "";
      expect(title).toContain("Calls:");
      expect(title).toContain("... +2 more");
    });
  });

  describe("CodeLens command (click to navigate)", () => {
    it("each CodeLens has a command that navigates to a caller", () => {
      provider.updateMapData(makeMap());
      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
      const cmd = result[0].command;
      expect(cmd).toBeDefined();
      expect(cmd?.command).toBe("noLongerVibe.navigateToCaller");
      // Arguments should include the file path to navigate to
      expect(cmd?.arguments).toBeDefined();
      expect(cmd?.arguments?.length).toBeGreaterThan(0);
    });

    it("CodeLens for dead code file has no navigation target", () => {
      provider.updateMapData(makeMap());
      const content = "export function createUser() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/models/user.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
      const cmd = result[0].command;
      // For dead code, command should still exist but with no navigation target
      expect(cmd).toBeDefined();
      // The arguments should indicate no callers
      expect(cmd?.arguments?.[0]).toBeUndefined();
    });
  });

  describe("path resolution", () => {
    it("resolves absolute file paths relative to repo_root", () => {
      provider.updateMapData(makeMap());
      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });

    it("handles repo_root with trailing slash", () => {
      const map = makeMap({ repo_root: "/mock/workspace/" });
      provider.updateMapData(map);
      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });

    it("returns empty for files outside repo_root", () => {
      provider.updateMapData(makeMap());
      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/other/location/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result).toEqual([]);
    });
  });

  describe("function detection patterns", () => {
    it("detects standard function declarations", () => {
      provider.updateMapData(makeMap());
      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });

    it("detects async function declarations", () => {
      provider.updateMapData(makeMap());
      const content = "export async function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });

    it("detects arrow function assignments", () => {
      provider.updateMapData(makeMap());
      const content = "export const getConfig = () => ({});";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });

    it("detects class declarations", () => {
      provider.updateMapData(makeMap());
      const content = "export class AppConfig { }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });

    it("detects Python function defs", () => {
      const map = makeMap({
        reading_order: [
          {
            index: 0,
            path: "src/config.py",
            layer: "foundation",
            reason: "No dependencies.",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: ["src/models/user.py"],
            exports: ["get_config"],
          },
        ],
        dependency_graph: {
          "src/config.py": {
            imports: [],
            imported_by: ["src/models/user.py"],
          },
        },
      });
      provider.updateMapData(map);
      const content = "def get_config():\n    return {}";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.py",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });

    it("detects Python class declarations", () => {
      const map = makeMap({
        reading_order: [
          {
            index: 0,
            path: "src/config.py",
            layer: "foundation",
            reason: "No deps.",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: ["AppConfig"],
          },
        ],
        dependency_graph: {
          "src/config.py": { imports: [], imported_by: [] },
        },
      });
      provider.updateMapData(map);
      const content = "class AppConfig:\n    pass";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.py",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      expect(result.length).toBeGreaterThan(0);
    });
  });

  describe("MCP set_codelens overrides", () => {
    it("setMcpOverrides replaces automatic CodeLens with MCP-provided entries", () => {
      provider.updateMapData(makeMap());
      const filePath = "src/config.ts";
      provider.setMcpOverrides(filePath, [
        { line: 5, text: "Custom annotation" },
        { line: 10, text: "Another annotation", command: "some.command" },
      ]);

      const content = [
        "line0", "line1", "line2", "line3", "line4",
        "export function getConfig() {}", // line 5
        "line6", "line7", "line8", "line9",
        "export const AppConfig = {};",   // line 10
      ].join("\n");
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      // Should return the MCP overrides, not the auto-generated ones
      expect(result.length).toBe(2);
      expect(result[0].command?.title).toBe("Custom annotation");
      expect(result[1].command?.title).toBe("Another annotation");
    });

    it("clearMcpOverrides reverts to automatic CodeLens", () => {
      provider.updateMapData(makeMap());
      const filePath = "src/config.ts";
      provider.setMcpOverrides(filePath, [
        { line: 1, text: "Override" },
      ]);
      provider.clearMcpOverrides(filePath);

      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      // Should show auto-generated "Called by:" style, not the override
      const title = result[0]?.command?.title ?? "";
      expect(title).toContain("Called by:");
    });
  });

  describe("file basename extraction for display", () => {
    it("shows only the basename of caller files", () => {
      provider.updateMapData(makeMap());
      const content = "export function getConfig() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/config.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      const title = result[0]?.command?.title ?? "";
      // Should show "user.ts" not "src/models/user.ts"
      expect(title).toContain("user.ts");
      expect(title).not.toContain("src/models/user.ts");
    });

    it("shows only the basename of callee files", () => {
      provider.updateMapData(makeMap());
      // user.ts imports config.ts
      const content = "export function createUser() { return {}; }";
      const doc = makeMockDocument(
        "/mock/workspace/src/models/user.ts",
        content,
      );
      const result = provider.provideCodeLenses(doc as never);
      const title = result[0]?.command?.title ?? "";
      expect(title).toContain("config.ts");
      expect(title).not.toContain("src/config.ts");
    });
  });
});
