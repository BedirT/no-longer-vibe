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

export class RelativePattern {
  constructor(
    public base: { uri: Uri } | Uri | string,
    public pattern: string,
  ) {}
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
};

export const window = {
  createOutputChannel: vi.fn((name: string): MockOutputChannel => {
    return new MockOutputChannel(name);
  }),
};
