import * as vscode from "vscode";
import { getMapData } from "./mapData";

/** Reading status for a single file in progress.json. */
export interface ProgressFileEntry {
  /** Expected values: "confirmed" | "flagged" | "skimmed". Validated at sync boundary via isFileStatus(). */
  status: string;
  read_at: string;
  note?: string | null;
  summary?: string | null;
  exports_read?: Record<string, { read_at: string; summary?: string | null }>;
}

/** Stats summary from progress.json. */
export interface ProgressStats {
  total: number;
  confirmed: number;
  flagged: number;
  skimmed: number;
  unread: number;
}

/** The top-level progress.json schema. */
export interface ProgressData {
  version: string;
  map_hash?: string;
  started_at?: string;
  last_session?: string;
  sessions?: number;
  files: Record<string, ProgressFileEntry>;
  stats: ProgressStats;
}

/** Event fired when progress data changes (loaded, updated, or cleared). */
const progressDataChangedEmitter = new vscode.EventEmitter<
  ProgressData | undefined
>();

/**
 * Event that fires whenever the in-memory progress data is updated.
 * Subscribers receive the new progress data, or undefined if cleared.
 */
export const onProgressDataChanged: vscode.Event<ProgressData | undefined> =
  progressDataChangedEmitter.event;

/** In-memory store for the parsed progress.json data. */
let currentProgress: ProgressData | undefined;

/** FileSystemWatcher for .codebase-guide/progress.json changes. */
let watcher: vscode.FileSystemWatcher | undefined;

/** Output channel for extension logging. */
let outputChannel: vscode.OutputChannel | undefined;

function getOutputChannel(): vscode.OutputChannel {
  if (!outputChannel) {
    outputChannel = vscode.window.createOutputChannel("No Longer Vibe");
  }
  return outputChannel;
}

function log(message: string): void {
  getOutputChannel().appendLine(`[${new Date().toISOString()}] ${message}`);
}

/**
 * Returns the current in-memory progress data, or undefined if not loaded.
 */
export function getProgressData(): ProgressData | undefined {
  return currentProgress;
}

/**
 * Finds the progress.json URI within the first workspace folder.
 * Returns undefined if no workspace is open.
 */
export function getProgressJsonUri(): vscode.Uri | undefined {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    return undefined;
  }
  return vscode.Uri.joinPath(
    workspaceFolders[0].uri,
    ".codebase-guide",
    "progress.json",
  );
}

/**
 * Reads and parses progress.json from the workspace.
 * Updates the in-memory store and fires the change event.
 * Returns the parsed data, or undefined on failure.
 */
export async function loadProgressData(): Promise<ProgressData | undefined> {
  const uri = getProgressJsonUri();
  if (!uri) {
    log("No workspace folder found; cannot load progress.json");
    return undefined;
  }

  try {
    const raw = await vscode.workspace.fs.readFile(uri);
    const text = Buffer.from(raw).toString("utf-8");
    const data = JSON.parse(text) as ProgressData;

    // Basic structural validation
    if (!data.version || !data.files || !data.stats) {
      log("progress.json is missing required fields");
      return undefined;
    }

    currentProgress = data;
    progressDataChangedEmitter.fire(currentProgress);
    log(
      `Loaded progress.json: ${String(data.stats.confirmed)} confirmed, ${String(data.stats.flagged)} flagged, ${String(data.stats.unread)} unread`,
    );
    return currentProgress;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    log(`Failed to load progress.json: ${message}`);
    return undefined;
  }
}

/**
 * Creates a FileSystemWatcher for progress.json and reloads on changes.
 * Returns a Disposable that cleans up the watcher.
 */
export function watchProgressJson(): vscode.Disposable {
  if (watcher) {
    watcher.dispose();
  }

  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    log("No workspace folder found; cannot watch progress.json");
    return new vscode.Disposable(() => {});
  }

  const pattern = new vscode.RelativePattern(
    folders[0],
    ".codebase-guide/progress.json",
  );

  watcher = vscode.workspace.createFileSystemWatcher(pattern);

  watcher.onDidChange(async () => {
    log("progress.json changed, reloading...");
    await loadProgressData();
  });

  watcher.onDidCreate(async () => {
    log("progress.json created, loading...");
    await loadProgressData();
  });

  watcher.onDidDelete(() => {
    log("progress.json deleted, clearing progress data");
    currentProgress = undefined;
    progressDataChangedEmitter.fire(undefined);
  });

  return new vscode.Disposable(() => {
    watcher?.dispose();
    watcher = undefined;
  });
}

