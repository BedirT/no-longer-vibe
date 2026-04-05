import { describe, it, expect } from "vitest";
import type {
  CodebaseMap,
  LayerName,
  Complexity,
  ReadingOrderEntry,
  DependencyInfo,
  Layer,
} from "../src/types";

/**
 * Type-level tests: verify the TypeScript interfaces match the SPEC.md schema.
 * These tests confirm structural correctness at compile time and runtime.
 */
describe("types", () => {
  describe("CodebaseMap interface", () => {
    it("accepts a valid map.json structure", () => {
      const map: CodebaseMap = {
        version: "1.0.0",
        repo_root: "/path/to/repo",
        generated_at: "2026-04-04T10:00:00Z",
        content_hashes: { "src/config.ts": "a3f2b8c1" },
        total_files: 1,
        layers: {
          foundation: { description: "Base layer", files: ["src/config.ts"] },
          core: { description: "Core", files: [] },
          features: { description: "Features", files: [] },
          integration: { description: "Integration", files: [] },
          entry: { description: "Entry", files: [] },
        },
        reading_order: [
          {
            index: 0,
            path: "src/config.ts",
            layer: "foundation",
            reason: "No deps",
            complexity: "low",
            line_count: 45,
            imports: [],
            imported_by: [],
            exports: ["AppConfig"],
          },
        ],
        dependency_graph: {
          "src/config.ts": { imports: [], imported_by: [] },
        },
      };

      expect(map.version).toBe("1.0.0");
      expect(map.total_files).toBe(1);
      expect(map.reading_order).toHaveLength(1);
    });
  });

  describe("LayerName type", () => {
    it("accepts all valid layer names", () => {
      const layers: LayerName[] = [
        "foundation",
        "core",
        "features",
        "integration",
        "entry",
      ];
      expect(layers).toHaveLength(5);
    });
  });

  describe("Complexity type", () => {
    it("accepts all valid complexity levels", () => {
      const levels: Complexity[] = ["low", "medium", "high"];
      expect(levels).toHaveLength(3);
    });
  });

  describe("ReadingOrderEntry interface", () => {
    it("has all required fields", () => {
      const entry: ReadingOrderEntry = {
        index: 0,
        path: "src/file.ts",
        layer: "foundation",
        reason: "No dependencies",
        complexity: "low",
        line_count: 50,
        imports: [],
        imported_by: ["src/other.ts"],
        exports: ["Foo"],
      };
      expect(entry.index).toBe(0);
      expect(entry.layer).toBe("foundation");
    });
  });

  describe("DependencyInfo interface", () => {
    it("has imports and imported_by arrays", () => {
      const dep: DependencyInfo = {
        imports: ["a.ts"],
        imported_by: ["b.ts"],
      };
      expect(dep.imports).toHaveLength(1);
      expect(dep.imported_by).toHaveLength(1);
    });
  });

  describe("Layer interface", () => {
    it("has description and files", () => {
      const layer: Layer = {
        description: "No or minimal internal dependencies",
        files: ["src/config.ts"],
      };
      expect(layer.description).toBeTruthy();
      expect(layer.files).toHaveLength(1);
    });
  });
});
