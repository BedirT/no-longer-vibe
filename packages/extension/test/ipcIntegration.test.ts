/**
 * Integration tests for the MCP bridge: standalone server ↔ VS Code extension.
 *
 * These tests verify the acceptance criteria from BED-96:
 * - When VS Code is open: visual tools work from Claude Code
 * - When VS Code is closed: filesystem tools still work, visual tools degrade
 */

import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";
import { IpcBridgeServer } from "../src/ipcServer";
import { IpcBridgeClient } from "../src/ipcClient";
import { createStandaloneMcpServer } from "../src/mcpStandalone";

describe("MCP bridge integration", () => {
  let tmpDir: string;
  let guideDir: string;
  let socketPath: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "nlv-bridge-test-"));
    guideDir = path.join(tmpDir, ".codebase-guide");
    fs.mkdirSync(guideDir, { recursive: true });
    socketPath = path.join(tmpDir, "bridge.sock");
  });

  afterEach(async () => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  describe("when VS Code extension is running (IPC connected)", () => {
    let server: IpcBridgeServer;
    let client: IpcBridgeClient;
    let receivedEvents: Array<{ tool: string; params: Record<string, unknown> }>;

    beforeEach(async () => {
      receivedEvents = [];
      server = new IpcBridgeServer(
        socketPath,
        async (tool, params) => {
          receivedEvents.push({ tool, params });
          return {
            content: [
              { type: "text", text: `[via extension] ${tool} executed` },
            ],
          };
        },
      );
      await server.start();

      client = new IpcBridgeClient(socketPath);
      await client.connect();
    });

    afterEach(async () => {
      client.disconnect();
      await server.stop();
    });

    it("highlight_range forwards to extension and returns extension result", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir, client);
      const result = await callTool(mcpServer, "highlight_range", {
        file: "src/main.ts",
        startLine: 10,
        endLine: 20,
        style: "focus",
      });

      expect(result.content[0].text).toContain("[via extension]");
      expect(result.content[0].text).toContain("highlight_range");
      expect(receivedEvents).toHaveLength(1);
      expect(receivedEvents[0].tool).toBe("highlight_range");
      expect(receivedEvents[0].params.file).toBe("src/main.ts");
    });

    it("clear_highlights forwards to extension", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir, client);
      const result = await callTool(mcpServer, "clear_highlights", {});

      expect(result.content[0].text).toContain("[via extension]");
      expect(receivedEvents).toHaveLength(1);
      expect(receivedEvents[0].tool).toBe("clear_highlights");
    });

    it("set_codelens forwards to extension", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir, client);
      const result = await callTool(mcpServer, "set_codelens", {
        file: "src/app.ts",
        entries: [{ line: 1, text: "Called by: foo.ts" }],
      });

      expect(result.content[0].text).toContain("[via extension]");
      expect(receivedEvents).toHaveLength(1);
      expect(receivedEvents[0].tool).toBe("set_codelens");
    });

    it("clear_blast_radius forwards to extension", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir, client);
      const result = await callTool(mcpServer, "clear_blast_radius", {});

      expect(result.content[0].text).toContain("[via extension]");
      expect(receivedEvents).toHaveLength(1);
      expect(receivedEvents[0].tool).toBe("clear_blast_radius");
    });

    it("open_file forwards to extension", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir, client);
      const result = await callTool(mcpServer, "open_file", {
        path: "src/main.ts",
        line: 42,
      });

      expect(result.content[0].text).toContain("[via extension]");
      expect(receivedEvents).toHaveLength(1);
      expect(receivedEvents[0].tool).toBe("open_file");
      expect(receivedEvents[0].params.path).toBe("src/main.ts");
    });

    it("clear_all forwards to extension", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir, client);
      const result = await callTool(mcpServer, "clear_all", {});

      expect(result.content[0].text).toContain("[via extension]");
      expect(receivedEvents).toHaveLength(1);
      expect(receivedEvents[0].tool).toBe("clear_all");
    });

    it("mark_read still updates filesystem directly (not forwarded)", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir, client);
      const result = await callTool(mcpServer, "mark_read", {
        path: "src/config.ts",
      });

      // mark_read is a filesystem tool — should NOT forward to extension
      expect(receivedEvents).toHaveLength(0);
      expect(result.content[0].text).toContain("confirmed");

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      expect(progress.files["src/config.ts"].status).toBe("confirmed");
    });

    it("mark_flagged still updates filesystem directly (not forwarded)", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir, client);
      const result = await callTool(mcpServer, "mark_flagged", {
        path: "src/auth.ts",
        reason: "needs review",
      });

      expect(receivedEvents).toHaveLength(0);
      expect(result.content[0].text).toContain("flagged");

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      expect(progress.files["src/auth.ts"].status).toBe("flagged");
    });
  });

  describe("when VS Code extension is NOT running (no IPC)", () => {
    it("highlight_range degrades gracefully with note", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir);
      const result = await callTool(mcpServer, "highlight_range", {
        file: "src/main.ts",
        startLine: 10,
        endLine: 20,
        style: "focus",
      });

      const parsed = JSON.parse(result.content[0].text);
      expect(parsed.success).toBe(true);
      expect(parsed.note).toContain("not connected");
    });

    it("mark_read still works fully", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir);
      await callTool(mcpServer, "mark_read", { path: "src/config.ts" });

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      expect(progress.files["src/config.ts"].status).toBe("confirmed");
    });

    it("mark_flagged still works fully", async () => {
      const mcpServer = createStandaloneMcpServer(tmpDir);
      await callTool(mcpServer, "mark_flagged", {
        path: "src/auth.ts",
        reason: "needs review",
      });

      const progressPath = path.join(guideDir, "progress.json");
      const progress = JSON.parse(fs.readFileSync(progressPath, "utf-8"));
      expect(progress.files["src/auth.ts"].status).toBe("flagged");
    });
  });
});

/** Helper to invoke a tool handler directly (bypassing MCP transport). */
async function callTool(
  server: { server: unknown },
  toolName: string,
  args: Record<string, unknown>,
): Promise<{
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}> {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const registeredTools = (server.server as any)._registeredTools as Record<
    string,
    {
      handler: (
        args: Record<string, unknown>,
        extra: unknown,
      ) => Promise<unknown>;
    }
  >;

  const tool = registeredTools[toolName];
  if (!tool) {
    throw new Error(`Tool '${toolName}' not registered`);
  }

  const result = await tool.handler(args, {});
  return result as {
    content: Array<{ type: string; text: string }>;
    isError?: boolean;
  };
}
