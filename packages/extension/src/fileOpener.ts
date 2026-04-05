import * as vscode from "vscode";

/** Result of an openFile operation. */
export interface OpenFileResult {
  success: boolean;
  error?: string;
}

/**
 * Opens a file in the VS Code editor, optionally scrolling to a specific line.
 *
 * @param path - Absolute file path to open
 * @param line - Optional 1-indexed line number to scroll to and reveal
 * @returns Result indicating success or failure with error details
 */
export async function openFile(
  path: string,
  line?: number,
): Promise<OpenFileResult> {
  if (!path) {
    return { success: false, error: "Path must not be empty" };
  }

  if (line !== undefined) {
    if (!Number.isInteger(line) || line < 1) {
      return {
        success: false,
        error: `Invalid line number: ${line}. Must be a positive integer.`,
      };
    }
  }

  try {
    const uri = vscode.Uri.file(path);
    const doc = await vscode.workspace.openTextDocument(uri);
    const editor = await vscode.window.showTextDocument(doc);

    if (line !== undefined) {
      const position = new vscode.Position(line - 1, 0);
      editor.selection = new vscode.Selection(position, position);
      editor.revealRange(
        new vscode.Range(position, position),
        vscode.TextEditorRevealType.InCenter,
      );
    }

    return { success: true };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    return { success: false, error: message };
  }
}
