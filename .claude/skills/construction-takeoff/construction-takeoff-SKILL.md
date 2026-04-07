---
name: construction-takeoff
description: "Domain knowledge skill for NotchField construction takeoff features. USE THIS SKILL whenever implementing, modifying, or debugging any feature related to: takeoff objects (polygons, lines, counts), classifications (trade-specific categories), scale calibration, quantities/cost calculations, the Fabric.js canvas editor, PDF.js plan rendering, AI plan analysis with Gemini, repeating groups, drawing management, export (Excel/PDF), touch gestures, snapping, merge/cut/split tools, assemblies, or any construction-specific logic. Also use when the user mentions 'takeoff', 'classification', 'polygon', 'quantities', 'scale', 'calibration', 'drawing', 'plan', 'sqft', 'linear feet', 'waste factor', 'BOM', or any of the 10 supported trades (marble, tile, drywall, paint, concrete, flooring, roofing, electrical, plumbing, HVAC). This skill contains geometry math, Fabric.js patterns, trade templates, and hard-won lessons from V1/V2 that prevent costly bugs."
argument-hint: "[feature or question]"
---

# Construction Takeoff — Domain Knowledge

> This skill is the construction brain of NotchField. It contains domain knowledge, code patterns, and rules that apply to every takeoff-related feature.

## Table of Contents
1. Core Concepts (what an estimator does)
2. Geometry & Math
3. Fabric.js Canvas Patterns
4. PDF.js Rendering
5. Classifications & 10 Trades
6. Quantities & Cost Engine
7. Scale Calibration
8. GestureManager (Touch Layer)
9. AI Integration (Gemini 3.1 Pro)
10. Repeating Groups
11. Export (Excel / PDF)
12. Data Integrity Rules
13. Hard-Won Lessons (V1/V2 Bugs)

---

## 1. Core Concepts

**What is a construction takeoff?**
An estimator receives architectural plans (PDF blueprints), measures areas/lengths/counts of materials needed, and produces a quantity report used to generate a bid. "Takeoff" = extracting quantities from plans.

**The workflow:**
1. Upload PDF plans (could be 200+ pages for a high-rise)
2. Organize into Drawing Sets (versioned groups)
3. Calibrate scale on each drawing (2-click calibration)
4. Draw polygons/lines/counts over the plan, assigning each to a Classification
5. Review quantities in the Quantities Panel
6. Export to Excel/PDF for the bid package

**Key terms:**
- **Drawing:** A single page/sheet from the plan set (floor plan, detail, elevation)
- **Drawing Set:** A versioned collection of drawings for a project
- **Classification:** A color-coded category (e.g., "Marble Floor", "Tile Wall", "Paint Ceiling")
- **Takeoff Object:** A geometric shape drawn on a drawing, linked to a classification
- **Scale:** The ratio of pixels to real-world inches on a drawing
- **Waste Factor:** Extra material percentage to account for cuts/breakage (e.g., 10%)
- **Assembly:** A recipe of materials for a classification (e.g., "Tile Wall" = tile + thinset + grout + backer board)
- **Repeating Group:** A master takeoff applied to multiple identical units (typical floors in a high-rise)
- **BOM (Bill of Materials):** Quantities converted to purchasable units (sqft → boxes of tile)

---

## 2. Geometry & Math

### Coordinate System
All geometry is stored as **normalized [0-1] coordinates** relative to image dimensions.

```typescript
// Converting pixel coordinates to normalized
const normalizedX = pixelX / imageWidth;   // 0.0 to 1.0
const normalizedY = pixelY / imageHeight;  // 0.0 to 1.0

// Converting back to pixels (for rendering)
const pixelX = normalizedX * imageWidth;
const pixelY = normalizedY * imageHeight;
```

**Why normalized?** If the user zooms, resizes browser, or the image loads at different resolution, the coordinates still map correctly. Stored in DB as JSONB:
```json
{
  "points": [[0.15, 0.22], [0.45, 0.22], [0.45, 0.55], [0.15, 0.55]],
  "type": "polygon"
}
```

### Area Calculation (Shoelace Formula)
```typescript
function polygonAreaSqft(
  points: [number, number][],  // normalized [0-1]
  imageWidth: number,          // pixels
  imageHeight: number,         // pixels
  scalePxPerInch: number       // from calibration
): number {
  // Convert to real-world inches
  const realPoints = points.map(([nx, ny]) => [
    (nx * imageWidth) / scalePxPerInch,   // inches
    (ny * imageHeight) / scalePxPerInch,  // inches
  ]);

  // Shoelace formula
  let area = 0;
  const n = realPoints.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    area += realPoints[i][0] * realPoints[j][1];
    area -= realPoints[j][0] * realPoints[i][1];
  }
  area = Math.abs(area) / 2;

  // Convert sq inches to sq feet
  return area / 144;
}
```

