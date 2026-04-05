/**
 * Mock implementation of the vscode module for unit tests.
 * Provides minimal stubs for the VS Code APIs used by the extension.
 */

import { vi } from "vitest";

export class Uri {
  readonly scheme: string;
  readonly path: string;
  readonly fsPath: string;

  private constructor(scheme: string, path: string) {
    this.scheme = scheme;
    this.path = path;
    this.fsPath = path;
  }

  static file(path: string): Uri {
    return new Uri("file", path);
  }

  static joinPath(base: Uri, ...pathSegments: string[]): Uri {
    const joined = [base.path, ...pathSegments].join("/");
    return new Uri(base.scheme, joined);
  }

  toString(): string {
    return `${this.scheme}://${this.path}`;
  }
}

export class Disposable {
  private disposeFunc: () => void;

  constructor(callOnDispose: () => void) {
    this.disposeFunc = callOnDispose;
  }

  dispose(): void {
    this.disposeFunc();
  }
}

export class EventEmitter<T> {
  private listeners: Array<(e: T) => void> = [];

  get event(): (listener: (e: T) => void) => Disposable {
    return (listener: (e: T) => void): Disposable => {
      this.listeners.push(listener);
      return new Disposable(() => {
        const index = this.listeners.indexOf(listener);
        if (index >= 0) {
          this.listeners.splice(index, 1);
        }
      });
    };
  }

  fire(data: T): void {
    for (const listener of this.listeners) {
      listener(data);
    }
  }

  dispose(): void {
    this.listeners = [];
  }
}

class MockOutputChannel {
  name: string;
  lines: string[] = [];

  constructor(name: string) {
    this.name = name;
  }

  appendLine(line: string): void {
    this.lines.push(line);
  }

  append(_value: string): void {
    // noop
  }

  clear(): void {
    this.lines = [];
  }

  show(): void {
    // noop
  }

  hide(): void {
    // noop
  }

  dispose(): void {
    this.lines = [];
  }
}

/** Mock workspace state */
let mockWorkspaceFolders: Array<{ uri: Uri; name: string; index: number }> | undefined = [
  { uri: Uri.file("/mock/workspace"), name: "workspace", index: 0 },
];

let mockFileContents: Map<string, Uint8Array> = new Map();

/** Configures mock workspace folders for testing. */
export function __setWorkspaceFolders(
  folders: Array<{ uri: Uri; name: string; index: number }> | undefined,
): void {
  mockWorkspaceFolders = folders;
}

/** Sets the content that readFile will return for a given URI path. */
export function __setFileContent(uriPath: string, content: string): void {
  mockFileContents.set(uriPath, new TextEncoder().encode(content));
}

/** Clears all mock file contents. */
export function __clearFileContents(): void {
  mockFileContents.clear();
}

/** Mock watcher created by createFileSystemWatcher. */
export class MockFileSystemWatcher {
  onDidChange: (listener: () => void) => Disposable;
  onDidCreate: (listener: () => void) => Disposable;
  onDidDelete: (listener: () => void) => Disposable;

  private changeEmitter = new EventEmitter<void>();
  private createEmitter = new EventEmitter<void>();
  private deleteEmitter = new EventEmitter<void>();

  constructor() {
    this.onDidChange = this.changeEmitter.event;
    this.onDidCreate = this.createEmitter.event;
    this.onDidDelete = this.deleteEmitter.event;
  }

  /** Simulate a file change event */
  __fireChange(): void {
    this.changeEmitter.fire();
  }

  /** Simulate a file create event */
  __fireCreate(): void {
    this.createEmitter.fire();
  }

  /** Simulate a file delete event */
  __fireDelete(): void {
    this.deleteEmitter.fire();
  }

  dispose(): void {
    this.changeEmitter.dispose();
    this.createEmitter.dispose();
    this.deleteEmitter.dispose();
  }
}

let lastCreatedWatcher: MockFileSystemWatcher | undefined;

/** Returns the most recently created mock watcher for test assertions. */
export function __getLastWatcher(): MockFileSystemWatcher | undefined {
  return lastCreatedWatcher;
}

export class ThemeColor {
  readonly id: string;

  constructor(id: string) {
    this.id = id;
  }
}

/** Mock FileDecoration matching the vscode.FileDecoration interface. */
export class FileDecoration {
  badge?: string;
  tooltip?: string;
  color?: ThemeColor;
  propagate?: boolean;

