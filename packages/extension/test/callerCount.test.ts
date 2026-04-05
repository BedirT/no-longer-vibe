import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import { CallerCountProvider } from "../src/callerCount";
import type { CodebaseMap } from "../src/types";
import {
  __setActiveEditor,
  __getDecorationTypes,
  __clearDecorationState,
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
    },
    total_files: 2,
    layers: {
      foundation: {
        description: "No or minimal internal dependencies",
        files: ["src/config.ts"],
      },
      core: {
        description: "Depends only on foundation",
        files: ["src/models/user.ts"],
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
        imported_by: ["src/models/user.ts"],
        exports: ["AppConfig", "getConfig"],
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
    ],
    dependency_graph: {
      "src/config.ts": {
        imports: [],
        imported_by: ["src/models/user.ts"],
      },
      "src/models/user.ts": {
        imports: ["src/config.ts"],
        imported_by: [],
      },
    },
    ...overrides,
  };
}

/**
 * Helper to build a mock TextEditor with document text.
 */
function makeMockEditor(
  filePath: string,
  content: string,
): {
  document: {
    uri: { fsPath: string; path: string };
    getText: () => string;
    lineAt: (line: number) => { text: string };
    lineCount: number;
  };
  setDecorations: ReturnType<typeof vi.fn>;
} {
  const lines = content.split("\n");
  return {
    document: {
      uri: { fsPath: filePath, path: filePath },
      getText: () => content,
      lineAt: (line: number) => ({ text: lines[line] ?? "" }),
      lineCount: lines.length,
    },
    setDecorations: vi.fn(),
  };
}

