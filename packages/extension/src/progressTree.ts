import * as vscode from "vscode";
import type { CodebaseMap, LayerName, ReadingOrderEntry } from "./types";
import { isFileStatus, type FileStatus } from "./fileDecorationProvider";
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
 *   Layer (foundation, core, ...)
 *     -> Directory folders (collapsible, single-child chains collapsed)
 *       -> Files
 *         -> Exported symbols
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

  /** Cache of all tree items by id for getParent/getItemById lookups. */
  private readonly itemsById = new Map<string, vscode.TreeItem>();
  /** Maps child id -> parent id for getParent lookups. */
  private readonly parentIdMap = new Map<string, string>();
  /** Tracks which exports have been read per file (filePath -> set of export names). */
  private readonly exportsRead = new Map<string, Set<string>>();

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
   * Returns the parent of a tree item, enabling reveal() support.
   */
  getParent(element: vscode.TreeItem): vscode.TreeItem | undefined {
    const id = element.id ?? element.contextValue;
    if (!id) return undefined;
    const parentId = this.parentIdMap.get(id);
    if (!parentId) return undefined;
    return this.itemsById.get(parentId);
  }

  /**
   * Returns a cached tree item by its id string.
   */
  getItemById(id: string): vscode.TreeItem | undefined {
    return this.itemsById.get(id);
  }

  /**
   * Ensures a file tree item exists in the cache by force-building
   * its ancestor chain (layer → directories → file). This is needed
   * because items only enter the cache when getChildren() is called,
   * which normally only happens when the user expands a node.
   *
   * Returns the file item, or undefined if the file is not in the map.
   */
  ensureFileItem(relativePath: string): vscode.TreeItem | undefined {
    // Fast path: already cached
    const cached = this.itemsById.get(`file:${relativePath}`);
    if (cached) return cached;

    if (!this.mapData) return undefined;

    // Find which layer this file belongs to
    let layerName: LayerName | undefined;
    for (const [name, layer] of Object.entries(this.mapData.layers)) {
      if (layer.files.includes(relativePath)) {
        layerName = name as LayerName;
        break;
      }
    }
    if (!layerName) return undefined;

    // Ensure root items exist (layer items)
    if (this.itemsById.size === 0) {
      this.getChildren(undefined);
    }

    // Get the layer item and force-expand it
    const layerItem = this.itemsById.get(`layer:${layerName}`);
    if (!layerItem) return undefined;

    // Walk down the directory path, calling getChildren at each level
    // to populate the cache
    const parts = relativePath.split("/");
    let currentItem: vscode.TreeItem = layerItem;

    for (let i = 0; i < parts.length - 1; i++) {
      const children = this.getChildren(currentItem);
      // Find the directory child that contains our target file
      const nextDir = children.find((child) => {
        const ctx = child.contextValue ?? "";
        if (!ctx.startsWith("dir:")) return false;
        // The dir path is after "dir:<layer>:"
        const dirPath = ctx.slice(`dir:${layerName}:`.length);
        return relativePath.startsWith(dirPath + "/");
      });
      if (!nextDir) break;
      currentItem = nextDir;
    }

    // One final getChildren to populate file-level items
    this.getChildren(currentItem);

    return this.itemsById.get(`file:${relativePath}`);
  }

  /**
   * Returns child elements for the given tree item.
   * - No parent: returns layer items (root level)
   * - Layer item: returns directory/file items at the layer root
   * - Dir item: returns subdirectory/file items within that directory
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
      return this.buildDirChildren(layerName, "");
    }

    if (ctx.startsWith("dir:")) {
      // Format: "dir:<layer>:<dirPath>"
      const rest = ctx.slice("dir:".length);
      const sepIdx = rest.indexOf(":");
      const layerName = rest.slice(0, sepIdx) as LayerName;
      const dirPath = rest.slice(sepIdx + 1);
      return this.buildDirChildren(layerName, dirPath);
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
   * Bulk-syncs file statuses from progress.json data.
   * Replaces all existing statuses with the ones from progress data,
   * preserving the currentFile. Also syncs exports_read data.
   * Fires a single tree refresh.
   */
  syncFromProgress(
    files: Record<string, { status: string; read_at: string; exports_read?: Record<string, { read_at: string; summary?: string | null }> }>,
  ): void {
    this.fileStatuses.clear();
    this.exportsRead.clear();
    for (const [path, entry] of Object.entries(files)) {
      if (isFileStatus(entry.status)) {
        this.fileStatuses.set(path, entry.status);
      }
      if (entry.exports_read) {
        this.exportsRead.set(path, new Set(Object.keys(entry.exports_read)));
      }
    }
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
    // Clear parent tracking caches — buildLayerItems is the root call
    this.itemsById.clear();
    this.parentIdMap.clear();

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
      item.id = `layer:${layerName}`;
      item.contextValue = `layer:${layerName}`;
      item.tooltip = layer.description;

      this.itemsById.set(item.id, item);
      items.push(item);
    }

    return items;
  }

  /**
   * Builds directory and file tree items for a given layer at a given
   * directory prefix. Returns subdirectory nodes and file nodes that
   * are direct children of the prefix.
   *
   * Single-child directory chains are collapsed: if a directory only
   * contains one subdirectory (and no files), they merge into a single
   * node label like "agents/gap_finder".
   */
  private buildDirChildren(
    layerName: LayerName,
    dirPrefix: string,
  ): vscode.TreeItem[] {
    const layer = this.mapData?.layers[layerName];
    if (!layer) {
      return [];
    }

    // Collect files that live under this dirPrefix
    const filesUnder = dirPrefix
      ? layer.files.filter((f) => f.startsWith(dirPrefix + "/"))
      : layer.files;

    // Build a single-level grouping: immediate subdirs and direct files
    const subdirs = new Map<string, string[]>();
    const directFiles: string[] = [];

    for (const filePath of filesUnder) {
      const remainder = dirPrefix ? filePath.slice(dirPrefix.length + 1) : filePath;
      const slashIdx = remainder.indexOf("/");

      if (slashIdx === -1) {
        // Direct file at this level
        directFiles.push(filePath);
      } else {
        // File is in a subdirectory
        const subdir = remainder.slice(0, slashIdx);
        const fullSubdir = dirPrefix ? `${dirPrefix}/${subdir}` : subdir;
        if (!subdirs.has(fullSubdir)) {
          subdirs.set(fullSubdir, []);
        }
        subdirs.get(fullSubdir)!.push(filePath);
      }
    }

    const items: vscode.TreeItem[] = [];

    // Build subdirectory items (sorted)
    const sortedSubdirs = [...subdirs.entries()].sort(([a], [b]) => a.localeCompare(b));
    for (const [subdirPath, subdirFiles] of sortedSubdirs) {
      // Collapse single-child directory chains
      const { label, resolvedPath } = this.collapseDirChain(
        layerName,
        subdirPath,
        subdirFiles,
      );

      const item = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.Collapsed);
      item.id = `dir:${layerName}:${resolvedPath}`;
      item.contextValue = `dir:${layerName}:${resolvedPath}`;
      item.iconPath = new vscode.ThemeIcon("folder");
      item.tooltip = resolvedPath;

      // Determine parent id for this directory item
      const parentId = dirPrefix
        ? `dir:${layerName}:${dirPrefix}`
        : `layer:${layerName}`;
      this.itemsById.set(item.id!, item);
      this.parentIdMap.set(item.id!, parentId);

      items.push(item);
    }

    // Build file items (sorted by basename)
    const sortedFiles = [...directFiles].sort((a, b) => {
      const aName = a.split("/").pop() ?? a;
      const bName = b.split("/").pop() ?? b;
      return aName.localeCompare(bName);
    });

    for (const filePath of sortedFiles) {
      const entry = this.findReadingOrderEntry(filePath);
      const basename = filePath.split("/").pop() ?? filePath;

      const hasExports = entry !== undefined && entry.exports.length > 0;
      const collapsibleState = hasExports
        ? vscode.TreeItemCollapsibleState.Collapsed
        : vscode.TreeItemCollapsibleState.None;

      const item = new vscode.TreeItem(basename, collapsibleState);
      item.id = `file:${filePath}`;
      item.contextValue = `file:${filePath}`;
      item.iconPath = this.getFileIcon(filePath);
      item.command = {
        command: "vscode.open",
        title: "Open File",
        arguments: [vscode.Uri.file(`${this.workspaceRoot}/${filePath}`)],
      };

      // Add partial export progress description
      if (hasExports && entry) {
        const readExports = this.exportsRead.get(filePath);
        if (readExports && readExports.size > 0) {
          const readCount = readExports.size;
          const totalExports = entry.exports.length;
          item.description = `(${String(readCount)}/${String(totalExports)})`;
          // If some exports read but file not fully marked, show partial icon
          if (!this.fileStatuses.has(filePath) && readCount < totalExports) {
            item.iconPath = new vscode.ThemeIcon("circle-slash");
          }
        }
      }

      // Determine parent id for this file item
      const parentId = dirPrefix
        ? `dir:${layerName}:${dirPrefix}`
        : `layer:${layerName}`;
      this.itemsById.set(item.id!, item);
      this.parentIdMap.set(item.id!, parentId);

      items.push(item);
    }

    return items;
  }

  /**
   * Collapse single-child directory chains. If a directory has only
   * subdirectories (no direct files) and exactly one subdirectory,
   * merge them into a combined label: "agents/gap_finder".
   *
   * Returns the display label and the resolved full path.
   */
  private collapseDirChain(
    layerName: LayerName,
    dirPath: string,
    filesInDir: string[],
  ): { label: string; resolvedPath: string } {
    let currentPath = dirPath;
    let displayLabel = dirPath.split("/").pop() ?? dirPath;

    // Keep collapsing while the directory has only subdirs (no direct files)
    // and exactly one subdirectory
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const directFiles: string[] = [];
      const childDirs = new Set<string>();

      for (const f of filesInDir) {
        const remainder = f.slice(currentPath.length + 1);
        const slashIdx = remainder.indexOf("/");
        if (slashIdx === -1) {
          directFiles.push(f);
        } else {
          const subdir = remainder.slice(0, slashIdx);
          childDirs.add(subdir);
        }
      }

      // Can only collapse if: no direct files AND exactly one child dir
      if (directFiles.length > 0 || childDirs.size !== 1) {
        break;
      }

      const onlyChild = [...childDirs][0];
      currentPath = `${currentPath}/${onlyChild}`;
      displayLabel = `${displayLabel}/${onlyChild}`;
    }

    return { label: displayLabel, resolvedPath: currentPath };
  }

  /**
   * Builds export/symbol tree items for a given file.
   */
  private buildExportItems(filePath: string): vscode.TreeItem[] {
    const entry = this.findReadingOrderEntry(filePath);
    if (!entry) {
      return [];
    }

    const readExports = this.exportsRead.get(filePath);

    return entry.exports.map((exportName) => {
      const item = new vscode.TreeItem(exportName, vscode.TreeItemCollapsibleState.None);
      item.id = `export:${filePath}:${exportName}`;
      item.contextValue = `export:${filePath}:${exportName}`;

      if (readExports?.has(exportName)) {
        const config = STATUS_ICONS.confirmed;
        item.iconPath = new vscode.ThemeIcon(
          config.id,
          config.colorId ? new vscode.ThemeColor(config.colorId) : undefined,
        );
      } else {
        item.iconPath = new vscode.ThemeIcon("circle-outline");
      }

      // Register in parent tracking
      const parentId = `file:${filePath}`;
      this.itemsById.set(item.id!, item);
      this.parentIdMap.set(item.id!, parentId);

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
