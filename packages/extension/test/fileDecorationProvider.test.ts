import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import {
  FileStatusDecorationProvider,
  type FileStatus,
} from "../src/fileDecorationProvider";
import { Uri, ThemeColor, EventEmitter } from "./__mocks__/vscode";
import type { McpToolEvent } from "../src/mcpServer";

function makeUri(relativePath: string): Uri {
  return Uri.file(`/mock/workspace/${relativePath}`);
}

describe("FileStatusDecorationProvider", () => {
  let provider: FileStatusDecorationProvider;

  beforeEach(() => {
    provider = new FileStatusDecorationProvider("/mock/workspace");
  });

  describe("provideFileDecoration", () => {
    it("returns undefined for unread files (no status set)", () => {
      const uri = makeUri("src/config.ts");
      const decoration = provider.provideFileDecoration(uri);
      expect(decoration).toBeUndefined();
    });

    it("returns confirmed decoration with checkmark badge", () => {
      provider.setFileStatus("src/config.ts", "confirmed");
      const uri = makeUri("src/config.ts");
      const decoration = provider.provideFileDecoration(uri);

      expect(decoration).toBeDefined();
      expect(decoration!.badge).toBe("\u2713");
      expect(decoration!.tooltip).toBe("Read and understood");
      expect(decoration!.color).toBeInstanceOf(ThemeColor);
      expect((decoration!.color as ThemeColor).id).toBe(
        "noLongerVibe.confirmed",
      );
      expect(decoration!.propagate).toBe(false);
    });

    it("returns flagged decoration with exclamation badge", () => {
      provider.setFileStatus("src/auth.ts", "flagged");
      const uri = makeUri("src/auth.ts");
      const decoration = provider.provideFileDecoration(uri);

      expect(decoration).toBeDefined();
      expect(decoration!.badge).toBe("!");
      expect(decoration!.tooltip).toBe("Flagged \u2014 needs second pass");
      expect((decoration!.color as ThemeColor).id).toBe(
        "noLongerVibe.flagged",
      );
      expect(decoration!.propagate).toBe(false);
    });

    it("returns current decoration with triangle badge", () => {
      provider.setCurrentFile("src/middleware.ts");
      const uri = makeUri("src/middleware.ts");
      const decoration = provider.provideFileDecoration(uri);

      expect(decoration).toBeDefined();
      expect(decoration!.badge).toBe("\u25B8");
      expect(decoration!.tooltip).toBe("Currently reading");
      expect((decoration!.color as ThemeColor).id).toBe(
        "noLongerVibe.current",
      );
      expect(decoration!.propagate).toBe(false);
    });

    it("returns skimmed decoration with tilde badge", () => {
      provider.setFileStatus("src/utils.ts", "skimmed");
      const uri = makeUri("src/utils.ts");
      const decoration = provider.provideFileDecoration(uri);

      expect(decoration).toBeDefined();
      expect(decoration!.badge).toBe("~");
      expect(decoration!.tooltip).toBe("Skimmed \u2014 deeper review later");
      expect((decoration!.color as ThemeColor).id).toBe(
        "noLongerVibe.skimmed",
      );
      expect(decoration!.propagate).toBe(false);
    });
  });

  describe("current file takes priority over other statuses", () => {
    it("shows current decoration even if file is confirmed", () => {
      provider.setFileStatus("src/config.ts", "confirmed");
      provider.setCurrentFile("src/config.ts");
      const uri = makeUri("src/config.ts");
      const decoration = provider.provideFileDecoration(uri);

      expect(decoration!.badge).toBe("\u25B8");
      expect(decoration!.tooltip).toBe("Currently reading");
    });

    it("shows current decoration even if file is flagged", () => {
      provider.setFileStatus("src/auth.ts", "flagged");
      provider.setCurrentFile("src/auth.ts");
      const uri = makeUri("src/auth.ts");
      const decoration = provider.provideFileDecoration(uri);

      expect(decoration!.badge).toBe("\u25B8");
    });
  });

  describe("setFileStatus", () => {
    it("updates status and fires change event", () => {
      const firedUris: Uri[] = [];
      provider.onDidChangeFileDecorations((uri) => {
        if (uri) firedUris.push(uri);
      });

      provider.setFileStatus("src/config.ts", "confirmed");

      expect(firedUris).toHaveLength(1);
      expect(firedUris[0].path).toContain("src/config.ts");
    });

    it("can override an existing status", () => {
      provider.setFileStatus("src/config.ts", "confirmed");
      provider.setFileStatus("src/config.ts", "flagged");

      const uri = makeUri("src/config.ts");
      const decoration = provider.provideFileDecoration(uri);
      expect(decoration!.badge).toBe("!");
    });
  });

  describe("setCurrentFile", () => {
    it("fires change events for both old and new current file", () => {
      provider.setCurrentFile("src/first.ts");

      const firedUris: Uri[] = [];
      provider.onDidChangeFileDecorations((uri) => {
        if (uri) firedUris.push(uri);
      });

      provider.setCurrentFile("src/second.ts");

      // Should fire for old file (src/first.ts) and new file (src/second.ts)
      expect(firedUris).toHaveLength(2);
      const paths = firedUris.map((u) => u.path);
      expect(paths.some((p) => p.includes("first.ts"))).toBe(true);
      expect(paths.some((p) => p.includes("second.ts"))).toBe(true);
    });

    it("clears current file when set to undefined", () => {
      provider.setCurrentFile("src/config.ts");
      provider.setCurrentFile(undefined);

      const uri = makeUri("src/config.ts");
      const decoration = provider.provideFileDecoration(uri);
      // Should fall back to no decoration (unread by default)
      expect(decoration).toBeUndefined();
    });

    it("fires change event for old file when clearing current", () => {
      provider.setCurrentFile("src/config.ts");

      const firedUris: Uri[] = [];
      provider.onDidChangeFileDecorations((uri) => {
        if (uri) firedUris.push(uri);
      });

      provider.setCurrentFile(undefined);
      expect(firedUris).toHaveLength(1);
      expect(firedUris[0].path).toContain("config.ts");
    });
  });

  describe("clearAll", () => {
    it("clears all statuses and current file", () => {
      provider.setFileStatus("src/config.ts", "confirmed");
      provider.setFileStatus("src/auth.ts", "flagged");
      provider.setCurrentFile("src/middleware.ts");

      provider.clearAll();

      expect(
        provider.provideFileDecoration(makeUri("src/config.ts")),
      ).toBeUndefined();
      expect(
        provider.provideFileDecoration(makeUri("src/auth.ts")),
      ).toBeUndefined();
      expect(
        provider.provideFileDecoration(makeUri("src/middleware.ts")),
      ).toBeUndefined();
    });

    it("fires change event with undefined to refresh all files", () => {
      let firedCount = 0;
      let lastUri: Uri | undefined;
      provider.onDidChangeFileDecorations((uri) => {
        firedCount++;
        lastUri = uri ?? undefined;
      });

      provider.clearAll();

      expect(firedCount).toBe(1);
      // undefined means refresh all decorations
      expect(lastUri).toBeUndefined();
    });
  });

  describe("files outside workspace root", () => {
    it("returns undefined for files outside the workspace root", () => {
      provider.setFileStatus("src/config.ts", "confirmed");
      const uri = Uri.file("/other/workspace/src/config.ts");
      const decoration = provider.provideFileDecoration(uri);
      expect(decoration).toBeUndefined();
    });
  });

  describe("subscribeMcpEvents", () => {
    it("handles mark_read events by setting confirmed status", () => {
      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({ tool: "mark_read", params: { path: "src/config.ts" } });

      const decoration = provider.provideFileDecoration(
        makeUri("src/config.ts"),
      );
      expect(decoration!.badge).toBe("\u2713");
    });

    it("handles mark_flagged events by setting flagged status", () => {
      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({
        tool: "mark_flagged",
        params: { path: "src/auth.ts", reason: "complex" },
      });

      const decoration = provider.provideFileDecoration(
        makeUri("src/auth.ts"),
      );
      expect(decoration!.badge).toBe("!");
    });

    it("handles clear_all events by clearing all state", () => {
      provider.setFileStatus("src/config.ts", "confirmed");

      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({ tool: "clear_all", params: {} });

      expect(
        provider.provideFileDecoration(makeUri("src/config.ts")),
      ).toBeUndefined();
    });

    it("handles open_file events by setting current file", () => {
      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({
        tool: "open_file",
        params: { path: "src/middleware.ts" },
      });

      const decoration = provider.provideFileDecoration(
        makeUri("src/middleware.ts"),
      );
      expect(decoration!.badge).toBe("\u25B8");
    });

    it("ignores unrelated tool events", () => {
      const emitter = new EventEmitter<McpToolEvent>();
      provider.subscribeMcpEvents(emitter.event);

      emitter.fire({
        tool: "highlight_range",
        params: { file: "src/config.ts", startLine: 1, endLine: 5 },
      });

      // Should not set any decoration
      expect(
        provider.provideFileDecoration(makeUri("src/config.ts")),
      ).toBeUndefined();
    });

    it("returns disposables from subscribeMcpEvents", () => {
      const emitter = new EventEmitter<McpToolEvent>();
      const disposables = provider.subscribeMcpEvents(emitter.event);

      expect(disposables).toBeDefined();
      expect(disposables.length).toBeGreaterThan(0);

      // Dispose and verify events no longer fire
      for (const d of disposables) {
        d.dispose();
      }

      emitter.fire({ tool: "mark_read", params: { path: "src/new.ts" } });

      expect(
        provider.provideFileDecoration(makeUri("src/new.ts")),
      ).toBeUndefined();
    });
  });

  describe("getFileStatus", () => {
    it("returns undefined for unknown files", () => {
      expect(provider.getFileStatus("src/unknown.ts")).toBeUndefined();
    });

    it("returns the current status for a known file", () => {
      provider.setFileStatus("src/config.ts", "confirmed");
      expect(provider.getFileStatus("src/config.ts")).toBe("confirmed");
    });
  });

  describe("dispose", () => {
    it("can be called without error", () => {
      provider.setFileStatus("src/config.ts", "confirmed");
      expect(() => provider.dispose()).not.toThrow();
    });
  });
});