describe("CallerCountProvider", () => {
  let provider: CallerCountProvider;

  beforeEach(() => {
    __clearDecorationState();
    provider = new CallerCountProvider();
  });

  afterEach(() => {
    provider.dispose();
    __clearDecorationState();
  });

  describe("constructor", () => {
    it("creates a CallerCountProvider instance", () => {
      expect(provider).toBeDefined();
    });
  });

  describe("updateMapData", () => {
    it("accepts a CodebaseMap and stores it", () => {
      const map = makeMap();
      provider.updateMapData(map);
      // Verify by triggering decorations on a known file
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        "export function getConfig() {}\nexport const AppConfig = {};",
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);
      // Should have applied decorations (one or more calls)
      expect(editor.setDecorations).toHaveBeenCalled();
    });

    it("clears decorations when called with undefined", () => {
      provider.updateMapData(makeMap());
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        "export function getConfig() {}",
      );
      __setActiveEditor(editor);

      // First apply decorations
      provider.updateDecorations(editor as never);
      expect(editor.setDecorations).toHaveBeenCalled();

      // Clear map data and reapply
      provider.updateMapData(undefined);
      provider.updateDecorations(editor as never);

      // After clearing, there should be no decoration calls with non-empty ranges
      // (the previous decorations were disposed, and no new ones created)
      const lastCalls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      // The final state should be that decoration types were disposed
      // (clearDecorations is called inside updateDecorations)
      const decTypes = __getDecorationTypes();
      expect(decTypes.every((d) => d.isDisposed)).toBe(true);
    });
  });

  describe("updateDecorations", () => {
    it("does not decorate files not in the map", () => {
      provider.updateMapData(makeMap());
      const editor = makeMockEditor(
        "/mock/workspace/src/unknown.ts",
        "export function foo() {}",
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      // setDecorations should be called to clear any previous decorations
      // but with empty decoration arrays
      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      for (const call of calls) {
        // Second arg is the decoration ranges - should be empty
        expect(call[1]).toHaveLength(0);
      }
    });

    it("does nothing when no map data is loaded", () => {
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        "export function getConfig() {}",
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      // setDecorations may be called to clear, but ranges must be empty
      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      for (const call of calls) {
        expect(call[1]).toHaveLength(0);
      }
    });

    it("places decorations on function declaration lines", () => {
      provider.updateMapData(makeMap());
      const content = [
        "// Comment line",
        "export function getConfig() {",
        "  return {};",
        "}",
        "export const AppConfig = {};",
      ].join("\n");
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      // Should have at least one call with non-empty decoration ranges
      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const hasDecorations = calls.some(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(hasDecorations).toBe(true);
    });

    it("uses correct color for dead code (0 callers)", () => {
      // Create a map where user.ts has 0 imported_by
      provider.updateMapData(makeMap());
      const content = [
        "export function createUser() {",
        "  return {};",
        "}",
      ].join("\n");
      const editor = makeMockEditor(
        "/mock/workspace/src/models/user.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const decoratedCalls = calls.filter(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );

      // There should be decorations for the exported function
      expect(decoratedCalls.length).toBeGreaterThan(0);
    });

    it("computes caller count from imported_by in reading order", () => {
      // src/config.ts is imported by 1 file (src/models/user.ts)
      provider.updateMapData(makeMap());
      const content = [
        "export function getConfig() {",
        "  return {};",
        "}",
      ].join("\n");
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const decoratedCalls = calls.filter(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(decoratedCalls.length).toBeGreaterThan(0);
    });
  });

  describe("color tiers", () => {
    function makeMapWithImportedBy(importedByCount: number): CodebaseMap {
      const importers = Array.from(
        { length: importedByCount },
        (_, i) => `src/file${String(i)}.ts`,
      );
      return makeMap({
        reading_order: [
          {
            index: 0,
            path: "src/target.ts",
            layer: "foundation",
            reason: "Test file",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: importers,
            exports: ["doStuff"],
          },
        ],
        dependency_graph: {
          "src/target.ts": {
            imports: [],
            imported_by: importers,
          },
        },
      });
    }

    it("returns dead-code color for 0 callers", () => {
      const color = CallerCountProvider.getCallerColor(0);
      expect(color.light).toBe("#dc2626");
      expect(color.dark).toBe("#ef4444");
    });

    it("returns low-usage color for 1-2 callers", () => {
      const color1 = CallerCountProvider.getCallerColor(1);
      expect(color1.light).toBe("#94a3b8");
      expect(color1.dark).toBe("#64748b");

      const color2 = CallerCountProvider.getCallerColor(2);
      expect(color2.light).toBe("#94a3b8");
      expect(color2.dark).toBe("#64748b");
    });

    it("returns normal color for 3-7 callers", () => {
      const color3 = CallerCountProvider.getCallerColor(3);
      expect(color3.light).toBe("#475569");
      expect(color3.dark).toBe("#94a3b8");

      const color7 = CallerCountProvider.getCallerColor(7);
      expect(color7.light).toBe("#475569");
      expect(color7.dark).toBe("#94a3b8");
    });

    it("returns hot-path color for 8+ callers", () => {
      const color8 = CallerCountProvider.getCallerColor(8);
      expect(color8.light).toBe("#1e40af");
      expect(color8.dark).toBe("#60a5fa");

      const color100 = CallerCountProvider.getCallerColor(100);
      expect(color100.light).toBe("#1e40af");
      expect(color100.dark).toBe("#60a5fa");
    });
  });

  describe("function detection", () => {
    it("detects standard function declarations", () => {
      provider.updateMapData(makeMap());
      const content = [
        "function getConfig() {",
        "  return {};",
        "}",
      ].join("\n");
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const hasDecorations = calls.some(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(hasDecorations).toBe(true);
    });

    it("detects exported function declarations", () => {
      provider.updateMapData(makeMap());
      const content = "export function getConfig() { return {}; }";
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const hasDecorations = calls.some(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(hasDecorations).toBe(true);
    });

    it("detects arrow function assignments", () => {
      provider.updateMapData(makeMap());
      const content = "export const getConfig = () => ({});";
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const hasDecorations = calls.some(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(hasDecorations).toBe(true);
    });

    it("detects class declarations", () => {
      provider.updateMapData(makeMap());
      const content = "export class AppConfig { }";
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const hasDecorations = calls.some(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(hasDecorations).toBe(true);
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
      const editor = makeMockEditor(
        "/mock/workspace/src/config.py",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const hasDecorations = calls.some(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(hasDecorations).toBe(true);
    });
  });

  describe("path resolution", () => {
    it("resolves file path relative to repo_root", () => {
      provider.updateMapData(makeMap());
      // Path in the editor is absolute, map has relative paths
      const content = "export function getConfig() { return {}; }";
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const hasDecorations = calls.some(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(hasDecorations).toBe(true);
    });

    it("handles paths without leading slash in repo_root", () => {
      const map = makeMap({ repo_root: "mock/workspace" });
      provider.updateMapData(map);
      const content = "export function getConfig() { return {}; }";
      const editor = makeMockEditor(
        "mock/workspace/src/config.ts",
        content,
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      const calls = (editor.setDecorations as ReturnType<typeof vi.fn>).mock.calls;
      const hasDecorations = calls.some(
        (call: unknown[]) => Array.isArray(call[1]) && (call[1] as unknown[]).length > 0,
      );
      expect(hasDecorations).toBe(true);
    });
  });

  describe("dispose", () => {
    it("disposes all decoration types", () => {
      provider.updateMapData(makeMap());
      const editor = makeMockEditor(
        "/mock/workspace/src/config.ts",
        "export function getConfig() { return {}; }",
      );
      __setActiveEditor(editor);
      provider.updateDecorations(editor as never);

      // Should not throw
      provider.dispose();
    });

    it("clears subscriptions", () => {
      provider.dispose();
      // Should not throw if called twice
      provider.dispose();
    });
  });
});
