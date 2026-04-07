import * as vscode from "vscode";
import { BlastRadiusProvider } from "./blastRadius";
import { CallerCountProvider } from "./callerCount";
import { CodeLensProvider } from "./codeLensProvider";
import { dispose, loadMapData, onMapDataChanged, watchMapJson } from "./mapData";
import {
  dispose as disposeProgress,
  loadProgressData,
  onProgressDataChanged,
  updateExportStatus,
  updateFileStatus,
  watchProgressJson,
} from "./progressData";
import { FileStatusDecorationProvider } from "./fileDecorationProvider";
import { openFile } from "./fileOpener";
import { HighlightManager } from "./highlightManager";
import { getSocketPath } from "./ipcProtocol";
import { IpcBridgeServer } from "./ipcServer";
import { createMcpServer } from "./mcpServer";
import { ProgressTreeProvider } from "./progressTree";

/**
 * Called by VS Code when the extension activates.
 * Activation event: workspaceContains:.codebase-guide/map.json
 */
export async function activate(
  context: vscode.ExtensionContext,
): Promise<void> {
  const outputChannel = vscode.window.createOutputChannel("No Longer Vibe");
  context.subscriptions.push(outputChannel);
  outputChannel.appendLine("No Longer Vibe extension activating...");

  // Load map.json on activation
  const mapData = await loadMapData();
  if (mapData) {
    outputChannel.appendLine(
      `Loaded codebase map: ${mapData.total_files} files across ${Object.keys(mapData.layers).length} layers`,
    );
  } else {
    outputChannel.appendLine(
      "No map.json found or failed to parse. Run /read-index to generate it.",
    );
  }

  // Watch for map.json changes
  const watcherDisposable = watchMapJson();
  context.subscriptions.push(watcherDisposable);

  // Load progress.json on activation
  const progressData = await loadProgressData();
  if (progressData) {
    outputChannel.appendLine(
      `Loaded progress: ${String(progressData.stats.confirmed)} confirmed, ${String(progressData.stats.flagged)} flagged, ${String(progressData.stats.unread)} unread`,
    );
  }

  // Watch for progress.json changes
  const progressWatcherDisposable = watchProgressJson();
  context.subscriptions.push(progressWatcherDisposable);

  // Set up caller count gutter decorations
  const callerCountProvider = new CallerCountProvider();
  context.subscriptions.push({ dispose: () => callerCountProvider.dispose() });

  // Set up CodeLens provider for caller/callee annotations
  const codeLensProvider = new CodeLensProvider();
  context.subscriptions.push(
    vscode.languages.registerCodeLensProvider({ scheme: "file" }, codeLensProvider),
  );
  context.subscriptions.push({ dispose: () => codeLensProvider.dispose() });

  if (mapData) {
    callerCountProvider.updateMapData(mapData);
    codeLensProvider.updateMapData(mapData);
  }

  // Re-apply decorations when map data changes
  const mapDataSub = onMapDataChanged((data) => {
    callerCountProvider.updateMapData(data);
    codeLensProvider.updateMapData(data);
  });
  context.subscriptions.push(mapDataSub);

  // Re-apply caller count decorations when active editor changes
  const editorSub = vscode.window.onDidChangeActiveTextEditor((editor) => {
    if (editor) {
      callerCountProvider.updateDecorations(editor);
    }
  });
  context.subscriptions.push(editorSub);

  // Register the navigate-to-caller command for CodeLens clicks
  const navigateCmd = vscode.commands.registerCommand(
    "noLongerVibe.navigateToCaller",
    async (filePath?: string) => {
      if (!filePath) {
        return;
      }
      const uri = vscode.Uri.file(filePath);
      await vscode.commands.executeCommand("vscode.open", uri);
    },
  );
  context.subscriptions.push(navigateCmd);

  // Register FileDecorationProvider for file status colors
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (workspaceFolders && workspaceFolders.length > 0) {
    const workspaceRoot = workspaceFolders[0].uri.fsPath;
    const decorationProvider = new FileStatusDecorationProvider(workspaceRoot);

    context.subscriptions.push(
      vscode.window.registerFileDecorationProvider(decorationProvider),
    );
    context.subscriptions.push(decorationProvider);

    // Register blast radius provider for explorer decorations
    const blastRadiusProvider = new BlastRadiusProvider(workspaceRoot);
    context.subscriptions.push(
      vscode.window.registerFileDecorationProvider(blastRadiusProvider),
    );
    context.subscriptions.push(blastRadiusProvider);

    if (mapData) {
      blastRadiusProvider.updateMapData(mapData);
    }

    // Subscribe to MCP tool events for decoration and CodeLens updates
    const { toolEvents } = createMcpServer();
    const mcpDisposables = decorationProvider.subscribeMcpEvents(
      toolEvents.event,
    );
    for (const d of mcpDisposables) {
      context.subscriptions.push(d);
    }

    // Subscribe blast radius provider to MCP events
    const blastRadiusMcpDisposables = blastRadiusProvider.subscribeMcpEvents(
      toolEvents.event,
    );
    for (const d of blastRadiusMcpDisposables) {
      context.subscriptions.push(d);
    }

    // Wire open_file events to actually open the file in the editor
    const openFileSub = toolEvents.event((event) => {
      if (event.tool === "open_file" && typeof event.params.path === "string") {
        const filePath = event.params.path;
        const absolutePath = filePath.startsWith("/")
          ? filePath
          : `${workspaceRoot}/${filePath}`;
        const line =
          typeof event.params.line === "number"
            ? event.params.line
            : undefined;
        openFile(absolutePath, line);
      }
    });
    context.subscriptions.push(openFileSub);

    // Set up highlight manager for highlight_range, clear_highlights, clear_all
    const highlightManager = new HighlightManager(toolEvents.event);
    context.subscriptions.push({ dispose: () => highlightManager.dispose() });

    // Wire MCP set_codelens events to the CodeLens provider
    const codeLensMcpSub = toolEvents.event((event) => {
      if (event.tool === "set_codelens") {
        const file = event.params.file as string;
        const entries = event.params.entries as Array<{
          line: number;
          text: string;
          command?: string;
        }>;
        codeLensProvider.setMcpOverrides(file, entries);
      }
    });
    context.subscriptions.push(codeLensMcpSub);

    // Register progress tree sidebar view
    const progressTree = new ProgressTreeProvider(workspaceRoot);
    const progressTreeView = vscode.window.createTreeView("nlv.progressTree", {
      treeDataProvider: progressTree,
    });
    context.subscriptions.push(progressTreeView);
    context.subscriptions.push({ dispose: () => progressTree.dispose() });

    // Auto-reveal opened files in the progress tree
    const revealSub = vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (!editor) return;
      const filePath = editor.document.uri.fsPath;
      if (!filePath.startsWith(workspaceRoot)) return;
      const relativePath = filePath.slice(workspaceRoot.length + 1);
      const item = progressTree.ensureFileItem(relativePath);
      if (item) {
        progressTreeView.reveal(item, { select: true, focus: false, expand: true }).then(
          undefined,
          () => { /* ignore reveal errors (e.g. tree not visible) */ },
        );
      }
    });
    context.subscriptions.push(revealSub);

    if (mapData) {
      progressTree.updateMapData(mapData);
    }

    // Subscribe progress tree to MCP events
    const progressTreeMcpDisposables = progressTree.subscribeMcpEvents(
      toolEvents.event,
    );
    for (const d of progressTreeMcpDisposables) {
      context.subscriptions.push(d);
    }

    // Register manual marking commands (right-click context menu)
    for (const [cmd, status] of [
      ["nlv.markConfirmed", "confirmed"],
      ["nlv.markFlagged", "flagged"],
      ["nlv.markSkimmed", "skimmed"],
    ] as const) {
      const disposable = vscode.commands.registerCommand(
        cmd,
        async (item?: vscode.TreeItem) => {
          const ctx = item?.contextValue ?? "";
          if (!ctx.startsWith("file:")) return;
          const filePath = ctx.slice("file:".length);
          await updateFileStatus(filePath, status);
        },
      );
      context.subscriptions.push(disposable);
    }

    // Register export marking command (right-click on export node)
    const markExportCmd = vscode.commands.registerCommand(
      "nlv.markExportRead",
      async (item?: vscode.TreeItem) => {
        const ctx = item?.contextValue ?? "";
        if (!ctx.startsWith("export:")) return;
        // contextValue format: "export:<filePath>:<exportName>"
        const rest = ctx.slice("export:".length);
        const lastColon = rest.lastIndexOf(":");
        if (lastColon === -1) return;
        const filePath = rest.slice(0, lastColon);
        const exportName = rest.slice(lastColon + 1);
        await updateExportStatus(filePath, exportName);
        // Clear any agent highlights on this file
        highlightManager.clearHighlightsForFile(filePath);
      },
    );
    context.subscriptions.push(markExportCmd);

    // Populate initial progress state from progress.json
    if (progressData) {
      decorationProvider.syncFromProgress(progressData.files);
      progressTree.syncFromProgress(progressData.files);
    }

    // Subscribe to progress.json filesystem changes
    const progressDataSub = onProgressDataChanged((data) => {
      if (data) {
        decorationProvider.syncFromProgress(data.files);
        progressTree.syncFromProgress(data.files);
      } else {
        decorationProvider.clearAll();
        progressTree.clearAll();
      }
    });
    context.subscriptions.push(progressDataSub);

    // Refresh progress tree and blast radius when map data changes
    const progressTreeMapSub = onMapDataChanged((data) => {
      progressTree.updateMapData(data);
      blastRadiusProvider.updateMapData(data);
    });
    context.subscriptions.push(progressTreeMapSub);

    outputChannel.appendLine("File decoration provider registered.");
    outputChannel.appendLine("Blast radius provider registered.");
    outputChannel.appendLine("Progress tree view registered.");

    // Start IPC bridge server so the standalone MCP server can forward
    // visual tool calls to this extension process.
    const socketPath = getSocketPath(workspaceRoot);
    const ipcServer = new IpcBridgeServer(
      socketPath,
      async (tool: string, params: Record<string, unknown>) => {
        toolEvents.fire({ tool, params });
        return {
          content: [
            {
              type: "text",
              text: `[via extension] ${tool} executed`,
            },
          ],
        };
      },
    );
    ipcServer
      .start()
      .then(() => {
        outputChannel.appendLine(
          `IPC bridge server listening on ${socketPath}`,
        );
      })
      .catch((err: unknown) => {
        outputChannel.appendLine(
          `IPC bridge server failed to start: ${err instanceof Error ? err.message : String(err)}`,
        );
      });
    context.subscriptions.push({
      dispose: () => {
        ipcServer.stop();
      },
    });
  }

  outputChannel.appendLine("CodeLens provider registered.");
  outputChannel.appendLine("No Longer Vibe extension activated.");
}

/**
 * Called by VS Code when the extension deactivates.
 */
export function deactivate(): void {
  dispose();
  disposeProgress();
}
