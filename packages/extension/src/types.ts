/**
 * TypeScript interfaces for the map.json schema defined in SPEC.md.
 */

/** Layer names used to categorize files by dependency depth. */
export type LayerName =
  | "foundation"
  | "core"
  | "features"
  | "integration"
  | "entry";

/** Complexity rating for a file. */
export type Complexity = "low" | "medium" | "high";

/** A layer grouping within the codebase map. */
export interface Layer {
  description: string;
  files: string[];
}

/** A single entry in the reading order sequence. */
export interface ReadingOrderEntry {
  index: number;
  path: string;
  layer: LayerName;
  reason: string;
  complexity: Complexity;
  line_count: number;
  imports: string[];
  imported_by: string[];
  exports: string[];
}

/** Dependency information for a single file. */
export interface DependencyInfo {
  imports: string[];
  imported_by: string[];
}

/** The top-level map.json schema. */
export interface CodebaseMap {
  version: string;
  repo_root: string;
  generated_at: string;
  content_hashes: Record<string, string>;
  total_files: number;
  layers: Record<LayerName, Layer>;
  reading_order: ReadingOrderEntry[];
  dependency_graph: Record<string, DependencyInfo>;
}
