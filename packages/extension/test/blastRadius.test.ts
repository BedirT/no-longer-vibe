import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import { BlastRadiusProvider } from "../src/blastRadius";
import type { CodebaseMap } from "../src/types";
import { Uri, ThemeColor, EventEmitter } from "./__mocks__/vscode";
import type { McpToolEvent } from "../src/mcpServer";

/**
 * Builds a CodebaseMap with a multi-level dependency graph for blast radius testing.
 *
 * Graph structure:
 *   config.ts -> models/user.ts -> services/db.ts -> api/routes.ts
 *                                                 -> middleware/auth.ts
 *                -> components/Dashboard.tsx
 *   utils.ts  (isolated, no dependents)
 */
function makeMap(overrides?: Partial<CodebaseMap>): CodebaseMap {
  return {
    version: "1.0.0",
    repo_root: "/mock/workspace",
    generated_at: "2026-04-04T10:00:00Z",
    content_hashes: {
      "src/config.ts": "a1",
      "src/models/user.ts": "a2",
      "src/services/db.ts": "a3",
      "src/api/routes.ts": "a4",
      "src/middleware/auth.ts": "a5",
      "src/components/Dashboard.tsx": "a6",
      "src/utils.ts": "a7",
    },
    total_files: 7,
    layers: {
      foundation: {
        description: "No or minimal internal dependencies",
        files: ["src/config.ts", "src/utils.ts"],
      },
      core: {
        description: "Depends only on foundation",
        files: ["src/models/user.ts"],
      },
      features: {
        description: "Business logic, depends on core",
        files: ["src/components/Dashboard.tsx", "src/services/db.ts"],
      },
      integration: {
        description: "Composes features, middleware, API routes",
        files: ["src/api/routes.ts", "src/middleware/auth.ts"],
      },
      entry: {
        description: "App entry points",
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
        imported_by: ["src/models/user.ts", "src/components/Dashboard.tsx"],
        exports: ["AppConfig", "getConfig"],
      },
      {
        index: 1,
        path: "src/utils.ts",
        layer: "foundation",
        reason: "No dependencies.",
        complexity: "low",
        line_count: 20,
        imports: [],
        imported_by: [],
        exports: ["formatDate"],
      },
      {
        index: 2,
        path: "src/models/user.ts",
        layer: "core",
        reason: "Depends on config.",
        complexity: "medium",
        line_count: 120,
        imports: ["src/config.ts"],
        imported_by: ["src/services/db.ts"],
        exports: ["User", "createUser"],
      },
      {
        index: 3,
        path: "src/services/db.ts",
        layer: "features",
        reason: "Depends on models.",
        complexity: "medium",
        line_count: 80,
        imports: ["src/models/user.ts"],
        imported_by: ["src/api/routes.ts", "src/middleware/auth.ts"],
        exports: ["DbService", "query"],
      },
      {
        index: 4,
        path: "src/components/Dashboard.tsx",
        layer: "features",
        reason: "Depends on config.",
        complexity: "high",
        line_count: 200,
        imports: ["src/config.ts"],
        imported_by: [],
        exports: ["Dashboard"],
      },
      {
        index: 5,
        path: "src/api/routes.ts",
        layer: "integration",
        reason: "Depends on db.",
        complexity: "medium",
        line_count: 150,
        imports: ["src/services/db.ts"],
        imported_by: [],
        exports: ["router"],
      },
      {
        index: 6,
        path: "src/middleware/auth.ts",
        layer: "integration",
        reason: "Depends on db.",
        complexity: "medium",
        line_count: 142,
        imports: ["src/services/db.ts"],
        imported_by: [],
        exports: ["authMiddleware"],
      },
    ],
    dependency_graph: {
      "src/config.ts": {
        imports: [],
        imported_by: ["src/models/user.ts", "src/components/Dashboard.tsx"],
      },
      "src/utils.ts": {
        imports: [],
        imported_by: [],
      },
      "src/models/user.ts": {
        imports: ["src/config.ts"],
        imported_by: ["src/services/db.ts"],
      },
      "src/services/db.ts": {
        imports: ["src/models/user.ts"],
        imported_by: ["src/api/routes.ts", "src/middleware/auth.ts"],
      },
      "src/api/routes.ts": {
        imports: ["src/services/db.ts"],
        imported_by: [],
      },
      "src/middleware/auth.ts": {
        imports: ["src/services/db.ts"],
        imported_by: [],
      },
      "src/components/Dashboard.tsx": {
        imports: ["src/config.ts"],
        imported_by: [],
      },
    },
    ...overrides,
  };
}

function makeUri(relativePath: string): Uri {
  return Uri.file(`/mock/workspace/${relativePath}`);
}

