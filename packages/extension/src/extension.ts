import * as vscode from "vscode";
import { CallerCountProvider } from "./callerCount";
import { CodeLensProvider } from "./codeLensProvider";
import { dispose, loadMapData, onMapDataChanged, watchMapJson } from "./mapData";
import { FileStatusDecorationProvider } from "./fileDecorationProvider";
import { createMcpServer } from "./mcpServer";

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

    // Subscribe to MCP tool events for decoration and CodeLens updates
    const { toolEvents } = createMcpServer();
    const mcpDisposables = decorationProvider.subscribeMcpEvents(
      toolEvents.event,
    );
    for (const d of mcpDisposables) {
      context.subscriptions.push(d);
    }

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

    outputChannel.appendLine("File decoration provider registered.");
  }

  outputChannel.appendLine("CodeLens provider registered.");
  outputChannel.appendLine("No Longer Vibe extension activated.");
}

/**
 * Called by VS Code when the extension deactivates.
 */
export function deactivate(): void {
  dispose();
}
