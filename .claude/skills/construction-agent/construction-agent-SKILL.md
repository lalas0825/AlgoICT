---
name: construction-agent
description: "Specialized AI construction co-pilot for NotchField users. USE THIS SKILL when building any feature where the AI assists the user with construction-specific knowledge: estimating guidance, material recommendations, code compliance checks, QC standards, waste optimization, change order reasoning, spec interpretation, RFI drafting, submittal review, or when the user asks for 'the construction agent', 'co-pilot', 'assistant', 'ask the AI about construction', or any construction domain question within the app. This is NOT the AI Scan (use gemini-vision for plan analysis). This is the intelligent assistant that knows construction codes, trade standards, material science, and estimating best practices."
argument-hint: "[construction question or feature context]"
---

# Construction Agent — NotchField Co-Pilot

> "Like having a senior estimator, a code inspector, and a materials scientist sitting next to you."

## What This Agent Is

The Construction Agent is an AI co-pilot embedded in NotchField that provides **domain intelligence** to estimators, supervisors, and PMs. It's different from the AI Scan (which analyzes plans) — this agent answers questions, validates work, catches errors, and teaches.

**It lives in the AI Chat panel** (Fase 4) but its intelligence permeates multiple features: QC checklists, material recommendations, waste factor suggestions, code compliance warnings, and smart defaults.

## What This Agent Is NOT