describe("BlastRadiusProvider", () => {
  let provider: BlastRadiusProvider;
  let map: CodebaseMap;

  beforeEach(() => {
    map = makeMap();
    provider = new BlastRadiusProvider("/mock/workspace");
    provider.updateMapData(map);
  });

  describe("findFileForSymbol", () => {
    it("finds the file exporting a given symbol", () => {
      const file = provider.findFileForSymbol("AppConfig");
      expect(file).toBe("src/config.ts");
    });

    it("finds a different symbol in a different file", () => {
      const file = provider.findFileForSymbol("User");
      expect(file).toBe("src/models/user.ts");
    });

    it("returns undefined for an unknown symbol", () => {
      const file = provider.findFileForSymbol("NonExistent");
      expect(file).toBeUndefined();
    });
  });

  describe("computeBlastRadius", () => {
    it("returns direct dependents for a leaf file", () => {
      // src/services/db.ts is imported by routes.ts and auth.ts
      const result = provider.computeBlastRadius("src/services/db.ts");
      expect(result.sort()).toEqual(
        ["src/api/routes.ts", "src/middleware/auth.ts"].sort(),
      );
    });

    it("returns transitive dependents (multi-level)", () => {
      // src/models/user.ts is imported by db.ts, which is imported by routes.ts and auth.ts
      const result = provider.computeBlastRadius("src/models/user.ts");
      expect(result.sort()).toEqual(
        [
          "src/services/db.ts",
          "src/api/routes.ts",
          "src/middleware/auth.ts",
        ].sort(),
      );
    });

    it("returns deep transitive dependents from a foundation file", () => {
      // config.ts -> user.ts -> db.ts -> routes.ts, auth.ts
      // config.ts -> Dashboard.tsx
      const result = provider.computeBlastRadius("src/config.ts");
      expect(result.sort()).toEqual(
        [
          "src/models/user.ts",
          "src/services/db.ts",
          "src/api/routes.ts",
          "src/middleware/auth.ts",
          "src/components/Dashboard.tsx",
        ].sort(),
      );
    });

    it("returns empty array for a file with no dependents", () => {
      const result = provider.computeBlastRadius("src/utils.ts");
      expect(result).toEqual([]);
    });

    it("returns empty array for an unknown file", () => {
      const result = provider.computeBlastRadius("src/nonexistent.ts");
      expect(result).toEqual([]);
    });

    it("does not include the source file itself in the blast radius", () => {
      const result = provider.computeBlastRadius("src/config.ts");
      expect(result).not.toContain("src/config.ts");
    });

    it("handles circular dependencies without infinite loop", () => {
      const circularMap = makeMap({
        dependency_graph: {
          "src/a.ts": {
            imports: ["src/b.ts"],
            imported_by: ["src/b.ts"],
          },
          "src/b.ts": {
            imports: ["src/a.ts"],
            imported_by: ["src/a.ts"],
          },
        },
      });
      provider.updateMapData(circularMap);

      const result = provider.computeBlastRadius("src/a.ts");
      // b.ts imports a.ts (so b.ts is affected), and a.ts imports b.ts
      // which means a.ts appears in b.ts's imported_by, so BFS visits a.ts too.
      // The key assertion: it terminates and includes the circular peer.
      expect(result.sort()).toEqual(["src/a.ts", "src/b.ts"].sort());
    });
  });

  describe("showBlastRadius", () => {
    it("returns affected files and count for a valid symbol", () => {
      const result = provider.showBlastRadius("DbService");
      expect(result).toBeDefined();
      expect(result!.sourceFile).toBe("src/services/db.ts");
      expect(result!.affectedFiles.sort()).toEqual(
        ["src/api/routes.ts", "src/middleware/auth.ts"].sort(),
      );
      expect(result!.affectedCount).toBe(2);
    });

    it("returns affected files for a symbol with transitive dependents", () => {
      const result = provider.showBlastRadius("AppConfig");
      expect(result).toBeDefined();
      expect(result!.sourceFile).toBe("src/config.ts");
      expect(result!.affectedCount).toBe(5);
    });

    it("returns undefined for an unknown symbol", () => {
      const result = provider.showBlastRadius("UnknownSymbol");
      expect(result).toBeUndefined();
    });

    it("stores the active blast radius state", () => {
      expect(provider.isActive()).toBe(false);
      provider.showBlastRadius("DbService");
      expect(provider.isActive()).toBe(true);
    });

    it("returns the affected files via getAffectedFiles when active", () => {
      provider.showBlastRadius("DbService");
      const affected = provider.getAffectedFiles();
      expect(affected.sort()).toEqual(
        ["src/api/routes.ts", "src/middleware/auth.ts"].sort(),
      );
    });
  });

  describe("clearBlastRadius", () => {
    it("clears the active blast radius state", () => {
      provider.showBlastRadius("DbService");
      expect(provider.isActive()).toBe(true);

      provider.clearBlastRadius();
      expect(provider.isActive()).toBe(false);
      expect(provider.getAffectedFiles()).toEqual([]);
    });

    it("is safe to call when no blast radius is active", () => {
      expect(() => provider.clearBlastRadius()).not.toThrow();
    });
  });

  describe("provideFileDecoration", () => {
    it("returns undefined when blast radius is not active", () => {
      const decoration = provider.provideFileDecoration(
        makeUri("src/api/routes.ts"),
      );
      expect(decoration).toBeUndefined();
    });

    it("returns orange decoration for affected files", () => {
      provider.showBlastRadius("DbService");

      const decoration = provider.provideFileDecoration(
        makeUri("src/api/routes.ts"),
      );
      expect(decoration).toBeDefined();
      expect(decoration!.badge).toBe("!");
      expect(decoration!.color).toBeInstanceOf(ThemeColor);
      expect((decoration!.color as ThemeColor).id).toBe(
        "noLongerVibe.flagged",
      );
    });

    it("returns undefined for non-affected files when blast radius is active", () => {
      provider.showBlastRadius("DbService");

      const decoration = provider.provideFileDecoration(
        makeUri("src/utils.ts"),
      );
      expect(decoration).toBeUndefined();
    });

    it("returns undefined for files outside workspace", () => {
      provider.showBlastRadius("DbService");

      const outsideUri = Uri.file("/other/workspace/file.ts");
      const decoration = provider.provideFileDecoration(outsideUri);
      expect(decoration).toBeUndefined();
    });

    it("returns decoration for source file itself", () => {
      provider.showBlastRadius("DbService");

      // The source file (where the symbol lives) should also be decorated
      const decoration = provider.provideFileDecoration(
        makeUri("src/services/db.ts"),
      );
      expect(decoration).toBeDefined();
      expect(decoration!.tooltip?.toLowerCase()).toContain("blast radius");
    });

    it("clears decorations after clearBlastRadius", () => {
      provider.showBlastRadius("DbService");
      provider.clearBlastRadius();

      const decoration = provider.provideFileDecoration(
        makeUri("src/api/routes.ts"),
      );
      expect(decoration).toBeUndefined();
    });
  });

  describe("onDidChangeFileDecorations", () => {
    it("fires when blast radius is shown", () => {
      const fired: unknown[] = [];
      provider.onDidChangeFileDecorations((e) => fired.push(e));

      provider.showBlastRadius("DbService");
      expect(fired.length).toBe(1);
      // Global refresh fires undefined
      expect(fired[0]).toBeUndefined();
    });

    it("fires when blast radius is cleared", () => {
      provider.showBlastRadius("DbService");

      const fired: unknown[] = [];
      provider.onDidChangeFileDecorations((e) => fired.push(e));

      provider.clearBlastRadius();
      expect(fired.length).toBe(1);
    });
  });

  describe("MCP event integration", () => {
    it("activates blast radius on show_blast_radius event", () => {
      const emitter = new EventEmitter<McpToolEvent>();
      const disposables = provider.subscribeMcpEvents(emitter.event);

      emitter.fire({ tool: "show_blast_radius", params: { symbol: "DbService" } });

      expect(provider.isActive()).toBe(true);
      expect(provider.getAffectedFiles().sort()).toEqual(
        ["src/api/routes.ts", "src/middleware/auth.ts"].sort(),
      );

      for (const d of disposables) {
        d.dispose();
      }
    });

    it("clears blast radius on clear_blast_radius event", () => {
      provider.showBlastRadius("DbService");

      const emitter = new EventEmitter<McpToolEvent>();
      const disposables = provider.subscribeMcpEvents(emitter.event);

      emitter.fire({ tool: "clear_blast_radius", params: {} });

      expect(provider.isActive()).toBe(false);

      for (const d of disposables) {
        d.dispose();
      }
    });

    it("clears blast radius on clear_all event", () => {
      provider.showBlastRadius("DbService");

      const emitter = new EventEmitter<McpToolEvent>();
      const disposables = provider.subscribeMcpEvents(emitter.event);

      emitter.fire({ tool: "clear_all", params: {} });

      expect(provider.isActive()).toBe(false);

      for (const d of disposables) {
        d.dispose();
      }
    });
  });

  describe("updateMapData", () => {
    it("clears blast radius when map data is updated", () => {
      provider.showBlastRadius("DbService");
      expect(provider.isActive()).toBe(true);

      provider.updateMapData(makeMap());
      expect(provider.isActive()).toBe(false);
    });

    it("handles undefined map data gracefully", () => {
      provider.updateMapData(undefined);
      const result = provider.showBlastRadius("AppConfig");
      expect(result).toBeUndefined();
    });
  });

  describe("dispose", () => {
    it("cleans up without error", () => {
      provider.showBlastRadius("DbService");
      expect(() => provider.dispose()).not.toThrow();
    });
  });
});