### Linear Measurement
```typescript
function lineLength(
  p1: [number, number],       // normalized
  p2: [number, number],       // normalized
  imageWidth: number,
  imageHeight: number,
  scalePxPerInch: number
): number {
  const dx = ((p2[0] - p1[0]) * imageWidth) / scalePxPerInch;
  const dy = ((p2[1] - p1[1]) * imageHeight) / scalePxPerInch;
  const inches = Math.sqrt(dx * dx + dy * dy);
  return inches / 12; // linear feet
}
```

### Dimension Parser
Estimators enter dimensions in many formats. Parse them ALL:
```typescript
function parseDimension(input: string): number | null {
  const s = input.trim().toLowerCase();

  // "12'6"" or "12' 6"" — feet and inches
  const feetInches = s.match(/^(\d+)['\u2019]\s*(\d+(?:\.\d+)?)["\u201d]?$/);
  if (feetInches) return parseFloat(feetInches[1]) * 12 + parseFloat(feetInches[2]);

  // "12ft 6in" or "12 ft 6 in"
  const ftIn = s.match(/^(\d+)\s*ft\s*(\d+(?:\.\d+)?)\s*in$/);
  if (ftIn) return parseFloat(ftIn[1]) * 12 + parseFloat(ftIn[2]);

  // "12.5" — assume feet, convert to inches
  const decimal = s.match(/^(\d+(?:\.\d+)?)$/);
  if (decimal) return parseFloat(decimal[1]) * 12;

  // "150in" — inches directly
  const inOnly = s.match(/^(\d+(?:\.\d+)?)\s*in$/);
  if (inOnly) return parseFloat(inOnly[1]);

  // "12ft" — feet only
  const ftOnly = s.match(/^(\d+(?:\.\d+)?)\s*ft$/);
  if (ftOnly) return parseFloat(ftOnly[1]) * 12;

  return null; // unparseable
}
```

---

## 3. Fabric.js Canvas Patterns

### CRITICAL Rules (from V1/V2 auto-blindaje)

**NEVER put CSS classes on the `<canvas>` element that Fabric.js initializes.** Fabric creates its own internal canvas elements. CSS on the parent canvas breaks coordinate mapping. Use a `<div>` wrapper instead.

**ALWAYS specify `originX: 'left', originY: 'top'`** when creating Fabric objects. Fabric v6+ changed defaults and without this, objects position incorrectly.

**Lazy-load PDF.js.** NEVER `import * as pdfjsLib from 'pdfjs-dist'` at top level — it breaks SSR. Use singleton pattern:
```typescript
let pdfjsPromise: Promise<typeof import('pdfjs-dist')> | null = null;

export function getPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = import('pdfjs-dist').then(mod => {
      mod.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';
      return mod;
    });
  }
  return pdfjsPromise;
}
```

### Tool Architecture (Command Pattern)
Every drawing tool implements the `Tool` interface:
```typescript
interface Tool {
  name: string;
  activate(canvas: fabric.Canvas): void;
  deactivate(canvas: fabric.Canvas): void;
  onMouseDown(event: fabric.TEvent): void;
  onMouseMove(event: fabric.TEvent): void;
  onMouseUp(event: fabric.TEvent): void;
}
```

All mutations go through `CommandHistory` for undo/redo:
```typescript
interface Command {
  execute(): void;
  undo(): void;
}

class AddObjectCommand implements Command {
  execute() { /* add to canvas + save to Supabase */ }
  undo() { /* remove from canvas + delete from Supabase */ }
}
```

The `ToolManager` singleton routes canvas events to the active tool:
```typescript
class ToolManager {
  private activeTool: Tool | null = null;
  private tools: Map<string, Tool> = new Map();

  setActiveTool(name: string) {
    this.activeTool?.deactivate(this.canvas);
    this.activeTool = this.tools.get(name) || null;
    this.activeTool?.activate(this.canvas);
  }
}
```

### Object Creation Pattern
```typescript
// ALWAYS follow this pattern when creating takeoff objects
const polygon = new fabric.Polygon(fabricPoints, {
  fill: classification.color + '40',     // 25% opacity fill
  stroke: classification.color,
  strokeWidth: 2,
  originX: 'left',                       // CRITICAL
  originY: 'top',                        // CRITICAL
  selectable: true,
  objectType: 'takeoff',                 // custom property
  classificationId: classification.id,   // custom property
  takeoffObjectId: dbRecord.id,          // links to Supabase row
});

canvas.add(polygon);
```

