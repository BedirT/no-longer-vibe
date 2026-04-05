import * as vscode from "vscode";
import type { CodebaseMap } from "./types";

/** Event fired when map data changes (loaded, updated, or cleared). */
const mapDataChangedEmitter = new vscode.EventEmitter<
  CodebaseMap | undefined
>();

/**
 * Event that fires whenever the in-memory map data is updated.
 * Subscribers receive the new map data, or undefined if cleared.
 */
export const onMapDataChanged: vscode.Event<CodebaseMap | undefined> =
  mapDataChangedEmitter.event;

/** In-memory store for the parsed map.json data. */
let currentMap: CodebaseMap | undefined;

/** FileSystemWatcher for .codebase-guide/map.json changes. */
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
 * Returns the current in-memory map data, or undefined if not loaded.
 */
export function getMapData(): CodebaseMap | undefined {
  return currentMap;
}

/**
 * Finds the map.json URI within the first workspace folder.
 * Returns undefined if no workspace is open.
 */
export function getMapJsonUri(): vscode.Uri | undefined {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    return undefined;
  }
  return vscode.Uri.joinPath(
    workspaceFolders[0].uri,
    ".codebase-guide",
    "map.json",
  );
}

/**
 * Reads and parses map.json from the workspace.
 * Updates the in-memory store and fires the change event.
 * Returns the parsed data, or undefined on failure.
 */
export async function loadMapData(): Promise<CodebaseMap | undefined> {
  const uri = getMapJsonUri();
  if (!uri) {
    log("No workspace folder found; cannot load map.json");
    return undefined;
  }

  try {
    const raw = await vscode.workspace.fs.readFile(uri);
    const text = Buffer.from(raw).toString("utf-8");
    const data = JSON.parse(text) as CodebaseMap;

    // Basic structural validation
    if (!data.version || !data.reading_order || !data.dependency_graph) {
      log("map.json is missing required fields");
      return undefined;
    }

    currentMap = data;
    mapDataChangedEmitter.fire(currentMap);
    log(
      `Loaded map.json: ${data.total_files} files, version ${data.version}`,
    );
    return currentMap;
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    log(`Failed to load map.json: ${message}`);
    return undefined;
  }
}

/**
 * Creates a FileSystemWatcher for map.json and reloads on changes.
 * Returns a Disposable that cleans up the watcher.
 */
export function watchMapJson(): vscode.Disposable {
  if (watcher) {
    watcher.dispose();
  }

  const pattern = new vscode.RelativePattern(
    vscode.workspace.workspaceFolders![0],
    ".codebase-guide/map.json",
  );

  watcher = vscode.workspace.createFileSystemWatcher(pattern);

  watcher.onDidChange(async () => {
    log("map.json changed, reloading...");
    await loadMapData();
  });

  watcher.onDidCreate(async () => {
    log("map.json created, loading...");
    await loadMapData();
  });

  watcher.onDidDelete(() => {
    log("map.json deleted, clearing map data");
    currentMap = undefined;
    mapDataChangedEmitter.fire(undefined);
  });

  return new vscode.Disposable(() => {
    watcher?.dispose();
    watcher = undefined;
  });
}

/**
 * Disposes all resources (watcher, output channel, event emitter).
 */
export function dispose(): void {
  watcher?.dispose();
  watcher = undefined;
  outputChannel?.dispose();
  outputChannel = undefined;
  mapDataChangedEmitter.dispose();
  currentMap = undefined;
}
