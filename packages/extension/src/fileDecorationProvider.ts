import * as vscode from "vscode";
import type { McpToolEvent } from "./mcpServer";

/**
 * Reading statuses for files in the codebase comprehension workflow.
 * - confirmed: Read and understood
 * - flagged: Needs a second pass
 * - skimmed: Quick read, deeper review later
 * - current: Currently being read (set by /read-next)
 */
export type FileStatus = "confirmed" | "flagged" | "skimmed";

/** Decoration config for each status. */
interface DecorationConfig {
  badge: string;
  tooltip: string;
  colorId: string;
}

const STATUS_DECORATIONS: Record<FileStatus | "current", DecorationConfig> = {
  confirmed: {
    badge: "\u2713",
    tooltip: "Read and understood",
    colorId: "noLongerVibe.confirmed",
  },
  flagged: {
    badge: "!",
    tooltip: "Flagged \u2014 needs second pass",
    colorId: "noLongerVibe.flagged",
  },
  skimmed: {
    badge: "~",
    tooltip: "Skimmed \u2014 deeper review later",
    colorId: "noLongerVibe.skimmed",
  },
  current: {
    badge: "\u25B8",
    tooltip: "Currently reading",
    colorId: "noLongerVibe.current",
  },
};

/**
 * FileDecorationProvider that color-codes files in the VS Code explorer
 * based on their reading status.
 *
 * Statuses:
 * | Status    | Badge | Tooltip                        |
 * |-----------|-------|--------------------------------|
 * | confirmed | checkmark | "Read and understood"          |
 * | flagged   | !     | "Flagged -- needs second pass" |
 * | current   | triangle  | "Currently reading"            |
 * | skimmed   | ~     | "Skimmed -- deeper review later"|
 * | unread    | --    | (no decoration)                |
 */
export class FileStatusDecorationProvider
  implements vscode.FileDecorationProvider
{
  private readonly _onDidChangeFileDecorations =
    new vscode.EventEmitter<vscode.Uri | undefined>();
  readonly onDidChangeFileDecorations = this._onDidChangeFileDecorations.event;

  /** Maps relative file paths to their reading status. */
  private readonly statuses = new Map<string, FileStatus>();

  /** The file currently being read (set by /read-next, cleared on next). */
  private currentFile: string | undefined;

  /** Workspace root path, used to resolve relative paths. */
  private readonly workspaceRoot: string;

  constructor(workspaceRoot: string) {
    this.workspaceRoot = workspaceRoot;
  }

  /**
   * Provides a FileDecoration for the given URI, or undefined if the file
   * has no status (unread).
   */
  provideFileDecoration(
    uri: vscode.Uri,
  ): vscode.FileDecoration | undefined {
    const relativePath = this.toRelativePath(uri);
    if (relativePath === undefined) {
      return undefined;
    }

    // Current file takes priority over other statuses
    if (this.currentFile === relativePath) {
      return this.makeDecoration("current");
    }

    const status = this.statuses.get(relativePath);
    if (!status) {
      return undefined;
    }

    return this.makeDecoration(status);
  }

  /**
   * Sets the reading status for a file and fires a change event.
   */
  setFileStatus(relativePath: string, status: FileStatus): void {
    this.statuses.set(relativePath, status);
    this._onDidChangeFileDecorations.fire(this.toUri(relativePath));
  }

  /**
   * Returns the current reading status for a file, or undefined if unread.
   */
  getFileStatus(relativePath: string): FileStatus | undefined {
    return this.statuses.get(relativePath);
  }

  /**
   * Sets the currently-reading file. Fires change events for both the
   * old and new current file so their decorations update.
   */
  setCurrentFile(relativePath: string | undefined): void {
    const previousFile = this.currentFile;
    this.currentFile = relativePath;

    if (previousFile) {
      this._onDidChangeFileDecorations.fire(this.toUri(previousFile));
    }
    if (relativePath) {
      this._onDidChangeFileDecorations.fire(this.toUri(relativePath));
    }
  }

  /**
   * Clears all statuses and the current file. Fires a global change
   * event (undefined URI) to refresh all decorations.
   */
  clearAll(): void {
    this.statuses.clear();
    this.currentFile = undefined;
    this._onDidChangeFileDecorations.fire(undefined);
  }

  /**
   * Bulk-syncs file statuses from progress.json data.
   * Replaces all existing statuses with the ones from progress data,
   * preserving the currentFile. Fires a single global change event.
   */
  syncFromProgress(
    files: Record<string, { status: string; read_at: string }>,
  ): void {
    this.statuses.clear();
    for (const [path, entry] of Object.entries(files)) {
      if (this.isValidStatus(entry.status)) {
        this.statuses.set(path, entry.status as FileStatus);
      }
    }
    this._onDidChangeFileDecorations.fire(undefined);
  }

  /**
   * Subscribes to MCP tool events that affect file decorations.
   * Returns an array of Disposables for cleanup.
   */
  subscribeMcpEvents(
    toolEvent: vscode.Event<McpToolEvent>,
  ): vscode.Disposable[] {
    const disposables: vscode.Disposable[] = [];

    disposables.push(
      toolEvent((event) => {
        switch (event.tool) {
          case "mark_read":
            if (typeof event.params.path === "string") {
              this.setFileStatus(event.params.path, "confirmed");
            }
            break;
          case "mark_flagged":
            if (typeof event.params.path === "string") {
              this.setFileStatus(event.params.path, "flagged");
            }
            break;
          case "open_file":
            if (typeof event.params.path === "string") {
              this.setCurrentFile(event.params.path);
            }
            break;
          case "clear_all":
            this.clearAll();
            break;
        }
      }),
    );

    return disposables;
  }

  /**
   * Disposes the event emitter.
   */
  dispose(): void {
    this._onDidChangeFileDecorations.dispose();
  }

  // --- Private helpers ---

  private makeDecoration(
    statusOrCurrent: FileStatus | "current",
  ): vscode.FileDecoration {
    const config = STATUS_DECORATIONS[statusOrCurrent];
    const decoration = new vscode.FileDecoration(
      config.badge,
      config.tooltip,
      new vscode.ThemeColor(config.colorId),
    );
    decoration.propagate = false;
    return decoration;
  }

  private toRelativePath(uri: vscode.Uri): string | undefined {
    const filePath = uri.fsPath ?? uri.path;
    const root = this.workspaceRoot;

    if (!filePath.startsWith(root)) {
      return undefined;
    }

    // Strip root + separator
    const relative = filePath.slice(root.length);
    if (relative.startsWith("/")) {
      return relative.slice(1);
    }
    return relative;
  }

  private toUri(relativePath: string): vscode.Uri {
    const fullPath = `${this.workspaceRoot}/${relativePath}`;
    return vscode.Uri.file(fullPath);
  }

  private isValidStatus(status: string): boolean {
    return status === "confirmed" || status === "flagged" || status === "skimmed";
  }
}
