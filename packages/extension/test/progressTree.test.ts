import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import { ProgressTreeProvider } from "../src/progressTree";
import type { CodebaseMap } from "../src/types";
import { EventEmitter } from "./__mocks__/vscode";
import type { McpToolEvent } from "../src/mcpServer";

/**
 * Builds a minimal CodebaseMap for testing with sensible defaults.
 */
function makeMap(overrides?: Partial<CodebaseMap>): CodebaseMap {
  return {
    version: "1.0.0",
    repo_root: "/mock/workspace",
    generated_at: "2026-04-04T10:00:00Z",
    content_hashes: {
      "src/config.ts": "a3f2b8c1",
      "src/models/user.ts": "d4e5f6a7",
      "src/components/Dashboard.tsx": "b1c2d3e4",
    },
    total_files: 3,
    layers: {
      foundation: {
        description: "No or minimal internal dependencies",
        files: ["src/config.ts"],
      },
      core: {
        description: "Depends only on foundation",
        files: ["src/models/user.ts"],
      },
      features: {
        description: "Business logic, depends on core",
        files: ["src/components/Dashboard.tsx"],
      },
      integration: {
        description: "Composes features, middleware, API routes",
        files: [],
      },
      entry: {
        description: "App entry points, page-level composition",
        files: [],
      },
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
        imported_by: ["src/components/Dashboard.tsx"],
        exports: ["User", "createUser"],
      },
      {
        index: 2,
        path: "src/components/Dashboard.tsx",
        layer: "features",
        reason: "Depends on user model.",
        complexity: "high",
        line_count: 300,
        imports: ["src/models/user.ts"],
        imported_by: [],
        exports: ["Dashboard"],
      },
    ],
    dependency_graph: {
      "src/config.ts": {
        imports: [],
        imported_by: ["src/models/user.ts"],
      },
      "src/models/user.ts": {
        imports: ["src/config.ts"],
        imported_by: ["src/components/Dashboard.tsx"],
      },
      "src/components/Dashboard.tsx": {
        imports: ["src/models/user.ts"],
        imported_by: [],
      },
    },
    ...overrides,
  };
}

/**
 * Helper: given a layer item, drill through the directory level to get file items.
 * For the default makeMap, each layer has one directory containing one file.
 */
function getFilesFromLayer(
  provider: ProgressTreeProvider,
  layerItem: { contextValue?: string },
): ReturnType<ProgressTreeProvider["getChildren"]> {
  const dirs = provider.getChildren(layerItem as Parameters<ProgressTreeProvider["getChildren"]>[0]);
  // dirs may contain directory items (contextValue starts with "dir:") or direct file items
  const files: ReturnType<ProgressTreeProvider["getChildren"]> = [];
  for (const d of dirs) {
    if (d.contextValue?.startsWith("dir:")) {
      files.push(...provider.getChildren(d));
    } else {
      files.push(d);
    }
  }
  return files;
}

