import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import * as vscode from "vscode";
import {
  EventEmitter,
  __resetDecorationTracking,
  __getDecorationTypes,
  __getDecorationApplications,
  __setVisibleTextEditors,
  __createMockEditor,
} from "./__mocks__/vscode";
import { HighlightManager } from "../src/highlightManager";
import type { McpToolEvent } from "../src/mcpServer";

describe("HighlightManager", () => {
  let manager: HighlightManager;
  let toolEvents: vscode.EventEmitter<McpToolEvent>;

  beforeEach(() => {
    __resetDecorationTracking();
    toolEvents = new EventEmitter<McpToolEvent>();
    manager = new HighlightManager(toolEvents.event);
  });

  describe("initialization", () => {
    it("creates decoration types for all four styles on construction", () => {
      const types = __getDecorationTypes();
      // 4 base styles + 4 importance tiers = 8
      expect(types).toHaveLength(8);

      const options = types.map((t) => t.options);
      // focus style
      const focus = options.find(
        (o) => o.backgroundColor === "rgba(59, 130, 246, 0.07)",
      );
      expect(focus).toBeDefined();
      expect(focus!.borderLeft).toBe("3px solid rgba(59, 130, 246, 0.5)");

      // context style - no border
      const context = options.find(
        (o) => o.backgroundColor === "rgba(148, 163, 184, 0.06)",
      );
      expect(context).toBeDefined();
      expect(context!.borderLeft).toBeUndefined();

      // warning style
      const warning = options.find(
        (o) => o.backgroundColor === "rgba(245, 158, 11, 0.07)",
      );
      expect(warning).toBeDefined();
      expect(warning!.borderLeft).toBe("3px solid rgba(245, 158, 11, 0.5)");

      // blast-radius style
      const blastRadius = options.find(
        (o) => o.backgroundColor === "rgba(239, 68, 68, 0.07)",
      );
      expect(blastRadius).toBeDefined();
      expect(blastRadius!.borderLeft).toBe("3px solid rgba(239, 68, 68, 0.4)");
    });

    it("isWholeLine is true for all decoration types", () => {
      const types = __getDecorationTypes();
      for (const t of types) {
        expect(t.options.isWholeLine).toBe(true);
      }
    });
  });

  describe("highlight_range event handling", () => {
    it("converts 1-indexed lines to 0-indexed ranges", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 10,
          endLine: 20,
          style: "focus",
        },
      });

      const apps = __getDecorationApplications();
      // 4 styles applied per editor (one with ranges, three empty)
      expect(apps.length).toBeGreaterThanOrEqual(1);
      // Find the app with non-empty ranges (the focus style)
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges).toBeDefined();
      // startLine 10 -> 0-indexed 9, endLine 20 -> 0-indexed 19
      expect(appWithRanges!.ranges[0].start.line).toBe(9);
      expect(appWithRanges!.ranges[0].start.character).toBe(0);
      expect(appWithRanges!.ranges[0].end.line).toBe(19);
      expect(appWithRanges!.ranges[0].end.character).toBe(0);
    });

    it("applies the correct decoration type for each style", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      const styles = [
        "focus",
        "context",
        "warning",
        "blast-radius",
      ] as const;
      for (const style of styles) {
        toolEvents.fire({
          tool: "highlight_range",
          params: { file: "src/main.ts", startLine: 1, endLine: 5, style },
        });
      }

      const apps = __getDecorationApplications();
      // Each highlight_range call applies all 8 decoration types to the editor
      // (4 base styles + 4 importance tiers)
      // 4 calls * 8 types = 32 total applications
      expect(apps.length).toBe(32);
      // Each of the 4 styles should have at least one non-empty range application
      const nonEmptyApps = apps.filter((a) => a.ranges.length > 0);
      expect(nonEmptyApps.length).toBeGreaterThanOrEqual(4);
    });

    it("supports multiple highlights in the same file", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 10,
          endLine: 15,
          style: "warning",
        },
      });

      // Both should be tracked
      const tracked = manager.getHighlightsForFile("src/main.ts");
      expect(tracked).toHaveLength(2);
    });

    it("supports multiple highlights with different styles in same file", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 10,
          endLine: 15,
          style: "context",
        },
      });

      const tracked = manager.getHighlightsForFile("src/main.ts");
      expect(tracked).toHaveLength(2);
      expect(tracked![0].style).toBe("focus");
      expect(tracked![1].style).toBe("context");
    });

    it("supports highlights in different files", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/a.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/b.ts",
          startLine: 1,
          endLine: 5,
          style: "context",
        },
      });

      expect(manager.getHighlightsForFile("src/a.ts")).toHaveLength(1);
      expect(manager.getHighlightsForFile("src/b.ts")).toHaveLength(1);
    });

    it("ignores non-highlight_range events", () => {
      toolEvents.fire({
        tool: "open_file",
        params: { path: "src/main.ts" },
      });

      expect(manager.getHighlightsForFile("src/main.ts")).toBeUndefined();
    });
  });

  describe("clear_highlights event handling", () => {
    it("clears highlights for a specific file", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/a.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/b.ts",
          startLine: 1,
          endLine: 5,
          style: "context",
        },
      });

      toolEvents.fire({
        tool: "clear_highlights",
        params: { file: "src/a.ts" },
      });

      expect(manager.getHighlightsForFile("src/a.ts")).toBeUndefined();
      expect(manager.getHighlightsForFile("src/b.ts")).toHaveLength(1);
    });

    it("clears highlights for all files when no file specified", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/a.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/b.ts",
          startLine: 1,
          endLine: 5,
          style: "context",
        },
      });

      toolEvents.fire({
        tool: "clear_highlights",
        params: {},
      });

      expect(manager.getHighlightsForFile("src/a.ts")).toBeUndefined();
      expect(manager.getHighlightsForFile("src/b.ts")).toBeUndefined();
    });

    it("applies empty ranges to editors after clearing", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });

      const appsBefore = __getDecorationApplications().length;

      toolEvents.fire({
        tool: "clear_highlights",
        params: { file: "src/main.ts" },
      });

      const appsAfter = __getDecorationApplications().length;
      // Clearing should apply decorations with empty ranges
      expect(appsAfter).toBeGreaterThan(appsBefore);
      // The clear calls should all have empty ranges
      const clearApps = __getDecorationApplications().slice(appsBefore);
      for (const app of clearApps) {
        expect(app.ranges).toHaveLength(0);
      }
    });
  });

  describe("clear_all event handling", () => {
    it("clears all highlights on clear_all", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/a.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });

      toolEvents.fire({ tool: "clear_all", params: {} });

      expect(manager.getHighlightsForFile("src/a.ts")).toBeUndefined();
    });
  });

  describe("dispose", () => {
    it("cleans up all decoration types on dispose", () => {
      const types = __getDecorationTypes();
      const disposeSpy = types.map((t) => vi.spyOn(t, "dispose"));

      manager.dispose();

      for (const spy of disposeSpy) {
        expect(spy).toHaveBeenCalledOnce();
      }
    });

    it("clears tracked highlights on dispose", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });

      manager.dispose();

      expect(manager.getHighlightsForFile("src/main.ts")).toBeUndefined();
    });

    it("unsubscribes from events on dispose", () => {
      manager.dispose();

      // Firing events after dispose should not add highlights
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 5,
          style: "focus",
        },
      });

      expect(manager.getHighlightsForFile("src/main.ts")).toBeUndefined();
    });
  });

  describe("edge cases", () => {
    it("handles single-line highlight (startLine === endLine)", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 5,
          endLine: 5,
          style: "focus",
        },
      });

      const tracked = manager.getHighlightsForFile("src/main.ts");
      expect(tracked).toHaveLength(1);

      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges).toBeDefined();
      expect(appWithRanges!.ranges[0].start.line).toBe(4);
      expect(appWithRanges!.ranges[0].end.line).toBe(4);
    });

    it("clearing a file with no highlights is a no-op", () => {
      // Should not throw
      toolEvents.fire({
        tool: "clear_highlights",
        params: { file: "src/nonexistent.ts" },
      });

      expect(manager.getHighlightsForFile("src/nonexistent.ts")).toBeUndefined();
    });

    it("returns undefined for files with no highlights", () => {
      expect(manager.getHighlightsForFile("src/unknown.ts")).toBeUndefined();
    });
  });

  describe("importance-weighted highlighting (BED-100)", () => {
    it("creates 8 decoration types: 4 base styles + 4 importance tiers", () => {
      const types = __getDecorationTypes();
      expect(types).toHaveLength(8);
    });

    it("tracks importance on highlight when provided", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 10,
          style: "focus",
          importance: 0.8,
        },
      });

      const tracked = manager.getHighlightsForFile("src/main.ts");
      expect(tracked).toHaveLength(1);
      expect(tracked![0].importance).toBe(0.8);
    });

    it("importance is undefined when not provided", () => {
      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 10,
          style: "focus",
        },
      });

      const tracked = manager.getHighlightsForFile("src/main.ts");
      expect(tracked![0].importance).toBeUndefined();
    });

    it("uses critical tier for importance >= 0.75", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 10,
          style: "focus",
          importance: 0.9,
        },
      });

      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges).toBeDefined();
      // Critical tier: strong blue wash with thick border
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe(
        "rgba(59, 130, 246, 0.14)",
      );
      expect(appWithRanges!.decorationType.options.borderLeft).toBe(
        "4px solid rgba(59, 130, 246, 0.7)",
      );
    });

    it("uses important tier for importance >= 0.5", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 10,
          style: "focus",
          importance: 0.6,
        },
      });

      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges).toBeDefined();
      // Important tier: green wash with border
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe(
        "rgba(34, 197, 94, 0.10)",
      );
      expect(appWithRanges!.decorationType.options.borderLeft).toBe(
        "3px solid rgba(34, 197, 94, 0.5)",
      );
    });

    it("uses standard tier for importance >= 0.25", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 10,
          style: "focus",
          importance: 0.3,
        },
      });

      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges).toBeDefined();
      // Standard tier: grey wash with thin border
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe(
        "rgba(148, 163, 184, 0.08)",
      );
      expect(appWithRanges!.decorationType.options.borderLeft).toBe(
        "2px solid rgba(148, 163, 184, 0.3)",
      );
    });

    it("uses low tier for importance < 0.25 (dead code)", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 10,
          style: "focus",
          importance: 0.1,
        },
      });

      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges).toBeDefined();
      // Low tier: very subtle grey for low-use code
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe(
        "rgba(148, 163, 184, 0.04)",
      );
      expect(appWithRanges!.decorationType.options.borderLeft).toBeUndefined();
    });

    it("falls back to base focus style when no importance provided", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 10,
          style: "focus",
        },
      });

      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges).toBeDefined();
      // Original focus style
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe(
        "rgba(59, 130, 246, 0.07)",
      );
      expect(appWithRanges!.decorationType.options.borderLeft).toBe(
        "3px solid rgba(59, 130, 246, 0.5)",
      );
    });

    it("uses critical tier at exact boundary 0.75", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);
      toolEvents.fire({
        tool: "highlight_range",
        params: { file: "src/main.ts", startLine: 1, endLine: 5, style: "focus", importance: 0.75 },
      });
      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe("rgba(59, 130, 246, 0.14)");
    });

    it("uses important tier just below 0.75", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);
      toolEvents.fire({
        tool: "highlight_range",
        params: { file: "src/main.ts", startLine: 1, endLine: 5, style: "focus", importance: 0.74 },
      });
      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe("rgba(34, 197, 94, 0.10)");
    });

    it("uses important tier at exact boundary 0.5", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);
      toolEvents.fire({
        tool: "highlight_range",
        params: { file: "src/main.ts", startLine: 1, endLine: 5, style: "focus", importance: 0.5 },
      });
      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe("rgba(34, 197, 94, 0.10)");
    });

    it("uses standard tier at exact boundary 0.25", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);
      toolEvents.fire({
        tool: "highlight_range",
        params: { file: "src/main.ts", startLine: 1, endLine: 5, style: "focus", importance: 0.25 },
      });
      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe("rgba(148, 163, 184, 0.08)");
    });

    it("handles importance 0.0 as low tier", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);
      toolEvents.fire({
        tool: "highlight_range",
        params: { file: "src/main.ts", startLine: 1, endLine: 5, style: "focus", importance: 0.0 },
      });
      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe("rgba(148, 163, 184, 0.04)");
    });

    it("handles importance 1.0 as critical tier", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);
      toolEvents.fire({
        tool: "highlight_range",
        params: { file: "src/main.ts", startLine: 1, endLine: 5, style: "focus", importance: 1.0 },
      });
      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe("rgba(59, 130, 246, 0.14)");
    });

    it("ignores importance for non-focus styles", () => {
      __setVisibleTextEditors([__createMockEditor("src/main.ts")]);

      toolEvents.fire({
        tool: "highlight_range",
        params: {
          file: "src/main.ts",
          startLine: 1,
          endLine: 10,
          style: "warning",
          importance: 0.9,
        },
      });

      const apps = __getDecorationApplications();
      const appWithRanges = apps.find((a) => a.ranges.length > 0);
      expect(appWithRanges).toBeDefined();
      // Should still use the warning style, not importance tier
      expect(appWithRanges!.decorationType.options.backgroundColor).toBe(
        "rgba(245, 158, 11, 0.07)",
      );
    });
  });
});
