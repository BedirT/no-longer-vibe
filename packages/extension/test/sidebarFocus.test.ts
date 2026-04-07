import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import { activate } from "../src/extension";
import {
  __setWorkspaceFolders,
  __setFileContent,
  __clearFileContents,
  __getLastTreeView,
  __resetTreeView,
  __fireActiveEditorChange,
  Uri,
} from "./__mocks__/vscode";
import { dispose } from "../src/mapData";
import { readFileSync } from "fs";
import { join } from "path";

const VALID_MAP = readFileSync(
  join(__dirname, "fixtures", "valid-map.json"),
  "utf-8",
);

const VALID_PROGRESS = readFileSync(
  join(__dirname, "fixtures", "valid-progress.json"),
  "utf-8",
);

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

function createMockEditor(filePath: string) {
  return {
    document: {
      uri: Uri.file(filePath),
      fileName: filePath,
    },
  };
}

describe("sidebar focus stealing (BED-149)", () => {
  beforeEach(() => {
    dispose();
    __clearFileContents();
    __resetTreeView();
    __setWorkspaceFolders([
      { uri: Uri.file("/mock/workspace"), name: "workspace", index: 0 },
    ]);
  });

  afterEach(() => {
    dispose();
    __clearFileContents();
    __resetTreeView();
  });

  it("does NOT call reveal() when tree view is not visible", async () => {
    __setFileContent("/mock/workspace/.codebase-guide/map.json", VALID_MAP);
    __setFileContent(
      "/mock/workspace/.codebase-guide/progress.json",
      VALID_PROGRESS,
    );

    const ctx = createMockContext();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await activate(ctx as any);

    const treeView = __getLastTreeView();
    expect(treeView).toBeDefined();

    // Tree view is NOT visible (default: false)
    treeView!.visible = false;

    // Simulate switching to a file that exists in the map
    const editor = createMockEditor("/mock/workspace/src/config.ts");
    __fireActiveEditorChange(editor);

    // reveal() should NOT have been called — sidebar is not visible
    expect(treeView!.reveal).not.toHaveBeenCalled();
  });

  it("calls reveal() when tree view IS visible", async () => {
    __setFileContent("/mock/workspace/.codebase-guide/map.json", VALID_MAP);
    __setFileContent(
      "/mock/workspace/.codebase-guide/progress.json",
      VALID_PROGRESS,
    );

    const ctx = createMockContext();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await activate(ctx as any);

    const treeView = __getLastTreeView();
    expect(treeView).toBeDefined();

    // Tree view IS visible
    treeView!.visible = true;

    const editor = createMockEditor("/mock/workspace/src/config.ts");
    __fireActiveEditorChange(editor);

    // reveal() SHOULD be called — user is already looking at the sidebar
    expect(treeView!.reveal).toHaveBeenCalled();
  });

  it("does not call reveal() for files outside the workspace", async () => {
    __setFileContent("/mock/workspace/.codebase-guide/map.json", VALID_MAP);
    __setFileContent(
      "/mock/workspace/.codebase-guide/progress.json",
      VALID_PROGRESS,
    );

    const ctx = createMockContext();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    await activate(ctx as any);

    const treeView = __getLastTreeView();
    expect(treeView).toBeDefined();
    treeView!.visible = true;

    // File is outside the workspace
    const editor = createMockEditor("/some/other/path/file.ts");
    __fireActiveEditorChange(editor);

    expect(treeView!.reveal).not.toHaveBeenCalled();
  });
});
