import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import {
  getProgressJsonUri,
  loadProgressData,
  getProgressData,
  watchProgressJson,
  onProgressDataChanged,
  dispose as disposeProgressData,
} from "../src/progressData";
import {
  __setWorkspaceFolders,
  __setFileContent,
  __clearFileContents,
  __getLastWatcher,
  Uri,
} from "./__mocks__/vscode";
import { readFileSync } from "fs";
import { join } from "path";

const VALID_PROGRESS = readFileSync(
  join(__dirname, "fixtures", "valid-progress.json"),
  "utf-8",
);

describe("progressData", () => {
  beforeEach(() => {
    disposeProgressData();
    __clearFileContents();
    __setWorkspaceFolders([
      { uri: Uri.file("/mock/workspace"), name: "workspace", index: 0 },
    ]);
  });

  afterEach(() => {
    disposeProgressData();
    __clearFileContents();
  });

  describe("getProgressJsonUri", () => {
    it("returns the progress.json URI within the workspace", () => {
      const uri = getProgressJsonUri();
      expect(uri).toBeDefined();
      expect(uri!.path).toBe(
        "/mock/workspace/.codebase-guide/progress.json",
      );
    });

    it("returns undefined when no workspace is open", () => {
      __setWorkspaceFolders(undefined);
      const uri = getProgressJsonUri();
      expect(uri).toBeUndefined();
    });

    it("returns undefined when workspace folders array is empty", () => {
      __setWorkspaceFolders([]);
      const uri = getProgressJsonUri();
      expect(uri).toBeUndefined();
    });
  });

  describe("loadProgressData", () => {
    it("loads and parses valid progress.json", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      const data = await loadProgressData();
      expect(data).toBeDefined();
      expect(data!.version).toBe("1.0.0");
      expect(data!.files["src/config.ts"].status).toBe("confirmed");
      expect(data!.files["src/models/user.ts"].status).toBe("flagged");
    });

    it("stores loaded data accessible via getProgressData", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      expect(getProgressData()).toBeUndefined();
      await loadProgressData();
      expect(getProgressData()).toBeDefined();
      expect(getProgressData()!.stats.confirmed).toBe(1);
    });

    it("returns undefined when no workspace is open", async () => {
      __setWorkspaceFolders(undefined);
      const data = await loadProgressData();
      expect(data).toBeUndefined();
    });

    it("returns undefined when progress.json does not exist", async () => {
      const data = await loadProgressData();
      expect(data).toBeUndefined();
    });

    it("returns undefined for invalid JSON", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        "{ not valid json",
      );
      const data = await loadProgressData();
      expect(data).toBeUndefined();
    });

    it("returns undefined for JSON missing required fields", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        JSON.stringify({ version: "1.0.0" }),
      );
      const data = await loadProgressData();
      expect(data).toBeUndefined();
    });

    it("parses file statuses correctly", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      const data = await loadProgressData();
      const configEntry = data!.files["src/config.ts"];
      expect(configEntry.status).toBe("confirmed");
      expect(configEntry.read_at).toBe("2026-04-04T10:35:00Z");

      const userEntry = data!.files["src/models/user.ts"];
      expect(userEntry.status).toBe("flagged");
      expect(userEntry.note).toBe("Complex validation logic needs second pass");
    });

    it("parses stats correctly", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      const data = await loadProgressData();
      expect(data!.stats.total).toBe(5);
      expect(data!.stats.confirmed).toBe(1);
      expect(data!.stats.flagged).toBe(1);
      expect(data!.stats.skimmed).toBe(0);
      expect(data!.stats.unread).toBe(3);
    });
  });

  describe("watchProgressJson", () => {
    it("creates a file system watcher", () => {
      const disposable = watchProgressJson();
      const watcher = __getLastWatcher();
      expect(watcher).toBeDefined();
      disposable.dispose();
    });

    it("reloads progress data when file changes", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      const disposable = watchProgressJson();
      const watcher = __getLastWatcher()!;

      await watcher.__fireChange();
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(getProgressData()).toBeDefined();
      expect(getProgressData()!.stats.confirmed).toBe(1);
      disposable.dispose();
    });

    it("loads progress data when file is created", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      const disposable = watchProgressJson();
      const watcher = __getLastWatcher()!;

      await watcher.__fireCreate();
      await new Promise((resolve) => setTimeout(resolve, 10));

      expect(getProgressData()).toBeDefined();
      disposable.dispose();
    });

    it("clears progress data when file is deleted", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      await loadProgressData();
      expect(getProgressData()).toBeDefined();

      const disposable = watchProgressJson();
      const watcher = __getLastWatcher()!;

      watcher.__fireDelete();
      expect(getProgressData()).toBeUndefined();
      disposable.dispose();
    });
  });

  describe("onProgressDataChanged event", () => {
    it("fires when progress data is loaded", async () => {
      const received: unknown[] = [];
      const sub = onProgressDataChanged((data) => received.push(data));

      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      await loadProgressData();

      expect(received).toHaveLength(1);
      expect(received[0]).toBeDefined();
      sub.dispose();
    });

    it("fires with undefined when progress data is cleared", async () => {
      __setFileContent(
        "/mock/workspace/.codebase-guide/progress.json",
        VALID_PROGRESS,
      );
      await loadProgressData();

      const received: unknown[] = [];
      const sub = onProgressDataChanged((data) => received.push(data));

      const disposable = watchProgressJson();
      const watcher = __getLastWatcher()!;
      watcher.__fireDelete();

      expect(received).toHaveLength(1);
      expect(received[0]).toBeUndefined();
      sub.dispose();
      disposable.dispose();
    });
  });
});
