/**
 * Pure utility for cascading confirmed status to exports.
 * No vscode dependency — safe to use from both the extension and
 * the standalone MCP server.
 */

interface ExportsReadMap {
  [exportName: string]: { read_at: string; summary?: string | null };
}

interface FileEntryWithExports {
  exports_read?: ExportsReadMap;
}

/**
 * Cascades confirmed status to all exports that have no existing
 * entry in exports_read. Mutates the file entry in place.
 *
 * @param fileEntry - The progress file entry to update
 * @param exports - List of export names from map.json reading_order
 * @param now - ISO timestamp for the read_at field
 */
export function cascadeExportsForConfirmed(
  fileEntry: FileEntryWithExports,
  exports: string[],
  now: string,
): void {
  if (exports.length === 0) return;

  if (!fileEntry.exports_read) {
    fileEntry.exports_read = {};
  }

  for (const name of exports) {
    if (!fileEntry.exports_read[name]) {
      fileEntry.exports_read[name] = { read_at: now };
    }
  }
}
