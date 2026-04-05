import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import {
  getMapData,
  getMapJsonUri,
  loadMapData,
  watchMapJson,
  dispose,
} from "../src/mapData";
import {
  __setWorkspaceFolders,
  __setFileContent,
  __clearFileContents,
  __getLastWatcher,
  Uri,
} from "./__mocks__/vscode";
import { readFileSync } from "fs";
import { join } from "path";

const VALID_MAP = readFileSync(
  join(__dirname, "fixtures", "valid-map.json"),
  "utf-8",
);

describe("mapData", () => {
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

  describe("getMapJsonUri", () => {
    it("returns the map.json URI within the workspace", () => {
      const uri = getMapJsonUri();
      expect(uri).toBeDefined();
      expect(uri!.path).toBe(
        "/mock/workspace/.codebase-guide/map.json",
      );
    });

    it("returns undefined when no workspace is open", () => {
      __setWorkspaceFolders(undefined);
      const uri = getMapJsonUri();
      expect(uri).toBeUndefined();
    });

    it("returns undefined when workspace folders array is empty", () => {
      __setWorkspaceFolders([]);
      const uri = getMapJsonUri();
      expect(uri).toBeUndefined();
    });
  });

  describe("loadMapData", () => {
    it("loads and parses valid map.json", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      const data = await loadMapData();
      expect(data).toBeDefined();
      expect(data!.version).toBe("1.0.0");
      expect(data!.total_files).toBe(2);
      expect(data!.reading_order).toHaveLength(2);
      expect(data!.reading_order[0].path).toBe("src/config.ts");
    });

    it("stores loaded data accessible via getMapData", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      expect(getMapData()).toBeUndefined();
      await loadMapData();
      expect(getMapData()).toBeDefined();
      expect(getMapData()!.total_files).toBe(2);
    });

    it("returns undefined when no workspace is open", async () => {
      __setWorkspaceFolders(undefined);
      const data = await loadMapData();
      expect(data).toBeUndefined();
    });

    it("returns undefined when map.json does not exist", async () => {
      // No file content set = file not found
      const data = await loadMapData();
      expect(data).toBeUndefined();
    });

    it("returns undefined for invalid JSON", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        "{ not valid json",
      );
      const data = await loadMapData();
      expect(data).toBeUndefined();
    });

    it("returns undefined for JSON missing required fields", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        JSON.stringify({ version: "1.0.0" }),
      );
      const data = await loadMapData();
      expect(data).toBeUndefined();
    });

    it("parses layers correctly", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      const data = await loadMapData();
      expect(data!.layers.foundation.files).toContain("src/config.ts");
      expect(data!.layers.core.files).toContain("src/models/user.ts");
    });

    it("parses dependency graph correctly", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      const data = await loadMapData();
      const configDeps = data!.dependency_graph["src/config.ts"];
      expect(configDeps.imports).toHaveLength(0);
      expect(configDeps.imported_by).toContain("src/models/user.ts");
    });
  });

  describe("watchMapJson", () => {
    it("creates a file system watcher", () => {
      const disposable = watchMapJson();
      const watcher = __getLastWatcher();
      expect(watcher).toBeDefined();
      disposable.dispose();
    });

    it("reloads map data when file changes", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      const disposable = watchMapJson();
      const watcher = __getLastWatcher()!;

      // Trigger change event
      await watcher.__fireChange();

      // Give the async handler a tick to complete
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(getMapData()).toBeDefined();
      expect(getMapData()!.total_files).toBe(2);
      disposable.dispose();
    });

    it("loads map data when file is created", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      const disposable = watchMapJson();
      const watcher = __getLastWatcher()!;

      // Trigger create event
      await watcher.__fireCreate();
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(getMapData()).toBeDefined();
      disposable.dispose();
    });

    it("clears map data when file is deleted", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      await loadMapData();
      expect(getMapData()).toBeDefined();

      const disposable = watchMapJson();
      const watcher = __getLastWatcher()!;

      // Trigger delete event
      watcher.__fireDelete();
      expect(getMapData()).toBeUndefined();
      disposable.dispose();
    });
  });

  describe("onMapDataChanged event", () => {
    it("fires when map data is loaded", async () => {
      const { onMapDataChanged } = await import("../src/mapData");
      const received: unknown[] = [];
      const sub = onMapDataChanged((data) => received.push(data));

      __setFileContent(
        "/mock/workspace/.codebase-guide/map.json",
        VALID_MAP,
      );
      await loadMapData();

      expect(received).toHaveLength(1);
      expect(received[0]).toBeDefined();
      sub.dispose();
    });
  });
});
