---
name: quality-gate-readyboard
description: "AI-powered quality control and trade readiness verification for construction field ops. USE THIS SKILL whenever implementing QC photo checklists, background AI photo analysis for defect detection, Ready Board (trade readiness by area), delay documentation with reason codes, delay impact reports, or worker QC accountability tracking. Triggers: 'quality gate', 'QC check', 'QC photos', 'defect detection', 'ready board', 'readiness', 'trade ready', 'delay documentation', 'delay log', 'blocked area', 'back-charge', 'time extension', 'delay impact', 'wait time', 'prior trade'. Contains two integrated features: Quality Gate (AI background QC) and Ready Board (delay documentation engine)."
---

# Quality Gate + Ready Board — Field Intelligence

> Two features that share infrastructure: photos, GPS, AI analysis, area status tracking.
> Quality Gate catches defects before GC punch list.
> Ready Board prevents crew idle time and documents delays for legal protection.

## Table of Contents
1. Quality Gate — AI Background QC
2. Ready Board — Trade Readiness
3. Delay Documentation Engine
4. Shared Infrastructure
5. Trade-Specific QC Checklists
6. AI Analysis Patterns
7. Data Model
8. Implementation

---

## 1. Quality Gate — AI Background QC

### Flow (foreman NEVER waits)

```
Installer finishes bathroom
        │
Foreman opens area drawer → taps "QC Check"
        │
System shows trade-specific photo checklist (5-8 items)
        │
Foreman takes photos → taps "Submit QC"
        │
Area marked "QC Submitted" (yellow) ← FOREMAN LEAVES, goes to next area
        │
        ╰──── BACKGROUND (server-side) ────╮
              │                              │
              Photos upload (or queue        │
              offline, upload later)         │
              │                              │
              Gemini 3.1 Pro analyzes        │
              each photo (~15 sec/photo)     │
              │                              │
        ┌─────┴──────┐                       │
        │             │                      │
    ALL PASS      FLAGS FOUND                │
        │             │                      │
  Auto-update     Push notification          │
  "QC Passed"     to foreman:                │
  (green)         "Baño 23A — grout          │
                  gap detected in            │
                  photo 3"                   │
                      │                      │
              Foreman reviews:               │
              ├── Confirm → assign fix       │
              └── Dismiss → false positive   │
```

### Key principle
The AI is the first reviewer, not the final authority. The foreman always has the last word. False positives get dismissed. Confirmed issues get assigned for fix. The AI learns from dismissals over time.

---

## 2. Ready Board — Trade Readiness

### Status per area

| Status | Color | Icon | Meaning | Action |
|--------|-------|------|---------|--------|
| READY | Green | ✅ | All prior trades done. Go work. | Assign crew |
| ALMOST | Yellow | ⏳ | Prior trade 80%+. ETA 1-2 days. | Plan for tomorrow |
| BLOCKED | Red | 🚫 | Prior trade still working. ETA 3+ days. | Document delay |
| HELD | Dark Red | ⛔ | External blocker (no heat, no access). | Document + escalate |

### Trade sequence engine

```typescript
// Each organization defines trade sequences per project type
interface TradeSequence {
  project_type: string;          // 'residential_bathroom', 'commercial_lobby'
  sequence: TradeStep[];
}

interface TradeStep {
  order: number;
  trade: string;                 // 'rough_plumbing', 'framing', 'drywall', 'waterproof', 'tile', 'marble'
  must_complete: boolean;        // true = 100% required before next, false = can overlap
  overlap_percent?: number;      // if must_complete=false, next can start when this reaches X%
}

// Standard bathroom sequence (NYC high-rise)
const BATHROOM_SEQUENCE: TradeStep[] = [
  { order: 1, trade: 'rough_plumbing', must_complete: true },
  { order: 2, trade: 'framing', must_complete: true },
  { order: 3, trade: 'drywall', must_complete: true },
  { order: 4, trade: 'waterproofing', must_complete: true },
  { order: 5, trade: 'mud_level', must_complete: true },
  // ═══ YOUR TRADE GOES HERE ═══
  { order: 6, trade: 'tile_marble', must_complete: true },
  { order: 7, trade: 'grout_caulk', must_complete: true },
  { order: 8, trade: 'sealer', must_complete: true },
  { order: 9, trade: 'paint_touchup', must_complete: true },
  { order: 10, trade: 'fixtures', must_complete: true },
];

// Calculate readiness for your trade
function calculateReadiness(
  area: Area,
  myTradeOrder: number,
  tradeProgress: Map<string, number>  // trade → percent complete
): AreaReadiness {
  
  const priorTrades = BATHROOM_SEQUENCE.filter(t => t.order < myTradeOrder);
  
  for (const trade of priorTrades) {
    const progress = tradeProgress.get(trade.trade) || 0;
    
    if (trade.must_complete && progress < 100) {
      if (progress >= 80) {
        return { status: 'almost', blocking_trade: trade.trade, eta: estimateETA(trade, progress) };
      } else {
        return { status: 'blocked', blocking_trade: trade.trade, eta: estimateETA(trade, progress) };
      }
    }
  }
  
  return { status: 'ready', blocking_trade: null, eta: null };
}
```