### Color-Coding
Objects are colored by their classification. The fill is 25% opacity (`color + '40'`), stroke is full opacity. This lets the underlying blueprint show through while clearly marking measured areas.

---

## 4. PDF.js Rendering

### Multi-Resolution Pattern
Render at 2x for crisp display on retina screens:
```typescript
const RENDER_SCALE = 2;
const viewport = page.getViewport({ scale: RENDER_SCALE });

const canvas = document.createElement('canvas');
canvas.width = viewport.width;
canvas.height = viewport.height;
canvas.style.width = `${viewport.width / RENDER_SCALE}px`;
canvas.style.height = `${viewport.height / RENDER_SCALE}px`;

await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
```

**PDF.js v5 API change:** Use `canvas` property, NOT `canvasContext`:
```typescript
// v5: page.render({ canvas: canvasEl, viewport })
// v4: page.render({ canvasContext: ctx, viewport })
```

---

## 5. Classifications & 10 Trades

When an organization registers, they select a primary trade. Default classifications are auto-created:

```typescript
const TRADE_DEFAULTS: Record<string, Classification[]> = {
  marble: [
    { name: 'Floor', unit: 'sqft', color: '#3B82F6', waste_factor: 0.10 },
    { name: 'Wall', unit: 'sqft', color: '#8B5CF6', waste_factor: 0.10 },
    { name: 'Countertop', unit: 'sqft', color: '#06B6D4', waste_factor: 0.15 },
    { name: 'Threshold', unit: 'lnft', color: '#F59E0B', waste_factor: 0.05 },
    { name: 'Baseboard', unit: 'lnft', color: '#10B981', waste_factor: 0.05 },
  ],
  tile: [
    { name: 'Floor Tile', unit: 'sqft', color: '#3B82F6', waste_factor: 0.10 },
    { name: 'Wall Tile', unit: 'sqft', color: '#8B5CF6', waste_factor: 0.10 },
    { name: 'Backsplash', unit: 'sqft', color: '#06B6D4', waste_factor: 0.12 },
    { name: 'Shower Pan', unit: 'sqft', color: '#F59E0B', waste_factor: 0.15 },
  ],
  drywall: [
    { name: 'Standard Wall', unit: 'sqft', color: '#3B82F6', waste_factor: 0.08 },
    { name: 'Ceiling', unit: 'sqft', color: '#8B5CF6', waste_factor: 0.08 },
    { name: 'Bulkhead', unit: 'sqft', color: '#06B6D4', waste_factor: 0.10 },
    { name: 'Soffit', unit: 'sqft', color: '#F59E0B', waste_factor: 0.10 },
  ],
  paint: [
    { name: 'Wall Paint', unit: 'sqft', color: '#3B82F6', waste_factor: 0.05 },
    { name: 'Ceiling Paint', unit: 'sqft', color: '#8B5CF6', waste_factor: 0.05 },
    { name: 'Trim', unit: 'lnft', color: '#06B6D4', waste_factor: 0.08 },
    { name: 'Door', unit: 'count', color: '#F59E0B', waste_factor: 0.00 },
  ],
  concrete: [
    { name: 'Slab', unit: 'sqft', color: '#3B82F6', waste_factor: 0.05 },
    { name: 'Foundation', unit: 'sqft', color: '#8B5CF6', waste_factor: 0.05 },
    { name: 'Column', unit: 'count', color: '#06B6D4', waste_factor: 0.00 },
    { name: 'Beam', unit: 'lnft', color: '#F59E0B', waste_factor: 0.05 },
  ],
  flooring: [
    { name: 'Hardwood', unit: 'sqft', color: '#3B82F6', waste_factor: 0.10 },
    { name: 'LVP', unit: 'sqft', color: '#8B5CF6', waste_factor: 0.08 },
    { name: 'Carpet', unit: 'sqft', color: '#06B6D4', waste_factor: 0.10 },
    { name: 'Epoxy', unit: 'sqft', color: '#F59E0B', waste_factor: 0.05 },
  ],
  roofing: [
    { name: 'Shingle', unit: 'sqft', color: '#3B82F6', waste_factor: 0.12 },
    { name: 'Membrane', unit: 'sqft', color: '#8B5CF6', waste_factor: 0.08 },
    { name: 'Flashing', unit: 'lnft', color: '#06B6D4', waste_factor: 0.10 },
    { name: 'Gutter', unit: 'lnft', color: '#F59E0B', waste_factor: 0.05 },
  ],
  electrical: [
    { name: 'Outlet', unit: 'count', color: '#3B82F6', waste_factor: 0.00 },
    { name: 'Switch', unit: 'count', color: '#8B5CF6', waste_factor: 0.00 },
    { name: 'Panel', unit: 'count', color: '#06B6D4', waste_factor: 0.00 },
    { name: 'Conduit', unit: 'lnft', color: '#F59E0B', waste_factor: 0.05 },
  ],
  plumbing: [
    { name: 'Pipe', unit: 'lnft', color: '#3B82F6', waste_factor: 0.05 },
    { name: 'Fixture', unit: 'count', color: '#8B5CF6', waste_factor: 0.00 },
    { name: 'Drain', unit: 'count', color: '#06B6D4', waste_factor: 0.00 },
    { name: 'Valve', unit: 'count', color: '#F59E0B', waste_factor: 0.00 },
  ],
  hvac: [
    { name: 'Duct', unit: 'lnft', color: '#3B82F6', waste_factor: 0.08 },
    { name: 'Vent', unit: 'count', color: '#8B5CF6', waste_factor: 0.00 },
    { name: 'Unit', unit: 'count', color: '#06B6D4', waste_factor: 0.00 },
    { name: 'Thermostat', unit: 'count', color: '#F59E0B', waste_factor: 0.00 },
  ],
};
```