describe("ProgressTreeProvider", () => {
  let provider: ProgressTreeProvider;

  beforeEach(() => {
    provider = new ProgressTreeProvider("/mock/workspace");
  });

  describe("getTreeItem", () => {
    it("returns the element itself (TreeItem passthrough)", () => {
      provider.updateMapData(makeMap());
      const children = provider.getChildren();
      const item = children[0];
      expect(provider.getTreeItem(item)).toBe(item);
    });
  });

  describe("getChildren — no map data", () => {
    it("returns empty array when no map data is loaded", () => {
      const children = provider.getChildren();
      expect(children).toEqual([]);
    });
  });

  describe("getChildren — root level (layers)", () => {
    it("returns layer items for all non-empty layers", () => {
      provider.updateMapData(makeMap());
      const children = provider.getChildren();

      // Only foundation, core, features have files — integration/entry are empty
      const labels = children.map((c) => c.label);
      expect(labels).toContain("foundation (0/1 read)");
      expect(labels).toContain("core (0/1 read)");
      expect(labels).toContain("features (0/1 read)");
    });

    it("skips layers with no files", () => {
      provider.updateMapData(makeMap());
      const children = provider.getChildren();
      const labels = children.map((c) => c.label);
      expect(labels).not.toContain(expect.stringContaining("integration"));
      expect(labels).not.toContain(expect.stringContaining("entry"));
    });

    it("preserves layer order: foundation, core, features, integration, entry", () => {
      const map = makeMap({
        layers: {
          foundation: { description: "", files: ["a.ts"] },
          core: { description: "", files: ["b.ts"] },
          features: { description: "", files: ["c.ts"] },
          integration: { description: "", files: ["d.ts"] },
          entry: { description: "", files: ["e.ts"] },
        },
        reading_order: [
          {
            index: 0,
            path: "a.ts",
            layer: "foundation",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: [],
          },
          {
            index: 1,
            path: "b.ts",
            layer: "core",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: [],
          },
          {
            index: 2,
            path: "c.ts",
            layer: "features",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: [],
          },
          {
            index: 3,
            path: "d.ts",
            layer: "integration",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: [],
          },
          {
            index: 4,
            path: "e.ts",
            layer: "entry",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: [],
          },
        ],
      });
      provider.updateMapData(map);
      const children = provider.getChildren();
      const layerNames = children.map((c) => c.contextValue);
      expect(layerNames).toEqual([
        "layer:foundation",
        "layer:core",
        "layer:features",
        "layer:integration",
        "layer:entry",
      ]);
    });

    it("layer items are collapsible (expanded state)", () => {
      provider.updateMapData(makeMap());
      const children = provider.getChildren();
      for (const child of children) {
        // 1 = Collapsed, 2 = Expanded; layers should be collapsible
        expect(child.collapsibleState).toBeDefined();
        expect(child.collapsibleState).toBeGreaterThan(0);
      }
    });
  });

  describe("getChildren — directory level", () => {
    it("returns directory items for a given layer", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const dirs = provider.getChildren(foundationLayer);

      // foundation has src/config.ts -> directory "src"
      expect(dirs).toHaveLength(1);
      expect(dirs[0].contextValue).toBe("dir:foundation:src");
    });

    it("collapses single-child directory chains", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const coreLayer = layers.find((l) => l.contextValue === "layer:core")!;
      const dirs = provider.getChildren(coreLayer);

      // core has src/models/user.ts -> collapsed to "src/models"
      expect(dirs).toHaveLength(1);
      expect(dirs[0].contextValue).toBe("dir:core:src/models");
      expect(dirs[0].label).toBe("src/models");
    });

    it("does NOT collapse directories that have direct files alongside subdirectories", () => {
      const map = makeMap({
        layers: {
          foundation: {
            description: "",
            files: ["src/index.ts", "src/utils/helper.ts"],
          },
          core: { description: "", files: [] },
          features: { description: "", files: [] },
          integration: { description: "", files: [] },
          entry: { description: "", files: [] },
        },
        reading_order: [
          {
            index: 0,
            path: "src/index.ts",
            layer: "foundation",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: [],
          },
          {
            index: 1,
            path: "src/utils/helper.ts",
            layer: "foundation",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: [],
          },
        ],
      });
      provider.updateMapData(map);
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const dirs = provider.getChildren(foundationLayer);

      // "src" should NOT be collapsed because it has both a direct file (index.ts)
      // and a subdirectory (utils)
      expect(dirs).toHaveLength(1);
      expect(dirs[0].contextValue).toBe("dir:foundation:src");
      expect(dirs[0].label).toBe("src");

      // Inside "src", we should see the subdirectory "utils" and the file "index.ts"
      const srcChildren = provider.getChildren(dirs[0]);
      const dirChildren = srcChildren.filter((c) =>
        c.contextValue?.startsWith("dir:"),
      );
      const fileChildren = srcChildren.filter((c) =>
        c.contextValue?.startsWith("file:"),
      );
      expect(dirChildren).toHaveLength(1);
      expect(dirChildren[0].contextValue).toBe("dir:foundation:src/utils");
      expect(fileChildren).toHaveLength(1);
      expect(fileChildren[0].contextValue).toBe("file:src/index.ts");
    });

    it("directory items have folder icons", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const dirs = provider.getChildren(foundationLayer);

      expect(dirs[0].iconPath).toBeDefined();
      expect((dirs[0].iconPath as { id: string }).id).toBe("folder");
    });

    it("multiple files in the same directory appear as siblings", () => {
      const map = makeMap({
        layers: {
          foundation: {
            description: "",
            files: ["src/config.ts", "src/constants.ts"],
          },
          core: { description: "", files: [] },
          features: { description: "", files: [] },
          integration: { description: "", files: [] },
          entry: { description: "", files: [] },
        },
        reading_order: [
          {
            index: 0,
            path: "src/config.ts",
            layer: "foundation",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: ["AppConfig"],
          },
          {
            index: 1,
            path: "src/constants.ts",
            layer: "foundation",
            reason: "",
            complexity: "low",
            line_count: 10,
            imports: [],
            imported_by: [],
            exports: [],
          },
        ],
      });
      provider.updateMapData(map);
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const dirs = provider.getChildren(foundationLayer);

      // Single "src" directory
      expect(dirs).toHaveLength(1);
      expect(dirs[0].contextValue).toBe("dir:foundation:src");

      // Inside "src", both files appear as siblings
      const files = provider.getChildren(dirs[0]);
      expect(files).toHaveLength(2);
      const labels = files.map((f) => f.label);
      expect(labels).toContain("config.ts");
      expect(labels).toContain("constants.ts");
    });
  });

  describe("getChildren — file level", () => {
    it("returns file items for a given layer (through directories)", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      expect(files).toHaveLength(1);
      expect(files[0].label).toBe("config.ts");
    });

    it("file items show basename, not full path", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const coreLayer = layers.find((l) => l.contextValue === "layer:core")!;
      const files = getFilesFromLayer(provider, coreLayer);

      expect(files[0].label).toBe("user.ts");
    });

    it("file items have correct contextValue with full path", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      expect(files[0].contextValue).toBe("file:src/config.ts");
    });

    it("file items are collapsible when they have exports", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      // src/config.ts has exports ["AppConfig", "getConfig"]
      expect(files[0].collapsibleState).toBeGreaterThan(0);
    });

    it("file items are not collapsible when they have no exports", () => {
      const map = makeMap();
      map.reading_order[0].exports = [];
      provider.updateMapData(map);

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      expect(files[0].collapsibleState).toBe(0);
    });

    it("clicking a file item triggers vscode.open command", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      expect(files[0].command).toBeDefined();
      expect(files[0].command!.command).toBe("vscode.open");
      expect(files[0].command!.title).toBe("Open File");
    });

    it("file directory context is provided by parent directory node", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const coreLayer = layers.find((l) => l.contextValue === "layer:core")!;
      const dirs = provider.getChildren(coreLayer);

      // The directory node provides the path context (src/models)
      expect(dirs[0].contextValue).toBe("dir:core:src/models");
      expect(dirs[0].label).toBe("src/models");

      // The file itself just shows the basename
      const files = provider.getChildren(dirs[0]);
      expect(files[0].label).toBe("user.ts");
    });
  });

  describe("getChildren — export/symbol level", () => {
    it("returns export items for a given file", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);
      const configFile = files[0];
      const exports = provider.getChildren(configFile);

      expect(exports).toHaveLength(2);
      const exportLabels = exports.map((e) => e.label);
      expect(exportLabels).toContain("AppConfig");
      expect(exportLabels).toContain("getConfig");
    });

    it("export items are not collapsible (leaf nodes)", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);
      const exports = provider.getChildren(files[0]);

      for (const exp of exports) {
        expect(exp.collapsibleState).toBe(0);
      }
    });

    it("export items have contextValue prefixed with 'export:'", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);
      const exports = provider.getChildren(files[0]);

      expect(exports[0].contextValue).toBe("export:AppConfig");
      expect(exports[1].contextValue).toBe("export:getConfig");
    });

    it("returns empty array for files with no exports", () => {
      const map = makeMap();
      map.reading_order[0].exports = [];
      provider.updateMapData(map);

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);
      const exports = provider.getChildren(files[0]);

      expect(exports).toEqual([]);
    });
  });

  describe("status icons", () => {
    it("unread files show circle-outline icon", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      expect(files[0].iconPath).toBeDefined();
      // ThemeIcon is mocked; check the id
      expect((files[0].iconPath as { id: string }).id).toBe("circle-outline");
    });

    it("confirmed files show check icon with green color", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "confirmed");
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      const icon = files[0].iconPath as { id: string; color?: { id: string } };
      expect(icon.id).toBe("check");
      expect(icon.color?.id).toBe("noLongerVibe.confirmed");
    });

    it("flagged files show warning icon with orange color", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "flagged");
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      const icon = files[0].iconPath as { id: string; color?: { id: string } };
      expect(icon.id).toBe("warning");
      expect(icon.color?.id).toBe("noLongerVibe.flagged");
    });

    it("skimmed files show eye-closed icon with skimmed color", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "skimmed");
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      const icon = files[0].iconPath as { id: string; color?: { id: string } };
      expect(icon.id).toBe("eye-closed");
      expect(icon.color?.id).toBe("noLongerVibe.skimmed");
    });

    it("current file shows eye icon with blue color", () => {
      provider.updateMapData(makeMap());
      provider.setCurrentFile("src/config.ts");
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      const icon = files[0].iconPath as { id: string; color?: { id: string } };
      expect(icon.id).toBe("eye");
      expect(icon.color?.id).toBe("noLongerVibe.current");
    });

    it("current file status takes priority over confirmed", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "confirmed");
      provider.setCurrentFile("src/config.ts");
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);

      const icon = files[0].iconPath as { id: string; color?: { id: string } };
      expect(icon.id).toBe("eye");
      expect(icon.color?.id).toBe("noLongerVibe.current");
    });
  });

  describe("layer progress counting", () => {
    it("shows 0/N when no files are read", () => {
      provider.updateMapData(makeMap());
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      expect(foundationLayer.label).toBe("foundation (0/1 read)");
    });

    it("counts confirmed files as read", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "confirmed");
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      expect(foundationLayer.label).toBe("foundation (1/1 read)");
    });

    it("counts skimmed files as read in progress", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "skimmed");
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      expect(foundationLayer.label).toBe("foundation (1/1 read)");
    });

    it("counts flagged files as read in progress", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "flagged");
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      expect(foundationLayer.label).toBe("foundation (1/1 read)");
    });

    it("does not count unread files in progress", () => {
      provider.updateMapData(makeMap());
      // No status set — file is unread
      const layers = provider.getChildren();
      const coreLayer = layers.find((l) => l.contextValue === "layer:core")!;
      expect(coreLayer.label).toBe("core (0/1 read)");
    });
  });

  describe("refresh (onDidChangeTreeData event)", () => {
    it("fires onDidChangeTreeData when updateMapData is called", () => {
      const listener = vi.fn();
      provider.onDidChangeTreeData(listener);

      provider.updateMapData(makeMap());

      expect(listener).toHaveBeenCalledTimes(1);
    });

    it("fires onDidChangeTreeData when setFileStatus is called", () => {
      provider.updateMapData(makeMap());

      const listener = vi.fn();
      provider.onDidChangeTreeData(listener);

      provider.setFileStatus("src/config.ts", "confirmed");

      expect(listener).toHaveBeenCalledTimes(1);
    });

    it("fires onDidChangeTreeData when setCurrentFile is called", () => {
      provider.updateMapData(makeMap());

      const listener = vi.fn();
      provider.onDidChangeTreeData(listener);

      provider.setCurrentFile("src/config.ts");

      expect(listener).toHaveBeenCalledTimes(1);
    });

    it("fires onDidChangeTreeData when refresh is called explicitly", () => {
      const listener = vi.fn();
      provider.onDidChangeTreeData(listener);

      provider.refresh();

      expect(listener).toHaveBeenCalledTimes(1);
    });
  });

  describe("clearAll", () => {
    it("clears all statuses and current file, then refreshes", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "confirmed");
      provider.setCurrentFile("src/models/user.ts");

      const listener = vi.fn();
      provider.onDidChangeTreeData(listener);

      provider.clearAll();

      // After clear, files should be unread
      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      expect(foundationLayer.label).toBe("foundation (0/1 read)");

      // Refresh event should have fired
      expect(listener).toHaveBeenCalled();
    });
  });

  describe("subscribeMcpEvents", () => {
    it("handles mark_read events", () => {
      provider.updateMapData(makeMap());

      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({ tool: "mark_read", params: { path: "src/config.ts" } });

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);
      const icon = files[0].iconPath as { id: string };
      expect(icon.id).toBe("check");
    });

    it("handles mark_flagged events", () => {
      provider.updateMapData(makeMap());

      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({
        tool: "mark_flagged",
        params: { path: "src/config.ts", reason: "complex" },
      });

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);
      const icon = files[0].iconPath as { id: string };
      expect(icon.id).toBe("warning");
    });

    it("handles open_file events by setting current file", () => {
      provider.updateMapData(makeMap());

      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({
        tool: "open_file",
        params: { path: "src/config.ts" },
      });

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);
      const icon = files[0].iconPath as { id: string };
      expect(icon.id).toBe("eye");
    });

    it("handles update_progress_tree events by refreshing", () => {
      provider.updateMapData(makeMap());

      const listener = vi.fn();
      provider.onDidChangeTreeData(listener);

      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({ tool: "update_progress_tree", params: {} });

      expect(listener).toHaveBeenCalled();
    });

    it("handles clear_all events", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "confirmed");

      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({ tool: "clear_all", params: {} });

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      expect(foundationLayer.label).toBe("foundation (0/1 read)");
    });

    it("returns disposables from subscribeMcpEvents", () => {
      const emitter = new EventEmitter<McpToolEvent>();
      const disposables = provider.subscribeMcpEvents(emitter.event);

      expect(disposables).toBeDefined();
      expect(disposables.length).toBeGreaterThan(0);

      // Dispose and verify events no longer affect state
      for (const d of disposables) {
        d.dispose();
      }

      provider.updateMapData(makeMap());
      emitter.fire({ tool: "mark_read", params: { path: "src/config.ts" } });

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      // Should still be 0/1 because the disposable was disposed
      expect(foundationLayer.label).toBe("foundation (0/1 read)");
    });

    it("ignores unrelated tool events", () => {
      provider.updateMapData(makeMap());

      const listener = vi.fn();
      provider.onDidChangeTreeData(listener);

      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      // Reset after subscribe triggers refresh
      listener.mockClear();

      emitter.fire({
        tool: "highlight_range",
        params: { file: "src/config.ts", startLine: 1, endLine: 5 },
      });

      expect(listener).not.toHaveBeenCalled();
    });
  });

  describe("syncFromProgress", () => {
    it("populates file statuses from progress data", () => {
      provider.updateMapData(makeMap());
      provider.syncFromProgress({
        "src/config.ts": { status: "confirmed", read_at: "2026-04-04T10:00:00Z" },
        "src/models/user.ts": { status: "flagged", read_at: "2026-04-05T11:00:00Z" },
      });

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      expect(foundationLayer.label).toBe("foundation (1/1 read)");

      const coreLayer = layers.find((l) => l.contextValue === "layer:core")!;
      expect(coreLayer.label).toBe("core (1/1 read)");
    });

    it("removes statuses for files no longer in progress data", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "confirmed");
      provider.setFileStatus("src/models/user.ts", "flagged");

      // Sync with only config — user.ts should become unread
      provider.syncFromProgress({
        "src/config.ts": { status: "confirmed", read_at: "2026-04-04T10:00:00Z" },
      });

      const layers = provider.getChildren();
      const coreLayer = layers.find((l) => l.contextValue === "layer:core")!;
      expect(coreLayer.label).toBe("core (0/1 read)");
    });

    it("preserves currentFile across sync", () => {
      provider.updateMapData(makeMap());
      provider.setCurrentFile("src/config.ts");

      provider.syncFromProgress({
        "src/config.ts": { status: "confirmed", read_at: "2026-04-04T10:00:00Z" },
      });

      const layers = provider.getChildren();
      const foundationLayer = layers.find(
        (l) => l.contextValue === "layer:foundation",
      )!;
      const files = getFilesFromLayer(provider, foundationLayer);
      const icon = files[0].iconPath as { id: string };
      // Current takes priority
      expect(icon.id).toBe("eye");
    });

    it("fires onDidChangeTreeData event", () => {
      provider.updateMapData(makeMap());
      const listener = vi.fn();
      provider.onDidChangeTreeData(listener);

      provider.syncFromProgress({
        "src/config.ts": { status: "confirmed", read_at: "2026-04-04T10:00:00Z" },
      });

      expect(listener).toHaveBeenCalled();
    });

    it("ignores entries with unrecognized status", () => {
      provider.updateMapData(makeMap());
      provider.syncFromProgress({
        "src/config.ts": { status: "confirmed", read_at: "2026-04-04T10:00:00Z" },
        "src/models/user.ts": { status: "unknown_status", read_at: "2026-04-04T10:00:00Z" },
      });

      const layers = provider.getChildren();
      const coreLayer = layers.find((l) => l.contextValue === "layer:core")!;
      expect(coreLayer.label).toBe("core (0/1 read)");
    });
  });

  describe("dispose", () => {
    it("can be called without error", () => {
      provider.updateMapData(makeMap());
      provider.setFileStatus("src/config.ts", "confirmed");
      expect(() => provider.dispose()).not.toThrow();
    });
  });
});
