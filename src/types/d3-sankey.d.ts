/**
 * Minimal types for d3-sankey (the package ships none and has no @types on this registry).
 *
 * Only what this project uses: the generator, the horizontal link path, and the alignments. The
 * layout node/link shapes are the library's own — narrowed to `any` where a chart author would
 * otherwise argue with the compiler instead of the data.
 */
declare module 'd3-sankey' {
  export interface SankeyNode {
    id: string; label?: string; value?: number;
    x0: number; x1: number; y0: number; y1: number;
  }
  export interface SankeyLink {
    source: any; target: any; value: number; width: number;
    y0?: number; y1?: number;
  }
  export interface SankeyGraph { nodes: SankeyNode[]; links: SankeyLink[] }
  export interface SankeyGenerator {
    (graph: { nodes: any[]; links: any[] }): SankeyGraph;
    nodeId(fn: (d: any) => string): SankeyGenerator;
    nodeWidth(n: number): SankeyGenerator;
    nodePadding(n: number): SankeyGenerator;
    nodeAlign(fn: any): SankeyGenerator;
    extent(e: [[number, number], [number, number]]): SankeyGenerator;
  }
  export function sankey(): SankeyGenerator;
  export function sankeyJustify(node: any, n: number): number;
  export function sankeyLeft(node: any, n: number): number;
  export function sankeyLinkHorizontal(): (link: any) => string | null;
}
