/**
 * Shared regex patterns for detecting function/class declarations
 * across language types. Used by both CallerCountProvider and
 * CodeLensProvider to find declaration lines in source code.
 */

/**
 * Regex patterns for detecting function/class declaration lines.
 * Each pattern captures the declared name in group 1.
 */
export const FUNCTION_PATTERNS: RegExp[] = [
  // JS/TS: function declarations (with optional export/async/default)
  /(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)/,
  // JS/TS: arrow function or function expression assignments
  /(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>/,
  // JS/TS: class declarations
  /(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)/,
  // Python: def statements
  /^(?:\s*)(?:async\s+)?def\s+(\w+)\s*\(/,
  // Python: class statements
  /^(?:\s*)class\s+(\w+)/,
];

/**
 * Extracts the declared name from a line of code, if it contains
 * a function, class, or method declaration.
 *
 * @returns The declared name, or undefined if no declaration found.
 */
export function extractDeclaredName(lineText: string): string | undefined {
  for (const pattern of FUNCTION_PATTERNS) {
    const match = pattern.exec(lineText);
    if (match?.[1]) {
      return match[1];
    }
  }
  return undefined;
}