### Classification Hierarchy
Classifications support nested folders via `parent_id` and `is_folder`:
```
📁 Finishes
  📁 Marble
    Floor (sqft, blue)
    Wall (sqft, purple)
  📁 Tile
    Floor Tile (sqft, blue)
    Wall Tile (sqft, purple)
```

---

## 6. Quantities & Cost Engine

### Calculation Logic
```typescript
interface QuantityGroup {
  classification: Classification;
  objects: TakeoffObject[];
  totalArea: number;      // sum of area_sqft
  totalLength: number;    // sum of length_lnft
  totalCount: number;     // count of count-type objects
  wastedTotal: number;    // total × (1 + waste_factor)
  unitCost: number;       // from classification.unit_cost
  totalCost: number;      // wastedTotal × unitCost
}
```

**The quantities panel updates reactively.** Use Supabase Realtime subscription on `takeoff_objects` filtered by drawing_id. When any object changes, recalculate all groups.

**Currency formatting** — always locale-aware:
```typescript
const formatCurrency = (amount: number, locale: string = 'en-US') =>
  new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD' }).format(amount);
```

---

## 7. Scale Calibration

The user clicks two points on the plan where they know the real-world distance (e.g., a dimension line showing "12'-6\"").

```typescript
function calculateScale(
  point1: { x: number; y: number },  // pixel coordinates on canvas
  point2: { x: number; y: number },
  realDimensionInches: number          // parsed from user input
): number {
  const pixelDistance = Math.sqrt(
    Math.pow(point2.x - point1.x, 2) + Math.pow(point2.y - point1.y, 2)
  );
  return pixelDistance / realDimensionInches;  // px per inch
}
```

**CRITICAL:** Without scale calibration, all area/length measurements are meaningless. The editor MUST show a prominent warning and disable cost calculations until scale is set. Display measurements as "px" instead of "sqft"/"lnft" when uncalibrated.

---

## 8. GestureManager (Touch Layer)

Prevents conflicts between Fabric.js drawing tools and navigation gestures:

```typescript
class GestureManager {
  private mode: 'idle' | 'drawing' | 'panning' | 'zooming' = 'idle';

  handleTouchStart(e: TouchEvent) {
    if (e.touches.length >= 2) {
      this.mode = 'panning';
      this.disableFabricMouseEvents();
      return; // Don't forward to Fabric
    }
    this.mode = 'drawing';
    this.forwardToFabricAsMouse(e);
  }

  handleTouchEnd(e: TouchEvent) {
    if (e.touches.length === 0) {
      this.mode = 'idle';
      this.enableFabricMouseEvents();
    }
  }
}
```

**Rules:**
- 1 finger = active tool (Fabric receives events)
- 2 fingers = pan/zoom (Fabric does NOT receive events)
- Long press (500ms, no movement >10px) = context menu
- Touch handles on selected objects = 44px radius minimum
- Debounce dialog opens from canvas taps by 150ms

---

## 9. AI Integration (Gemini 3.1 Pro)