### Readiness data sources

The Ready Board gets trade progress from multiple sources:

```typescript
// Source 1: NotchField Track users (our crew reports their own progress)
// This is the most accurate — real sqft data from production tab

// Source 2: GC schedule updates (PM manually updates other trades' status)
// Less granular but covers trades that don't use NotchField

// Source 3: GC's Procore/Fieldwire (future API integration)
// Auto-pull status from GC's system if they share access

// For MVP: Source 1 + Source 2 (manual input from PM/supervisor)
// The supervisor walks the floor and updates: "drywall done in 24A, 24B, 24C"
// Quick tap interface: area → prior trade → status (done/in-progress/not-started/percentage)
```

---

## 3. Delay Documentation Engine

### Delay reason codes

```typescript
const DELAY_REASONS = {
  PRIOR_TRADE: {
    label: 'Prior trade not finished',
    sub_reasons: ['Still working', 'Rework required', 'Failed inspection'],
    requires_trade_name: true,
    excusable: true,              // not your fault
  },
  NO_HEAT: {
    label: 'No heat in building',
    sub_reasons: ['Heating system off', 'Heating system broken', 'Fuel delivery late'],
    requires_trade_name: false,
    excusable: true,
  },
  NO_ACCESS: {
    label: 'Access denied by GC',
    sub_reasons: ['Floor closed', 'Elevator not available', 'Safety hold'],
    requires_trade_name: false,
    excusable: true,
  },
  INSPECTION_FAIL: {
    label: 'Prior trade failed inspection',
    sub_reasons: ['Must redo work', 'Waiting for re-inspection'],
    requires_trade_name: true,
    excusable: true,
  },
  OUT_OF_SQUARE: {
    label: 'Walls/plumbing out of square',
    sub_reasons: ['Walls not plumb', 'Floor not level', 'Plumbing in wrong position'],
    requires_trade_name: true,
    excusable: true,
  },
  MATERIAL_WAIT: {
    label: 'Waiting for material',
    sub_reasons: ['Our material late', 'Other trade material blocking', 'Wrong material delivered'],
    requires_trade_name: false,
    excusable: false,             // depends on whose material
  },
  DESIGN_CHANGE: {
    label: 'Design/drawing change',
    sub_reasons: ['New revision pending', 'RFI pending response', 'Scope change'],
    requires_trade_name: false,
    excusable: true,
  },
  WEATHER: {
    label: 'Weather related',
    sub_reasons: ['Rain (exterior)', 'Extreme cold', 'Wind (high floors)'],
    requires_trade_name: false,
    excusable: true,
  },
  SAFETY_HOLD: {
    label: 'Safety hold',
    sub_reasons: ['Incident investigation', 'Safety violation', 'Missing permits'],
    requires_trade_name: false,
    excusable: true,
  },
};
```

### Delay logging flow (Track)

