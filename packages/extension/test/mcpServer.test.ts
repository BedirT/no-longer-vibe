import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("vscode", async () => {
  return await import("./__mocks__/vscode");
});

import {
  createMcpServer,
  getMcpToolNames,
  type McpToolEvent,
  type HighlightStyle,
} from "../src/mcpServer";

describe("mcpServer", () => {
  describe("createMcpServer", () => {
    it("creates an MCP server instance", () => {
      const server = createMcpServer();
      expect(server).toBeDefined();
      expect(server.server).toBeDefined();
      expect(server.toolEvents).toBeDefined();
    });
  });

  describe("getMcpToolNames", () => {
    it("returns all registered tool names", () => {
      const names = getMcpToolNames();
      expect(names).toContain("highlight_range");
      expect(names).toContain("clear_highlights");
      expect(names).toContain("open_file");
      expect(names).toContain("mark_read");
      expect(names).toContain("mark_flagged");
      expect(names).toContain("set_codelens");
      expect(names).toContain("show_blast_radius");
      expect(names).toContain("clear_blast_radius");
      expect(names).toContain("update_progress_tree");
      expect(names).toContain("clear_all");
      expect(names).toHaveLength(10);
    });
  });

  describe("tool event emission", () => {
    it("emits highlight_range event with correct params", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      // Simulate calling the tool through the server's internal handler
      const result = await callTool(server, "highlight_range", {
        file: "src/main.ts",
        startLine: 10,
        endLine: 20,
        style: "focus",
      });

      expect(result.content).toBeDefined();
      expect(result.isError).not.toBe(true);
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("highlight_range");
      expect(events[0].params).toEqual({
        file: "src/main.ts",
        startLine: 10,
        endLine: 20,
        style: "focus",
      });
    });

    it("emits clear_highlights event with file param", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "clear_highlights", {
        file: "src/main.ts",
      });

      expect(result.isError).not.toBe(true);
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("clear_highlights");
      expect(events[0].params).toEqual({ file: "src/main.ts" });
    });

    it("emits clear_highlights event without file (clears all)", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "clear_highlights", {});

      expect(result.isError).not.toBe(true);
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("clear_highlights");
    });

    it("emits open_file event with path and optional line", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "open_file", {
        path: "src/config.ts",
        line: 42,
      });

      expect(result.isError).not.toBe(true);
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("open_file");
      expect(events[0].params).toEqual({ path: "src/config.ts", line: 42 });
    });

    it("emits open_file event with path only", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "open_file", {
        path: "src/config.ts",
      });

      expect(result.isError).not.toBe(true);
      expect(events[0].params).toEqual({ path: "src/config.ts" });
    });

    it("emits mark_read event", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "mark_read", {
        path: "src/config.ts",
      });

      expect(result.isError).not.toBe(true);
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("mark_read");
      expect(events[0].params).toEqual({ path: "src/config.ts" });
    });

    it("emits mark_flagged event with reason", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "mark_flagged", {
        path: "src/auth.ts",
        reason: "Dual token store seems unnecessary",
      });

      expect(result.isError).not.toBe(true);
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("mark_flagged");
      expect(events[0].params).toEqual({
        path: "src/auth.ts",
        reason: "Dual token store seems unnecessary",
      });
    });
  });

  describe("stub tools", () => {
    it("set_codelens returns success message and emits event", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e: McpToolEvent) => events.push(e));

      const result = await callTool(server, "set_codelens", {
        file: "src/main.ts",
        entries: [{ line: 1, text: "Called by: foo.ts" }],
      });

      expect(result.content).toBeDefined();
      const textContent = result.content[0];
      expect(textContent.type).toBe("text");
      expect(textContent.text).toContain("1 CodeLens entries on src/main.ts");

      // Verify event emission
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("set_codelens");
      expect(events[0].params.file).toBe("src/main.ts");
    });

    it("show_blast_radius emits event and returns confirmation", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "show_blast_radius", {
        symbol: "validateToken",
      });

      const textContent = result.content[0];
      expect(textContent.type).toBe("text");
      expect(textContent.text).toContain("validateToken");

      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("show_blast_radius");
      expect(events[0].params.symbol).toBe("validateToken");
    });

    it("clear_blast_radius emits event and returns confirmation", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "clear_blast_radius", {});

      const textContent = result.content[0];
      expect(textContent.type).toBe("text");
      expect(textContent.text).toContain("cleared");

      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("clear_blast_radius");
    });

    it("update_progress_tree emits event and returns confirmation", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: Array<{ tool: string }> = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "update_progress_tree", {});

      const textContent = result.content[0];
      expect(textContent.type).toBe("text");
      expect(textContent.text).toContain("Progress tree refreshed");
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("update_progress_tree");
    });
  });

  describe("clear_all tool", () => {
    it("emits clear_all event", async () => {
      const { server, toolEvents } = createMcpServer();
      const events: McpToolEvent[] = [];
      toolEvents.event((e) => events.push(e));

      const result = await callTool(server, "clear_all", {});

      expect(result.isError).not.toBe(true);
      expect(events).toHaveLength(1);
      expect(events[0].tool).toBe("clear_all");
    });
  });

  describe("highlight_range style validation", () => {
    const validStyles: HighlightStyle[] = [
      "focus",
      "context",
      "warning",
      "blast-radius",
    ];

    for (const style of validStyles) {
      it(`accepts '${style}' as a valid style`, async () => {
        const { server, toolEvents } = createMcpServer();
        const events: McpToolEvent[] = [];
        toolEvents.event((e) => events.push(e));

        const result = await callTool(server, "highlight_range", {
          file: "src/main.ts",
          startLine: 1,
          endLine: 5,
          style,
        });

        expect(result.isError).not.toBe(true);
        expect(events[0].params.style).toBe(style);
      });
    }
  });

  describe("tool result content format", () => {
    it("returns text content for highlight_range", async () => {
      const { server } = createMcpServer();
      const result = await callTool(server, "highlight_range", {
        file: "src/main.ts",
        startLine: 10,
        endLine: 20,
        style: "focus",
      });

      expect(result.content).toHaveLength(1);
      expect(result.content[0].type).toBe("text");
      expect(typeof result.content[0].text).toBe("string");
    });

    it("returns text content for mark_read", async () => {
      const { server } = createMcpServer();
      const result = await callTool(server, "mark_read", {
        path: "src/config.ts",
      });

      expect(result.content).toHaveLength(1);
      expect(result.content[0].type).toBe("text");
    });
  });
});

/**
 * Helper to invoke a tool handler directly on the McpServer,
 * bypassing MCP protocol transport for unit testing.
 */
async function callTool(
  server: ReturnType<typeof createMcpServer>["server"],
  toolName: string,
  args: Record<string, unknown>,
): Promise<{
  content: Array<{ type: string; text: string }>;
  isError?: boolean;
}> {
  // Access the registered tools through the server's internal state.
  // The McpServer stores tools in _registeredTools as a plain object keyed by name.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const registeredTools = (server as any)._registeredTools as Record<
    string,
    { handler: (args: Record<string, unknown>, extra: unknown) => Promise<unknown> }
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