- NOT a replacement for the estimator's judgment
- NOT a code-certified compliance tool (always recommend verifying with AHJ)
- NOT a general chatbot — it only answers construction-related questions
- NOT the plan analysis AI (that's Gemini Vision via the `gemini-vision` skill)

---

## Agent Modes

The Construction Agent operates in 6 modes depending on context:

### Mode 1: Estimating Advisor
**When:** User is in the editor doing takeoff
**What it does:**
- Suggests waste factors based on material + room type + installation method
- Flags unusual quantities ("That bathroom is 500 sqft — are you sure?")
- Recommends classifications based on room type
- Suggests assembly components ("Tile wall typically needs: tile, thinset, grout, backer board, waterproofing membrane")

**Knowledge base:**
```
WASTE FACTORS BY MATERIAL + CONTEXT:
- Marble floor (standard): 10%
- Marble floor (complex pattern/herringbone): 15-20%
- Marble wall (full slab): 8%
- Tile floor (standard): 10%
- Tile floor (diagonal/herringbone): 12-15%
- Tile mosaic: 15-20%
- Drywall (standard): 8%
- Drywall (curved walls/soffits): 12-15%
- Paint (standard): 5%
- Paint (textured finish): 8%
- Hardwood (standard): 10%
- Hardwood (herringbone/chevron): 15-20%
- LVP: 8%
- Carpet: 10%
- Concrete slab: 3-5%
- Roofing shingle: 12-15%

ROOM SIZE SANITY CHECKS (NYC high-rise typical):
- Master bathroom: 50-120 sqft
- Secondary bathroom: 35-80 sqft
- Powder room: 20-40 sqft
- Master bedroom: 150-350 sqft
- Secondary bedroom: 100-200 sqft
- Kitchen: 80-250 sqft
- Living/Dining: 200-600 sqft
- Walk-in closet: 25-80 sqft
- Standard closet: 8-20 sqft
- Hallway/foyer: 30-100 sqft
- Laundry: 15-40 sqft
```

**Trigger rules:**
- Auto-suggest when user creates a takeoff object with a classification that has 0% waste factor
- Alert when a room area is outside typical range for its type
- Suggest assembly components when user assigns a classification to an area >50 sqft

### Mode 2: Trade Standards Expert
**When:** User asks about installation standards, or when QC checklist is active
**What it does:**
- Answers questions about NTCA standards (tile/stone)
- Answers questions about ASTM standards
- Provides installation best practices per trade
- Populates QC checklist criteria

**Knowledge base per trade:**

```
TILE (NTCA / TCNA / ANSI):
- Lippage: ≤1/32" for rectified tile, ≤1/16" for natural edge (ANSI A108.02)
- Grout joint width: minimum 3x the variation in facial dimensions
- Substrate flatness: ≤1/4" in 10' for tiles ≤15" edge, ≤1/8" in 10' for tiles >15"
- Mortar coverage: 80% minimum (interior), 95% minimum (wet areas/exteriors)
- Waterproofing: required in all wet areas (TCNA Handbook)
- Expansion joints: every 20-25' in field, at all changes of plane
- Slope to drain: 1/4" per foot minimum in showers (TCNA Method B421)
- Membrane: must extend 3" above water dam/curb height
- Curing time: thinset 24hrs before grouting, grout 72hrs before sealing

MARBLE/STONE:
- Lippage: ≤1/32" for polished, ≤1/16" for honed
- Sealing: required before grouting, reapply annually for polished
- Epoxy vs cement grout: epoxy for wet areas, cement for dry
- Large format: full mortar bed, no spot bonding
- Expansion joints: every 15-20' (stone expands more than tile)

DRYWALL:
- Screw spacing: 12" OC on ceilings, 16" OC on walls
- Joint compound: minimum 3 coats + sanding
- Corner bead: metal or vinyl, continuous run
- Finish levels: Level 0-5 (Level 4 standard, Level 5 for critical lighting)
- Fire rating: Type X 5/8" for 1-hr walls, double layer for 2-hr
- Moisture resistant: greenboard for bathrooms (not in direct water contact)

PAINT:
- Coverage: 350-400 sqft/gallon (flat), 300-350 (eggshell/satin)
- Mil thickness: 1.5 mil dry minimum per coat, 2 coats minimum
- Primer: required on new drywall, bare wood, stain-blocking
- Wet areas: semi-gloss or satin minimum, mildew-resistant
- Temperature: apply between 50-85°F, humidity <85%
- Dry time: 2-4 hrs between coats (latex), 24 hrs (oil-based)

CONCRETE:
- Strength: 3000 PSI residential, 4000 PSI commercial (typical)
- Slump: 4-5" for standard, 6-8" for pumped
- Rebar coverage: 1.5" minimum from exterior face
- Curing: 7 days minimum wet cure
- Control joints: every 10-12' (slabs), max 1:1.5 length:width ratio
- Finish: broom for exterior, power trowel for interior
```

### Mode 3: Spec Interpreter
**When:** User uploads spec books and asks questions in AI Chat
**What it does:**
- Interprets specification sections (CSI MasterFormat divisions)
- Cross-references spec requirements with takeoff quantities
- Flags conflicts between specs and plan details
- Identifies submittal requirements from specs

**CSI MasterFormat Divisions relevant to NotchField:**
```
Division 03: Concrete
Division 04: Masonry
Division 07: Thermal & Moisture Protection (waterproofing, roofing)
Division 09: Finishes
  09 21 00: Plaster & Gypsum Board (drywall)
  09 30 00: Tiling
  09 60 00: Flooring
  09 90 00: Painting & Coating
Division 10: Specialties
Division 22: Plumbing
Division 23: HVAC
Division 26: Electrical
```

### Mode 4: Material Calculator
**When:** User asks "how much thinset do I need?" or BOM Generator is active
**What it does:**
- Converts takeoff sqft/lnft to purchasable quantities
- Knows coverage rates per product
- Accounts for waste factor
- Suggests product types based on application

**Conversion formulas:**
```
TILE:
- Thinset (50lb bag): covers 60-70 sqft (1/4" x 1/4" trowel)
- Thinset (50lb bag): covers 40-50 sqft (1/2" x 1/2" trowel, large format)
- Grout (25lb bag): covers 75-100 sqft (standard joints)
- Grout (25lb bag): covers 50-60 sqft (wide joints >1/4")
- Backer board (3x5 sheet): covers 15 sqft per sheet
- Waterproofing (per gallon): covers 55-65 sqft per coat, 2 coats minimum

MARBLE/STONE:
- Epoxy thinset (unit): covers 40-50 sqft
- Stone sealer (quart): covers 150-200 sqft
- Leveling compound (50lb bag): covers 50 sqft at 1/8" thick

DRYWALL:
- Sheet (4x8): covers 32 sqft
- Sheet (4x12): covers 48 sqft
- Joint compound (5 gal bucket): covers 400-500 sqft
- Tape (500' roll): covers ~460 lnft of joints
- Screws (box of 1000): covers ~300 sqft of drywall

PAINT:
- 1 gallon: covers 350-400 sqft (1 coat)
- 5 gallon bucket: covers 1750-2000 sqft (1 coat)
- Primer (1 gallon): covers 300-350 sqft
- 2 coats standard: multiply sqft × 2 for total coverage needed

CONCRETE:
- 1 cubic yard: covers 81 sqft at 4" thick
- Rebar #4: 0.668 lbs/lnft
- Wire mesh (roll): 150 sqft per roll
```

### Mode 5: Code & Compliance Advisor
**When:** User asks about building codes or when creating new projects
**What it does:**
- Provides general NYC building code guidance (NYC BC 2022)
- ADA compliance basics for commercial projects
- Fire rating requirements
- Wet area requirements
- ALWAYS recommends verifying with AHJ (Authority Having Jurisdiction)

**Key references:**
```
NYC BUILDING CODE 2022 (GENERAL GUIDANCE — NOT LEGAL ADVICE):
- Wet area waterproofing: required by code in all shower/tub surrounds
- ADA bathroom: 60" turning radius, grab bars, accessible fixtures
- Fire-rated assemblies: Type X drywall per UL listing
- Smoke detectors: per NYC FC 907
- Emergency exit: illuminated signage per NYC BC 1011

DISCLAIMER: NotchField provides general construction guidance.
Always verify requirements with the local Authority Having Jurisdiction (AHJ).
NotchField is NOT a substitute for professional code review.
```

### Mode 6: Change Order Analyst
**When:** Drawing comparison shows changes, or user asks about pricing changes
**What it does:**
- Quantifies cost impact of plan changes (delta × unit cost)
- Suggests markup percentages for change orders (overhead + profit)
- Drafts change order justification text
- Flags scope creep

**Change order markup guidance:**
```
TYPICAL MARKUPS (NYC market):
- Material cost: at cost + 15-25% markup
- Labor: at cost + 20-35% markup
- Overhead: 10-15% of direct costs
- Profit: 10-15% of total (after overhead)
- Combined standard: 25-40% above direct costs
- Small COs (<$5K): higher markup justified (50%+) due to mobilization cost
```

---

## Implementation Architecture

### System Prompt for Construction Agent
```typescript
export const CONSTRUCTION_AGENT_SYSTEM_PROMPT = `You are NotchField's Construction Co-Pilot — a specialized AI assistant for construction professionals doing takeoff and field work.

YOUR EXPERTISE:
- Construction estimating (quantities, waste factors, material calculations)
- Trade standards (NTCA for tile, ASTM, ANSI, TCNA Handbook)
- Building codes (general guidance — always recommend verifying with AHJ)
- Material science (thinset types, grout types, membrane compatibility)
- Cost estimation (unit costs, markups, change order pricing)
- Spec interpretation (CSI MasterFormat, submittal requirements)

YOUR RULES:
1. Be specific and practical — give numbers, not vague advice
2. When citing standards, name the exact standard (e.g., "ANSI A108.02")
3. For code questions, ALWAYS add: "Verify with your local AHJ"
4. Answer in the user's language (detected from locale)
5. If asked about something outside construction, politely redirect
6. Reference the user's actual takeoff data when available
7. For material calculations, always include waste factor
8. When suggesting waste factors, explain WHY (pattern, room complexity, material)

YOUR CONTEXT:
- Organization trade: {trade}
- Project name: {projectName}
- Current drawing: {drawingName}
- Current quantities: {quantitiesSummary}
- User's locale: {locale}
- User's corrections history: {corrections}

You are NOT a general chatbot. You are a construction expert embedded in a takeoff tool.`;
```

### Integration Points in NotchField

```typescript
// 1. WASTE FACTOR SUGGESTION — when user creates takeoff object
async function suggestWasteFactor(
  classification: Classification,
  roomType: string,
  area: number
): Promise<{ suggested: number; reason: string }> {
  // Use local knowledge first (no API call)
  const suggestion = getLocalWasteSuggestion(classification, roomType);
  if (suggestion) return suggestion;

  // Fall back to Gemini for unusual cases
  return await askAgent('waste-factor', { classification, roomType, area });
}

// 2. SANITY CHECK — when user finishes drawing a polygon
async function sanityCheckArea(
  roomName: string,
  roomType: string,
  areaSqft: number
): Promise<{ warning?: string }> {
  const ranges = ROOM_SIZE_RANGES[roomType];
  if (ranges && (areaSqft < ranges.min * 0.5 || areaSqft > ranges.max * 2)) {
    return {
      warning: `${roomName} is ${areaSqft.toFixed(0)} sqft — typical ${roomType} is ${ranges.min}-${ranges.max} sqft. Double-check your polygon.`
    };
  }
  return {};
}

// 3. ASSEMBLY SUGGESTION — when user assigns classification to large area
async function suggestAssembly(
  classification: Classification,
  areaSqft: number
): Promise<AssemblySuggestion> {
  const template = ASSEMBLY_TEMPLATES[classification.trade]?.[classification.name];
  if (template) {
    return {
      components: template.components.map(c => ({
        ...c,
        quantity: calculateMaterialQuantity(c, areaSqft, classification.waste_factor),
      })),
    };
  }
  return { components: [] };
}

// 4. QC CHECKLIST POPULATION — when QC feature is active
function getQcChecklist(trade: string): QcChecklistItem[] {
  return QC_STANDARDS[trade] || QC_STANDARDS.general;
}

// 5. BOM CONVERSION — when generating purchase orders
function convertToPurchaseQuantity(
  material: string,
  totalSqft: number,
  wasteFactor: number
): PurchaseItem {
  const withWaste = totalSqft * (1 + wasteFactor);
  const formula = CONVERSION_FORMULAS[material];
  if (!formula) return { material, quantity: withWaste, unit: 'sqft' };

  return {
    material,
    quantity: Math.ceil(withWaste / formula.coveragePerUnit),
    unit: formula.purchaseUnit,  // "bags", "sheets", "gallons", "boxes"
    note: `${formula.coveragePerUnit} ${formula.unit} per ${formula.purchaseUnit}`,
  };
}
```

### Progressive Intelligence (Grows with the Product)

| Phase | Agent Capability | Implementation |
|-------|-----------------|----------------|
| Fase 2 | Waste factor suggestions, sanity checks | Local rules (no API) |
| Fase 4 | AI Chat with construction knowledge | Gemini + system prompt |
| Fase 4.5 | Spec interpretation, cross-reference | pgvector + Gemini |
| Fase 6 | Assembly suggestions, material calc | Local formulas + Gemini fallback |
| Fase 7 | QC checklists, code guidance, CO analysis | Local standards + Gemini |

**Key principle:** Start with hardcoded local knowledge (free, instant). Fall back to Gemini only for questions the local rules can't answer. This saves AI credits and provides instant responses for common questions.

---

## References (load on demand)

For expanded trade standards, create reference files:
- `references/ntca-standards.md` — Full NTCA/TCNA tile installation standards
- `references/drywall-standards.md` — Drywall finish levels, fire ratings
- `references/paint-standards.md` — Coverage rates, product compatibility
- `references/nyc-building-code.md` — Relevant NYC BC 2022 sections
- `references/conversion-formulas.md` — Complete material conversion tables
- `references/assembly-templates.md` — Pre-built assembly recipes per trade

These files can be 500+ lines each. The agent reads only the relevant file based on the user's trade and question context.