```typescript
// Supervisor taps blocked area → selects reason → takes photo → submits

async function logDelay(params: {
  areaId: string;
  reasonCode: string;
  subReason?: string;
  blockingTrade?: string;
  description?: string;
  photoUri?: string;
  workersAffected: number;
}): Promise<void> {
  
  const gps = await getLocationStamp();
  const laborRate = await getOrgLaborRate();
  const manHoursLost = params.workersAffected * 8; // full day
  const costImpact = manHoursLost * laborRate;
  
  await db.execute(`
    INSERT INTO delay_logs 
    (id, project_id, organization_id, area_id, delay_date, 
     reason_code, sub_reason, blocking_trade, reason_detail,
     workers_affected, man_hours_lost, estimated_cost_impact,
     photo_urls, gps_latitude, gps_longitude, reported_by, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `, [
    crypto.randomUUID(), projectId, orgId, params.areaId,
    new Date().toISOString().split('T')[0],
    params.reasonCode, params.subReason, params.blockingTrade,
    params.description,
    params.workersAffected, manHoursLost, costImpact,
    JSON.stringify(params.photoUri ? [params.photoUri] : []),
    gps?.lat?.toString(), gps?.lng?.toString(),
    currentUserId, new Date().toISOString(),
  ]);
}
```

### Delay Impact Report (Web — auto-generated weekly)

```typescript
interface DelayImpactReport {
  project_id: string;
  period_start: string;
  period_end: string;
  
  total_crew_days_lost: number;
  total_man_hours_lost: number;
  total_cost_impact: number;
  
  by_cause: {
    reason_code: string;
    reason_label: string;
    crew_days: number;
    man_hours: number;
    cost: number;
    excusable: boolean;
    areas_affected: string[];
    photo_count: number;
  }[];
  
  by_trade: {
    trade: string;
    crew_days: number;
    cost: number;
  }[];
  
  by_floor: {
    floor: string;
    crew_days: number;
    cost: number;
  }[];
  
  // AI recommendations
  recommendations: string[];
  
  // For legal/contractual use
  documentation_summary: {
    total_photos: number;
    total_daily_logs: number;
    gps_verified_entries: number;
    date_range: string;
  };
}

// PDF export includes:
// - Company letterhead (from org.logo_url)
// - Summary table with totals
// - Breakdown by cause with excusable/non-excusable categorization
// - Photo evidence appendix
// - GPS verification stamps
// - "Powered by NotchField" footer
// - Ready for back-charge claims or time extension requests
```

---

## 4. Shared Infrastructure

Both Quality Gate and Ready Board share:

| Component | Shared By |
|-----------|-----------|
| Photo capture + offline queue | QC photos + Delay evidence photos |
| GPS location stamps | QC verification + Delay location proof |
| Area status system | QC status (pass/fail) + Readiness status (ready/blocked) |
| Push notifications | QC flags + Readiness alerts |
| PDF report generation | QC reports + Delay impact reports |
| Worker assignment data | QC per-worker tracking + Delay crew-days calculation |
| Gemini AI integration | QC photo analysis + Future: delay pattern recognition |

---

## 5. Trade-Specific QC Checklists

```typescript
const QC_CHECKLISTS: Record<string, QCChecklistItem[]> = {
  
  marble_floor: [
    { id: 'mf1', item: 'Surface condition', instruction: 'Photo of full floor area — check for scratches, chips, stains', required: true },
    { id: 'mf2', item: 'Lippage check', instruction: 'Close-up photo at tile joints — check edges are flush', required: true },
    { id: 'mf3', item: 'Grout lines', instruction: 'Photo of grout joints — check for gaps, consistency, color match', required: true },
    { id: 'mf4', item: 'Caulk joints', instruction: 'Photo of perimeter caulk — check for clean lines, no gaps', required: true },
    { id: 'mf5', item: 'Sealer application', instruction: 'Photo showing sealer sheen — check even coverage, no pooling', required: true },
    { id: 'mf6', item: 'Threshold/transitions', instruction: 'Photo of door threshold — check height transition, no trip hazard', required: false },
  ],
  
  marble_wall: [
    { id: 'mw1', item: 'Surface condition', instruction: 'Photo of each wall section — check for scratches, chips', required: true },
    { id: 'mw2', item: 'Grout lines', instruction: 'Close-up of grout — check straight lines, consistent width, no gaps', required: true },
    { id: 'mw3', item: 'Caulk at corners', instruction: 'Photo of inside corners — check clean caulk lines', required: true },
    { id: 'mw4', item: 'Plumb check', instruction: 'Photo showing wall is plumb — check no lean or bow', required: true },
    { id: 'mw5', item: 'Fixture cutouts', instruction: 'Photo around plumbing/fixtures — check clean cuts, proper clearance', required: false },
  ],
  
  tile_floor: [
    { id: 'tf1', item: 'Pattern alignment', instruction: 'Full floor photo — check pattern is straight and consistent', required: true },
    { id: 'tf2', item: 'Lippage', instruction: 'Close-up at joints — maximum 1/32" for rectified tile', required: true },
    { id: 'tf3', item: 'Grout coverage', instruction: 'Photo of grout lines — no voids, consistent color', required: true },
    { id: 'tf4', item: 'Slope (wet areas)', instruction: 'Photo showing drain area — water should flow to drain, 1/4" per foot', required: true },
    { id: 'tf5', item: 'Caulk at perimeter', instruction: 'Perimeter caulk clean and complete', required: true },
    { id: 'tf6', item: 'Mortar coverage', instruction: 'If accessible, verify 80%+ mortar coverage on back of tile', required: false },
  ],
  
  tile_wall: [
    { id: 'tw1', item: 'Layout/pattern', instruction: 'Full wall photo — check cuts are symmetric, pattern centered', required: true },
    { id: 'tw2', item: 'Grout lines', instruction: 'Grout straight and consistent', required: true },
    { id: 'tw3', item: 'Inside corners', instruction: 'Caulk (not grout) at inside corners', required: true },
    { id: 'tw4', item: 'Edge trim', instruction: 'Photo of exposed edges — check trim is straight and secure', required: true },
    { id: 'tw5', item: 'Plumb', instruction: 'Wall surface is plumb', required: true },
  ],
  
  drywall: [
    { id: 'dw1', item: 'Surface smooth', instruction: 'Raking light photo — check no ridges, bumps, tool marks', required: true },
    { id: 'dw2', item: 'Joints invisible', instruction: 'Photo at seam locations — tape joints should be invisible', required: true },
    { id: 'dw3', item: 'Corners clean', instruction: 'Inside and outside corners — check straight, no cracks', required: true },
    { id: 'dw4', item: 'No cracks', instruction: 'Full wall photo — check no cracks especially at corners and openings', required: true },
    { id: 'dw5', item: 'Screw pops', instruction: 'Check no visible screw heads or dimples', required: true },
  ],
  
  paint: [
    { id: 'pt1', item: 'Coverage', instruction: 'Full wall photo — check even coverage, no thin spots', required: true },
    { id: 'pt2', item: 'Cut lines', instruction: 'Close-up at trim/ceiling line — check straight cut', required: true },
    { id: 'pt3', item: 'No drips/runs', instruction: 'Check for drips, runs, sags', required: true },
    { id: 'pt4', item: 'Color match', instruction: 'Photo with color sample — check match', required: true },
    { id: 'pt5', item: 'Protection', instruction: 'Check no paint on floors, fixtures, windows', required: true },
  ],
};
```

---

## 6. AI Analysis Patterns

```typescript
// Gemini prompt for QC photo analysis
const QC_ANALYSIS_PROMPT = `You are a construction quality control inspector specializing in {trade}.

Analyze this photo of {checklist_item} in a {area_type}.

Check for these specific defects:
{defect_checklist_for_trade}

For each issue found, respond with:
- defect_type: specific defect code
- severity: minor (cosmetic), major (functional), critical (must fix)
- description: what you see and where in the image
- confidence: 0.0 to 1.0

If no issues are found, respond with an empty issues array.

Be conservative — only flag clear, visible issues. When in doubt, mark as minor.
Construction photos are often taken in poor lighting conditions — account for shadows.`;

// Defect types per trade
const DEFECT_TYPES = {
  marble: ['grout_gap', 'grout_missing', 'lippage', 'scratch', 'chip', 'crack', 'stain', 'sealer_uneven', 'caulk_gap', 'wrong_color'],
  tile: ['grout_gap', 'lippage', 'pattern_misalign', 'cracked_tile', 'uneven_spacing', 'caulk_missing', 'edge_trim_loose', 'mortar_squeeze'],
  drywall: ['joint_visible', 'screw_pop', 'crack', 'bump', 'corner_damage', 'tape_bubble', 'uneven_surface'],
  paint: ['thin_coverage', 'drip', 'cut_line_crooked', 'wrong_color', 'roller_marks', 'brush_marks', 'overspray'],
};
```

---

## 7. Data Model

```sql
-- QC submissions (foreman submits, AI analyzes)
CREATE TABLE qc_submissions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  area_id UUID NOT NULL,
  trade TEXT NOT NULL,
  status TEXT DEFAULT 'submitted',
  photos JSONB NOT NULL,
  ai_results JSONB,
  ai_analyzed_at TIMESTAMPTZ,
  submitted_by UUID REFERENCES profiles(id),
  worker_id UUID REFERENCES profiles(id),
  resolved_by UUID REFERENCES profiles(id),
  resolved_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- QC defects (individual issues)
CREATE TABLE qc_defects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  qc_submission_id UUID NOT NULL REFERENCES qc_submissions(id),
  defect_type TEXT NOT NULL,
  severity TEXT DEFAULT 'minor',
  description TEXT,
  photo_index INTEGER,
  confidence NUMERIC,
  worker_id UUID REFERENCES profiles(id),
  status TEXT DEFAULT 'open',
  fixed_by UUID REFERENCES profiles(id),
  fixed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Area readiness (Ready Board)
CREATE TABLE area_readiness (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  area_id UUID NOT NULL,
  status TEXT NOT NULL,
  trade_sequence JSONB,
  blocking_trade TEXT,
  estimated_ready_date DATE,
  last_checked_at TIMESTAMPTZ DEFAULT now(),
  checked_by UUID REFERENCES profiles(id)
);

-- Delay logs (documented daily)
CREATE TABLE delay_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  area_id UUID NOT NULL,
  delay_date DATE NOT NULL DEFAULT CURRENT_DATE,
  reason_code TEXT NOT NULL,
  sub_reason TEXT,
  blocking_trade TEXT,
  reason_detail TEXT,
  workers_affected INTEGER,
  man_hours_lost NUMERIC,
  estimated_cost_impact NUMERIC,
  photo_urls TEXT[],
  gps_latitude NUMERIC,
  gps_longitude NUMERIC,
  reported_by UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ DEFAULT now()
);

-- Delay impact reports (auto-generated)
CREATE TABLE delay_impact_reports (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  report_period_start DATE NOT NULL,
  report_period_end DATE NOT NULL,
  total_crew_days_lost NUMERIC,
  total_man_hours_lost NUMERIC,
  total_cost_impact NUMERIC,
  breakdown_by_cause JSONB,
  breakdown_by_trade JSONB,
  breakdown_by_floor JSONB,
  recommendations JSONB,
  photo_count INTEGER,
  generated_at TIMESTAMPTZ DEFAULT now()
);

-- Trade sequences (per organization, per project type)
CREATE TABLE trade_sequences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  project_type TEXT NOT NULL,
  sequence JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(organization_id, project_type)
);
```

---

## 8. Implementation

| Component | App | Phase |
|-----------|-----|-------|
| QC photo checklist UI | Track (Production area drawer) | Phase T2 |
| QC submission flow | Track | Phase T2 |
| Background AI analysis | Server (Edge Function + Gemini) | Phase T3 |
| QC push notifications | Track | Phase T3 |
| QC analytics dashboard | Web PM Module | Fase 7 |
| Worker QC fail rate tracking | Web PM Module | Fase 7 |
| Ready Board view | Track (Operations tab) | Phase T2 |
| Trade sequence configuration | Web PM Module | Fase 7 |
| Prior trade status input | Track (quick tap interface) | Phase T2 |
| Delay logging | Track (Operations tab) | Phase T2 |
| Delay Impact Report PDF | Web PM Module | Fase 7 |
| Delay pattern recognition (AI) | Server | Phase T3 |