/**
 * Updates a single file's status in progress.json on disk.
 * The FileSystemWatcher will detect the change and reload automatically.
 */
export async function updateFileStatus(
  relativePath: string,
  status: "confirmed" | "flagged" | "skimmed",
): Promise<boolean> {
  const uri = getProgressJsonUri();
  if (!uri || !currentProgress) {
    log("Cannot update file status: no progress.json loaded");
    return false;
  }

  const now = new Date().toISOString();
  const existingExportsRead = currentProgress.files[relativePath]?.exports_read;
  currentProgress.files[relativePath] = {
    status,
    read_at: now,
    note: currentProgress.files[relativePath]?.note ?? null,
    summary: currentProgress.files[relativePath]?.summary ?? null,
    exports_read: existingExportsRead,
  };

  // Cascade confirmed status to unmarked exports
  if (status === "confirmed") {
    const map = getMapData();
    if (map) {
      const entry = map.reading_order.find((e) => e.path === relativePath);
      if (entry && entry.exports.length > 0) {
        const fileEntry = currentProgress.files[relativePath];
        if (!fileEntry.exports_read) {
          fileEntry.exports_read = {};
        }
        for (const exportName of entry.exports) {
          if (!fileEntry.exports_read[exportName]) {
            fileEntry.exports_read[exportName] = { read_at: now };
          }
        }
      }
    }
  }

  // Recompute stats
  const files = currentProgress.files;
  let confirmed = 0;
  let flagged = 0;
  let skimmed = 0;
  for (const entry of Object.values(files)) {
    if (entry.status === "confirmed") confirmed++;
    else if (entry.status === "flagged") flagged++;
    else if (entry.status === "skimmed") skimmed++;
  }
  currentProgress.stats = {
    total: currentProgress.stats.total,
    confirmed,
    flagged,
    skimmed,
    unread: currentProgress.stats.total - confirmed - flagged - skimmed,
  };

  try {
    const content = JSON.stringify(currentProgress, null, 2) + "\n";
    await vscode.workspace.fs.writeFile(uri, Buffer.from(content, "utf-8"));
    log(`Updated ${relativePath} to ${status}`);
    return true;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    log(`Failed to write progress.json: ${message}`);
    return false;
  }
}

/**
 * Marks a single export as read within a file's progress entry.
 * Creates the file entry and exports_read map if they don't exist.
 * The FileSystemWatcher will detect the change and reload automatically.
 */
export async function updateExportStatus(
  relativePath: string,
  exportName: string,
): Promise<boolean> {
  const uri = getProgressJsonUri();
  if (!uri || !currentProgress) {
    log("Cannot update export status: no progress.json loaded");
    return false;
  }

  if (!currentProgress.files[relativePath]) {
    currentProgress.files[relativePath] = {
      status: "unread",
      read_at: "",
      note: null,
      summary: null,
    };
  }

  const fileEntry = currentProgress.files[relativePath];
  if (!fileEntry.exports_read) {
    fileEntry.exports_read = {};
  }
  fileEntry.exports_read[exportName] = {
    read_at: new Date().toISOString(),
    summary: null,
  };

  try {
    const content = JSON.stringify(currentProgress, null, 2) + "\n";
    await vscode.workspace.fs.writeFile(uri, Buffer.from(content, "utf-8"));
    log(`Marked export ${exportName} in ${relativePath} as read`);
    return true;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    log(`Failed to write progress.json: ${message}`);
    return false;
  }
}

/**
 * Disposes all resources (watcher, output channel, event emitter).
 */
export function dispose(): void {
  watcher?.dispose();
  watcher = undefined;
  outputChannel?.dispose();
  outputChannel = undefined;
  progressDataChangedEmitter.dispose();
  currentProgress = undefined;
}