### What Gemini CAN do (tested March 2026):
- Identify rooms with correct names (PB-7.0, SB-7.0, B-1.0 TYPE A)
- Classify room types (Primary Bathroom, Powder Room, Walk-In Closet)
- Detect fixtures (double vanity, toilet, bathtub, walk-in shower, cooktop, refrigerator)
- Identify HVAC units, structural columns, windows, closet fixtures
- Classify walls (exterior, demising, interior partitions)

### What Gemini CANNOT do:
- Produce precise polygon coordinates for room boundaries
- Calculate accurate square footage from visual analysis alone
- Replace the estimator drawing polygons manually

### AI Strategy: Guided Takeoff
1. **AI Scan** → Gemini analyzes plan → returns room/fixture/wall list with classifications
2. **Smart Classification** → Auto-suggest finish type per room
3. **Guided Checklist** → "Draw polygon for FOYER ☐, PR-2.0 ☐, LR/DR/K ☐..."
4. **User draws** → Estimator draws polygons with AI-suggested classifications pre-selected

### AI Feedback Loop
When user corrects an AI classification, log it:
```typescript
await supabase.from('ai_training_feedback').insert({
  organization_id: orgId,
  project_id: projectId,
  drawing_id: drawingId,
  ai_prediction: { room: 'PB-7.0', predicted_class: 'tile wall' },
  user_correction: { corrected_class: 'marble wall' },
  bounding_box: [[0.15, 0.22], [0.45, 0.55]],
});
```

On subsequent AI Scans for the same project, send past corrections as context.

---

## 10. Repeating Groups

For high-rise buildings where multiple floors have identical layouts:

1. Estimator completes takeoff on one "master" drawing (e.g., typical floor plan)
2. Creates a Repeating Group from selected objects
3. Applies the group to other drawings (floors 5-30)
4. Placement is flexible: flip horizontal/vertical, rotate to match
5. Edit master → ALL instances update automatically
6. Quantities auto-aggregate across all instances

**This single feature saves 20+ hours per project on a 30-story high-rise.**

---

## 11. Export

### Excel Export (ExcelJS)
- **Sheet 1 "Summary":** Classification | Unit | Quantity | Waste % | With Waste | Unit Cost | Total Cost
- **Sheet 2 "Detail":** Drawing | Classification | Object Label | Area/Length/Count
- Header: project name, address, date, org name
- Professional formatting: borders, colors, auto-width columns

### PDF Export (jsPDF)
- Page 1: Annotated plan with colored polygons + classification legend
- Page 2: Quantity table with costs
- Page 3 (optional): Visual evidence snapshot from `validations` table

---

## 12. Data Integrity Rules

- **Takeoff data is IMMUTABLE once finalized.** `master_production_targets` is read-only for Track.
- **Every table has RLS** using `organization_id = public.user_org_id()`.
- **Schema changes to shared tables** (`organizations`, `profiles`, `projects`, `classifications`) require cross-app impact analysis.
- **Geometry is always normalized [0-1].** Never store pixel coordinates in the database.
- **Scale is per-drawing**, not per-project. Different drawings may have different scales.

---

## 13. Hard-Won Lessons (V1/V2 Bugs)

| Bug | Fix | Rule |
|-----|-----|------|
| Fabric.js objects positioned wrong | Always set `originX: 'left', originY: 'top'` | EVERY Fabric object creation |
| PDF.js breaks SSR | Lazy-load with singleton `await import()` | NEVER top-level import |
| CSS on `<canvas>` breaks Fabric | Use `<div>` wrapper, no CSS on canvas | NEVER style the canvas element |
| Dialog closes on canvas click | Debounce 150ms before opening dialogs | ALL dialogs triggered by canvas |
| Nested `<button>` hydration error | Use `<div role="button">` for clickable containers | NEVER nest interactive elements |
| Scale shows wrong units | Check `scale_set` boolean before calculations | ALWAYS guard with calibration check |
| Quantities show stale data | Use Supabase Realtime subscription | NEVER manual refetch for quantities |

---

## References (load on demand)

For detailed specs beyond this SKILL.md, read:
- `CLAUDE.md` — Full Factory OS with stack, roadmap, restrictions
- `BUSINESS_LOGIC.md` — Complete product spec with DB schema, all features by phase
- `TASKS.md` — Current task tracker with session logs

For AI prompts and Gemini integration details, see:
- `src/features/ai/prompts/` — System prompts for AI Scan, Chat, Image Search
- `src/features/ai/parsers/` — Gemini response → Fabric.js object converters