  constructor(badge?: string, tooltip?: string, color?: ThemeColor) {
    this.badge = badge;
    this.tooltip = tooltip;
    this.color = color;
  }
}

export class RelativePattern {
  constructor(
    public base: { uri: Uri } | Uri | string,
    public pattern: string,
  ) {}
}

export class Position {
  readonly line: number;
  readonly character: number;

  constructor(line: number, character: number) {
    this.line = line;
    this.character = character;
  }
}

export class Selection {
  readonly anchor: Position;
  readonly active: Position;

  constructor(anchor: Position, active: Position) {
    this.anchor = anchor;
    this.active = active;
  }
}

export class Range {
  readonly start: Position;
  readonly end: Position;

  constructor(start: Position, end: Position) {
    this.start = start;
    this.end = end;
  }
}

export enum TextEditorRevealType {
  Default = 0,
  InCenter = 1,
  InCenterIfOutsideViewport = 2,
  AtTop = 3,
}

/** Mock editor tracking for test assertions. */
interface MockEditorRecord {
  selection: Selection | undefined;
  revealRangeCalls: Array<{ range: Range; revealType: TextEditorRevealType }>;
}

let lastMockEditor: MockEditorRecord | undefined;

/** Returns the last editor created by showTextDocument. */
export function __getLastEditor(): MockEditorRecord | undefined {
  return lastMockEditor;
}

/** Resets mock editor state between tests. */
export function __resetMockEditors(): void {
  lastMockEditor = undefined;
  mockOpenTextDocumentResult = undefined;
  mockShowTextDocumentResult = undefined;
  mockShowTextDocumentShouldThrow = false;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockOpenTextDocumentResult: any;
// eslint-disable-next-line @typescript-eslint/no-explicit-any
let mockShowTextDocumentResult: any;
let mockShowTextDocumentShouldThrow = false;

/** Sets what openTextDocument will return. Pass null to make it throw. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function __setOpenTextDocumentResult(result: any): void {
  mockOpenTextDocumentResult = result;
}

/** Sets what showTextDocument will return. Pass null to make it throw. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function __setShowTextDocumentResult(result: any): void {
  if (result === null) {
    mockShowTextDocumentShouldThrow = true;
    mockShowTextDocumentResult = undefined;
  } else {
    mockShowTextDocumentShouldThrow = false;
    mockShowTextDocumentResult = result;
  }
}

export const workspace = {
  get workspaceFolders() {
    return mockWorkspaceFolders;
  },
  fs: {
    readFile: vi.fn(async (uri: Uri): Promise<Uint8Array> => {
      const content = mockFileContents.get(uri.path);
      if (!content) {
        throw new Error(`File not found: ${uri.path}`);
      }
      return content;
    }),
  },
  createFileSystemWatcher: vi.fn((): MockFileSystemWatcher => {
    lastCreatedWatcher = new MockFileSystemWatcher();
    return lastCreatedWatcher;
  }),
  openTextDocument: vi.fn(async (uri: Uri) => {
    if (mockOpenTextDocumentResult === null) {
      throw new Error(`File not found: ${uri.fsPath}`);
    }
    if (mockOpenTextDocumentResult !== undefined) {
      return mockOpenTextDocumentResult;
    }
    return { uri };
  }),
};

export const window = {
  createOutputChannel: vi.fn((name: string): MockOutputChannel => {
    return new MockOutputChannel(name);
  }),
  registerFileDecorationProvider: vi.fn(
    (_provider: unknown): Disposable => {
      return new Disposable(() => {});
    },
  ),
  showTextDocument: vi.fn(async () => {
    if (mockShowTextDocumentShouldThrow) {
      throw new Error("Failed to show text document");
    }
    const editorRecord: MockEditorRecord = {
      selection: undefined,
      revealRangeCalls: [],
    };
    const editor = {
      get selection() {
        return editorRecord.selection;
      },
      set selection(sel: Selection) {
        editorRecord.selection = sel;
      },
      revealRange(range: Range, revealType?: TextEditorRevealType): void {
        editorRecord.revealRangeCalls.push({
          range,
          revealType: revealType ?? TextEditorRevealType.Default,
        });
      },
    };
    lastMockEditor = editorRecord;
    return editor;
  }),
};
