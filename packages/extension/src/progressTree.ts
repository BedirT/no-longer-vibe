import * as vscode from "vscode";
import type { CodebaseMap, LayerName, ReadingOrderEntry } from "./types";
import type { FileStatus } from "./fileDecorationProvider";
import type { McpToolEvent } from "./mcpServer";

/** Canonical layer order as defined in the spec. */
const LAYER_ORDER: readonly LayerName[] = [
  "foundation",
  "core",
  "features",
  "integration",
  "entry",
];

/** Icon configuration for each file status. */
const STATUS_ICONS: Record<FileStatus | "current" | "unread", { id: string; colorId?: string }> = {
  confirmed: { id: "check", colorId: "noLongerVibe.confirmed" },
  flagged: { id: "warning", colorId: "noLongerVibe.flagged" },
  skimmed: { id: "eye-closed", colorId: "noLongerVibe.skimmed" },
  current: { id: "eye", colorId: "noLongerVibe.current" },
  unread: { id: "circle-outline" },
};

/**
 * TreeDataProvider that displays reading progress as a sidebar tree.
 *
 * Hierarchy:
 *   Layer (foundation, core, ...) -> Files -> Exported symbols
 *
 * Each file shows a status icon (confirmed, flagged, current, unread).
 * Layer items show progress counts: "foundation (2/5 read)".
 * Clicking a file opens it in the editor.
 */
export class ProgressTreeProvider implements vscode.TreeDataProvider<vscode.TreeItem> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<void>();
  readonly onDidChangeTreeData: vscode.Event<void> = this._onDidChangeTreeData.event;

  private mapData: CodebaseMap | undefined;
  private readonly fileStatuses = new Map<string, FileStatus>();
  private currentFile: string | undefined;
  private readonly workspaceRoot: string;

  constructor(workspaceRoot: string) {
    this.workspaceRoot = workspaceRoot;
  }

  /**
   * Returns the tree item for display. Direct passthrough since
   * we construct fully-formed TreeItems in getChildren.
   */
  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  /**
   * Returns child elements for the given tree item.
   * - No parent: returns layer items (root level)
   * - Layer item: returns file items
   * - File item: returns export/symbol items
   */
  getChildren(element?: vscode.TreeItem): vscode.TreeItem[] {
    if (!this.mapData) {
      return [];
    }

    if (!element) {
      return this.buildLayerItems();
    }

    const ctx = element.contextValue ?? "";

    if (ctx.startsWith("layer:")) {
      const layerName = ctx.slice("layer:".length) as LayerName;
      return this.buildFileItems(layerName);
    }

    if (ctx.startsWith("file:")) {
      const filePath = ctx.slice("file:".length);
      return this.buildExportItems(filePath);
    }

    return [];
  }

  /**
   * Updates the stored map data and refreshes the tree.
   */
  updateMapData(map: CodebaseMap | undefined): void {
    this.mapData = map;
    this._onDidChangeTreeData.fire();
  }

  /**
   * Sets the reading status for a file and refreshes the tree.
   */
  setFileStatus(relativePath: string, status: FileStatus): void {
    this.fileStatuses.set(relativePath, status);
    this._onDidChangeTreeData.fire();
  }

  /**
   * Sets the currently-reading file and refreshes the tree.
   */
  setCurrentFile(relativePath: string | undefined): void {
    this.currentFile = relativePath;
    this._onDidChangeTreeData.fire();
  }

  /**
   * Clears all statuses and current file, then refreshes.
   */
  clearAll(): void {
    this.fileStatuses.clear();
    this.currentFile = undefined;
    this._onDidChangeTreeData.fire();
  }

  /**
   * Forces a refresh of the tree view.
   */
  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  /**
   * Subscribes to MCP tool events that affect the progress tree.
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
          case "update_progress_tree":
            this.refresh();
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
    this._onDidChangeTreeData.dispose();
  }

  // --- Private helpers ---

  /**
   * Builds root-level tree items for each non-empty layer.
   */
  private buildLayerItems(): vscode.TreeItem[] {
    const items: vscode.TreeItem[] = [];

    for (const layerName of LAYER_ORDER) {
      const layer = this.mapData?.layers[layerName];
      if (!layer || layer.files.length === 0) {
        continue;
      }

      const readCount = this.countReadFiles(layer.files);
      const total = layer.files.length;
      const label = `${layerName} (${String(readCount)}/${String(total)} read)`;

      const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.Collapsed);
      item.contextValue = `layer:${layerName}`;
      item.tooltip = layer.description;

      items.push(item);
    }

    return items;
  }

  /**
   * Builds file-level tree items for a given layer.
   */
  private buildFileItems(layerName: LayerName): vscode.TreeItem[] {
    const layer = this.mapData?.layers[layerName];
    if (!layer) {
      return [];
    }

    return layer.files.map((filePath) => {
      const entry = this.findReadingOrderEntry(filePath);
      const basename = filePath.split("/").pop() ?? filePath;
      const dirPath = filePath.split("/").slice(0, -1).join("/");

      const hasExports = entry !== undefined && entry.exports.length > 0;
      const collapsibleState = hasExports
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None;

      const item = new vscode.TreeItem(basename, collapsibleState);
      item.contextValue = `file:${filePath}`;
      item.description = dirPath || undefined;
      item.iconPath = this.getFileIcon(filePath);
      item.command = {
        command: "vscode.open",
        title: "Open File",
        arguments: [vscode.Uri.file(`${this.workspaceRoot}/${filePath}`)],
      };

      return item;
    });
  }

  /**
   * Builds export/symbol tree items for a given file.
   */
  private buildExportItems(filePath: string): vscode.TreeItem[] {
    const entry = this.findReadingOrderEntry(filePath);
    if (!entry) {
      return [];
    }

    return entry.exports.map((exportName) => {
      const item = new vscode.TreeItem(exportName, vscode.TreeItemCollapsibleState.None);
      item.contextValue = `export:${exportName}`;
      item.iconPath = new vscode.ThemeIcon("symbol-function");
      return item;
    });
  }

  /**
   * Returns the appropriate ThemeIcon for a file based on its status.
   */
  private getFileIcon(filePath: string): vscode.ThemeIcon {
    // Current file takes priority
    if (this.currentFile === filePath) {
      const config = STATUS_ICONS.current;
      return new vscode.ThemeIcon(
        config.id,
        config.colorId ? new vscode.ThemeColor(config.colorId) : undefined,
      );
    }

    const status = this.fileStatuses.get(filePath);
    if (!status) {
      return new vscode.ThemeIcon(STATUS_ICONS.unread.id);
    }

    const config = STATUS_ICONS[status];
    return new vscode.ThemeIcon(
      config.id,
      config.colorId ? new vscode.ThemeColor(config.colorId) : undefined,
    );
  }

  /**
   * Counts files in the given list that have any non-unread status.
   */
  private countReadFiles(files: string[]): number {
    let count = 0;
    for (const filePath of files) {
      if (this.fileStatuses.has(filePath)) {
        count++;
      }
    }
    return count;
  }

  /**
   * Finds the ReadingOrderEntry for a given relative path.
   */
  private findReadingOrderEntry(
    relativePath: string,
  ): ReadingOrderEntry | undefined {
    return this.mapData?.reading_order.find(
      (entry) => entry.path === relativePath,
    );
  }
}
