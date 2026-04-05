import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import { activate, deactivate } from "../src/extension";
import {
  __setWorkspaceFolders,
  __setFileContent,
  __clearFileContents,
  Uri,
  Disposable,
} from "./__mocks__/vscode";
import { getMapData, dispose } from "../src/mapData";
import { readFileSync } from "fs";
import { join } from "path";

const VALID_MAP = readFileSync(
  join(__dirname, "fixtures", "valid-map.json"),
  "utf-8",
);

/** Minimal mock of vscode.ExtensionContext */
function createMockContext(): {
  subscriptions: { dispose: () => void }[];
  extensionUri: Uri;
  extensionPath: string;
} {
  return {
    subscriptions: [],
    extensionUri: Uri.file("/mock/extension"),
    extensionPath: "/mock/extension",
  };
}

describe("extension", () => {
  beforeEach(() => {
    dispose();
    __clearFileContents();
    __setWorkspaceFolders([
      { uri: Uri.file("/mock/workspace"), name: "workspace", index: 0 },
    ]);
  });

  afterEach(() => {
    dispose();
    __clearFileContents();
  });

  describe("activate", () => {
    it("loads map.json when present", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      const ctx = createMockContext();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await activate(ctx as any);

      expect(getMapData()).toBeDefined();
      expect(getMapData()!.total_files).toBe(2);
    });

    it("registers disposables in context subscriptions", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      const ctx = createMockContext();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await activate(ctx as any);

      // Should have output channel + watcher disposable
      expect(ctx.subscriptions.length).toBeGreaterThanOrEqual(2);
    });

    it("handles missing map.json gracefully", async () => {
      const ctx = createMockContext();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await activate(ctx as any);

      expect(getMapData()).toBeUndefined();
      // Should still register subscriptions (watcher for future creation)
      expect(ctx.subscriptions.length).toBeGreaterThanOrEqual(1);
    });
  });

  describe("deactivate", () => {
    it("clears map data on deactivate", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      const ctx = createMockContext();
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await activate(ctx as any);
      expect(getMapData()).toBeDefined();

      deactivate();
      expect(getMapData()).toBeUndefined();
    });
  });
});
