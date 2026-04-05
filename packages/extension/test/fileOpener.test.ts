import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import { openFile } from "../src/fileOpener";
import {
  __setOpenTextDocumentResult,
  __setShowTextDocumentResult,
  __resetMockEditors,
  __getLastEditor,
  workspace,
  window,
  Uri,
  Position,
  Selection,
  Range,
  TextEditorRevealType,
} from "./__mocks__/vscode";

describe("fileOpener", () => {
  beforeEach(() => {
    __resetMockEditors();
    vi.clearAllMocks();
  });

  describe("openFile", () => {
    it("opens a file by path", async () => {
      const mockDoc = { uri: Uri.file("/workspace/src/config.ts") };
      __setOpenTextDocumentResult(mockDoc);
      __setShowTextDocumentResult({ document: mockDoc });

      const result = await openFile("/workspace/src/config.ts");

      expect(result.success).toBe(true);
      expect(workspace.openTextDocument).toHaveBeenCalledOnce();
      expect(window.showTextDocument).toHaveBeenCalledOnce();
    });

    it("creates a URI from the given path", async () => {
      const mockDoc = { uri: Uri.file("/workspace/src/config.ts") };
      __setOpenTextDocumentResult(mockDoc);
      __setShowTextDocumentResult({ document: mockDoc });

      await openFile("/workspace/src/config.ts");

      const calledUri = (
        workspace.openTextDocument as ReturnType<typeof vi.fn>
      ).mock.calls[0][0] as Uri;
      expect(calledUri.fsPath).toBe("/workspace/src/config.ts");
    });

    it("does not set cursor or reveal when no line is given", async () => {
      const mockDoc = { uri: Uri.file("/workspace/src/config.ts") };
      __setOpenTextDocumentResult(mockDoc);
      const editor = { document: mockDoc };
      __setShowTextDocumentResult(editor);

      await openFile("/workspace/src/config.ts");

      const lastEditor = __getLastEditor();
      expect(lastEditor?.selection).toBeUndefined();
      expect(lastEditor?.revealRangeCalls).toHaveLength(0);
    });

    it("scrolls to the specified line (1-indexed)", async () => {
      const mockDoc = { uri: Uri.file("/workspace/src/config.ts") };
      __setOpenTextDocumentResult(mockDoc);
      const editor = { document: mockDoc };
      __setShowTextDocumentResult(editor);

      await openFile("/workspace/src/config.ts", 42);

      const lastEditor = __getLastEditor();
      // line 42 (1-indexed) -> Position(41, 0) (0-indexed)
      expect(lastEditor?.selection).toBeDefined();
      expect(lastEditor?.selection?.active.line).toBe(41);
      expect(lastEditor?.selection?.active.character).toBe(0);
      expect(lastEditor?.revealRangeCalls).toHaveLength(1);
      expect(lastEditor?.revealRangeCalls[0].revealType).toBe(
        TextEditorRevealType.InCenter,
      );
    });

    it("scrolls to line 1 correctly", async () => {
      const mockDoc = { uri: Uri.file("/workspace/src/config.ts") };
      __setOpenTextDocumentResult(mockDoc);
      __setShowTextDocumentResult({ document: mockDoc });

      await openFile("/workspace/src/config.ts", 1);

      const lastEditor = __getLastEditor();
      expect(lastEditor?.selection?.active.line).toBe(0);
      expect(lastEditor?.selection?.active.character).toBe(0);
    });

    it("returns failure when file is not found", async () => {
      __setOpenTextDocumentResult(null);

      const result = await openFile("/workspace/nonexistent.ts");

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
      expect(result.error).toContain("nonexistent.ts");
    });

    it("returns failure when showTextDocument throws", async () => {
      const mockDoc = { uri: Uri.file("/workspace/src/config.ts") };
      __setOpenTextDocumentResult(mockDoc);
      __setShowTextDocumentResult(null); // signals throw

      const result = await openFile("/workspace/src/config.ts");

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });

    it("returns failure for empty path", async () => {
      const result = await openFile("");

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });

    it("returns failure for line number less than 1", async () => {
      const result = await openFile("/workspace/src/config.ts", 0);

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
      expect(result.error).toContain("line");
    });

    it("returns failure for negative line number", async () => {
      const result = await openFile("/workspace/src/config.ts", -5);

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });

    it("returns failure for non-integer line number", async () => {
      const result = await openFile("/workspace/src/config.ts", 3.5);

      expect(result.success).toBe(false);
      expect(result.error).toBeDefined();
    });
  });
});
