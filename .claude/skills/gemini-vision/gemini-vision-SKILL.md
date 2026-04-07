---
name: gemini-vision
description: "AI plan analysis integration using Google Gemini 3.1 Pro for NotchField construction takeoff. USE THIS SKILL whenever implementing AI features for plan analysis, building the AI Scan button, AI Image Search (bounding box pattern matching), AI Chat with plans, AI-guided takeoff checklist, or the AI feedback/correction loop. Triggers include: any mention of 'AI scan', 'AI takeoff', 'Gemini', 'plan analysis', 'room detection', 'fixture detection', 'AI chat', 'image search', 'pattern search', 'bounding box search', 'AI credits', 'ai_training_feedback', or 'guided takeoff'. This skill contains the exact prompts, response schemas, parser patterns, and real-world test results from W8 floor plan testing (March 2026)."
---

# Gemini Vision — AI Plan Analysis for NotchField

> Tested March 16, 2026 with real W8 floor plan from Jantile Group NYC high-rise.
> Gemini 3.1 Pro correctly identified 16 rooms, bathroom types, fixtures, and HVAC.

## Table of Contents
1. Model Configuration
2. AI Scan (Room Detection)
3. AI Guided Takeoff Checklist
4. AI Image Search
5. AI Chat
6. Feedback Loop
7. Credits & Rate Limiting
8. What Gemini CAN and CANNOT Do

---

## 1. Model Configuration

### API Setup
```typescript
// src/features/ai/config.ts
export const GEMINI_CONFIG = {
  model: 'gemini-3.1-pro-preview',
  apiEndpoint: 'https://generativelanguage.googleapis.com/v1beta',
  pricing: {
    input: 2.00,    // $ per million tokens
    output: 12.00,  // $ per million tokens
  },
  contextWindow: 1_000_000,  // 1M tokens — can send entire plan set
  maxOutputTokens: 8192,
};
```

### Vercel AI SDK Integration
```typescript
// src/features/ai/gemini-client.ts
import { createGoogleGenerativeAI } from '@ai-sdk/google';

const google = createGoogleGenerativeAI({
  apiKey: process.env.GOOGLE_AI_API_KEY!,
});

export const geminiPro = google('gemini-3.1-pro-preview');
```

### API Route Pattern
```typescript
// src/app/api/ai/takeoff/route.ts
import { generateObject } from 'ai';
import { geminiPro } from '@/features/ai/gemini-client';
import { z } from 'zod';

export async function POST(req: Request) {
  const { imageBase64, classifications, projectContext } = await req.json();

  // Check AI credits
  // ...

  const result = await generateObject({
    model: geminiPro,
    schema: aiScanResponseSchema,  // Zod schema
    messages: [
      { role: 'system', content: AI_SCAN_SYSTEM_PROMPT },
      {
        role: 'user',
        content: [
          { type: 'image', image: imageBase64 },
          { type: 'text', text: buildUserPrompt(classifications, projectContext) },
        ],
      },
    ],
  });

  // Deduct AI credit
  // ...

  return Response.json(result.object);
}
```

---

## 2. AI Scan (Room Detection)

### System Prompt
```typescript
export const AI_SCAN_SYSTEM_PROMPT = `You are an expert construction estimator specializing in finishes (marble, tile, drywall, paint, concrete, flooring, roofing, electrical, plumbing, HVAC).

Analyze this architectural floor plan and detect:

1. ROOMS: Every distinct space including closets, WICs, hallways, utility rooms
   - Name using the exact label visible on the plan (e.g., "PB-7.0", "BR 1", "LR/DR/K")
   - If no label is visible, assign a descriptive name (e.g., "Walk-In Closet near BR 1")
   - Classify the likely finish type based on room type and standard construction practice
   - Rate your confidence from 0.0 to 1.0

2. FIXTURES: Every plumbing fixture, appliance, and equipment
   - Type: toilet, vanity (single/double), bathtub, shower, sink, cooktop, refrigerator, dishwasher, washer, dryer, HVAC unit
   - Location: which room it belongs to

3. WALLS: Wall segments with classification
   - Type: exterior, interior partition, demising (between units)
   - Notable features: windows, structural columns

4. DOORS: Every door with type
   - Type: swing, sliding, pocket, double

Be EXHAUSTIVE. Do not skip small spaces like closets, utility rooms, or corridors.
For bathroom types, use the exact designation from the plan (PB, SB, PR, TYPE A, etc.).`;
```

### User Prompt Builder
```typescript
function buildUserPrompt(
  classifications: Classification[],
  projectContext?: { corrections: AiFeedback[], trade: string }
): string {
  let prompt = `Analyze this floor plan. The organization works in ${projectContext?.trade || 'general construction'}.

Available classifications for this organization:
${classifications.map(c => `- ${c.name} (${c.unit}, ${c.trade})`).join('\n')}

For each room detected, suggest which classification best matches.`;

  // Include past corrections for this project (Feedback Loop)
  if (projectContext?.corrections?.length) {
    prompt += `\n\nIMPORTANT — Past corrections by the user on this project:
${projectContext.corrections.map(c =>
  `- Room "${c.ai_prediction.room}": AI predicted "${c.ai_prediction.predicted_class}" but user corrected to "${c.user_correction.corrected_class}"`
).join('\n')}
Apply these corrections to similar rooms in this analysis.`;
  }

  return prompt;
}
```

### Response Schema (Zod)
```typescript
export const aiScanResponseSchema = z.object({
  rooms: z.array(z.object({
    name: z.string().describe('Room name from plan label or descriptive'),
    type: z.string().describe('Room type: bathroom, bedroom, kitchen, closet, hallway, utility, living'),
    finish_type: z.string().describe('Suggested finish classification'),
    suggested_classification_id: z.string().optional().describe('Best matching classification ID'),
    fixtures: z.array(z.object({
      type: z.string(),
      detail: z.string().optional(),
    })).describe('Fixtures in this room'),
    confidence: z.number().min(0).max(1),
  })),
  walls: z.array(z.object({
    type: z.enum(['exterior', 'interior', 'demising']),
    location: z.string().describe('Which side or between which rooms'),
    features: z.array(z.string()).optional(),
    confidence: z.number().min(0).max(1),
  })),
  doors: z.array(z.object({
    type: z.string(),
    between: z.string().describe('Between which rooms'),
    confidence: z.number().min(0).max(1),
  })),
  summary: z.object({
    total_rooms: z.number(),
    total_bathrooms: z.number(),
    total_fixtures: z.number(),
    total_doors: z.number(),
  }),
});

export type AiScanResponse = z.infer<typeof aiScanResponseSchema>;
```

---

## 3. AI Guided Takeoff Checklist

The AI Scan response gets converted into a checklist the estimator works through:

```typescript
// src/features/ai/parsers/scanToChecklist.ts

interface ChecklistItem {
  id: string;
  roomName: string;
  roomType: string;
  suggestedClassification: string;
  suggestedClassificationId?: string;
  fixtures: string[];
  confidence: number;
  status: 'pending' | 'drawn' | 'skipped';
}

function scanToChecklist(scan: AiScanResponse, classifications: Classification[]): ChecklistItem[] {
  return scan.rooms.map((room, i) => ({
    id: `room-${i}`,
    roomName: room.name,
    roomType: room.type,
    suggestedClassification: room.finish_type,
    suggestedClassificationId: room.suggested_classification_id
      || findBestMatch(room.finish_type, classifications)?.id,
    fixtures: room.fixtures.map(f => `${f.type}${f.detail ? ` (${f.detail})` : ''}`),
    confidence: room.confidence,
    status: 'pending',
  }));
}
```

### Checklist UI Behavior
1. Checklist panel appears on the left after AI Scan completes
2. Each item shows: room name, suggested classification (color dot), fixture count, confidence %
3. User clicks an item → classification auto-selects in the editor → user draws polygon
4. After drawing, item automatically marks as "drawn" ✅
5. User can skip items (mark as "skipped" ⏭️)
6. User can change the suggested classification before drawing
7. Progress bar at top: "8/16 rooms drawn (50%)"

---

## 4. AI Image Search

### Flow
1. User activates "Image Search" mode in toolbar
2. User draws a bounding box around a symbol/fixture on the plan
3. That crop is sent to Gemini with the full plan set
4. Gemini returns locations of matching patterns across all pages

### API Route
```typescript
// src/app/api/ai/image-search/route.ts
export async function POST(req: Request) {
  const { boundingBoxImage, planPages, description } = await req.json();

  const result = await generateObject({
    model: geminiPro,
    schema: imageSearchResponseSchema,
    messages: [
      {
        role: 'system',
        content: `You are a construction plan pattern matcher. The user has selected a specific symbol or fixture from a construction plan. Find ALL instances of this same symbol/fixture across the provided plan pages. Return the page number and approximate location for each match.`
      },
      {
        role: 'user',
        content: [
          { type: 'text', text: `Find all instances of this pattern: ${description || 'the selected symbol'}` },
          { type: 'image', image: boundingBoxImage },
          { type: 'text', text: 'Search across these plan pages:' },
          ...planPages.map((page: string, i: number) => ([
            { type: 'text', text: `Page ${i + 1}:` },
            { type: 'image', image: page },
          ])).flat(),
        ],
      },
    ],
  });

  return Response.json(result.object);
}
```

### Response Schema
```typescript
const imageSearchResponseSchema = z.object({
  pattern_description: z.string().describe('What the AI thinks the pattern is'),
  matches: z.array(z.object({
    page_number: z.number(),
    location_description: z.string().describe('Where on the page, e.g. "top-left near BR 1"'),
    confidence: z.number().min(0).max(1),
  })),
  total_count: z.number(),
});
```

### Converting to Classification
After search results return, user can:
1. Click "Create Count Classification" → creates new classification with count = total_count
2. Click individual matches to add count markers at approximate locations
3. Edit/remove false positives

---

## 5. AI Chat

### Two-Tier Architecture
```
User question
    │
    ├── Can be answered from local data? (quantities, classifications)
    │   └── YES → Answer immediately (FREE, no AI credits)
    │       Examples: "How many sqft of marble?", "What's the total cost?"
    │
    └── Requires plan interpretation or document search?
        └── YES → Send to Gemini (consumes AI credits)
            Examples: "How many bathrooms in this unit?", "What does spec say about grout?"
```

### Local Answer Detection
```typescript
function canAnswerLocally(message: string, quantities: QuantityGroup[]): boolean {
  const localPatterns = [
    /how much|how many|total|sum/i,
    /cost|price|budget|estimate/i,
    /sqft|square feet|linear feet|count/i,
    /waste|waste factor/i,
    /classification|category/i,
  ];
  return localPatterns.some(p => p.test(message));
}

function generateLocalAnswer(message: string, quantities: QuantityGroup[], locale: string): string {
  // Parse intent and compute answer from quantities data
  // Return answer in user's locale language
  // This is FREE — no API call needed
}
```

### Gemini Chat with Context
```typescript
// For questions requiring plan analysis
const messages = [
  {
    role: 'system',
    content: `You are an AI assistant for a construction takeoff tool. You can see the current floor plan and know the quantities already measured. Answer in ${locale} language.

Current quantities:
${quantities.map(q => `- ${q.classification.name}: ${q.totalArea} sqft / ${q.totalLength} lnft / ${q.totalCount} count`).join('\n')}

Answer concisely. If referencing a document, cite the page number.`,
  },
  {
    role: 'user',
    content: [
      { type: 'image', image: currentDrawingBase64 },
      { type: 'text', text: userMessage },
    ],
  },
];
```

### Multi-Document Search (Fase 4.5)
When user uploads spec books, contracts, schedules:
1. Documents are chunked and embedded with pgvector on upload
2. Chat queries search across all project documents
3. Results include clickable page references

```typescript
// Vector search for relevant document chunks
const { data: chunks } = await supabase.rpc('match_documents', {
  query_embedding: await embedText(userMessage),
  match_threshold: 0.7,
  match_count: 5,
  project_id: projectId,
});

// Include relevant chunks in Gemini context
const context = chunks.map(c => `[${c.document_name}, Page ${c.page_number}]: ${c.content}`).join('\n');
```

---

## 6. Feedback Loop

### Recording Corrections
When the user changes an AI-suggested classification:

```typescript
async function recordAiCorrection(
  supabase: SupabaseClient,
  params: {
    orgId: string;
    projectId: string;
    drawingId: string;
    roomName: string;
    predictedClass: string;
    correctedClass: string;
    boundingBox?: [number, number][];
    canvasObjects: any[];  // snapshot of current canvas state
  }
) {
  await supabase.from('ai_training_feedback').insert({
    organization_id: params.orgId,
    project_id: params.projectId,
    drawing_id: params.drawingId,
    ai_prediction: {
      room: params.roomName,
      predicted_class: params.predictedClass,
    },
    user_correction: {
      corrected_class: params.correctedClass,
    },
    bounding_box: params.boundingBox,
    canvas_state_after: { objects: params.canvasObjects },
    created_by: (await supabase.auth.getUser()).data.user?.id,
  });
}
```

### Using Corrections in Future Scans
Before each AI Scan, load corrections for the current project:

```typescript
const { data: corrections } = await supabase
  .from('ai_training_feedback')
  .select('ai_prediction, user_correction')
  .eq('project_id', projectId)
  .order('created_at', { ascending: false })
  .limit(20);

// Pass corrections to buildUserPrompt() — see Section 2
```

This creates a learning loop: the more the user corrects, the better future scans become for that project. Corrections are project-scoped, not global.

---

## 7. Credits & Rate Limiting

### Credit System
| Plan | AI Credits/Month | Approx. Scans |
|------|-----------------|---------------|
| Starter | 50 | ~15 full-page scans |
| Pro | 200 | ~60 scans |
| Team | 500 | ~150 scans |

### Cost Per Operation (approximate)
| Operation | Input Tokens | Output Tokens | Cost | Credits |
|-----------|-------------|---------------|------|---------|
| AI Scan (1 page) | ~2,000 | ~1,500 | ~$0.022 | 3 |
| AI Image Search (10 pages) | ~20,000 | ~500 | ~$0.046 | 5 |
| AI Chat (1 question) | ~3,000 | ~500 | ~$0.012 | 1 |
| Local Chat (quantities) | 0 | 0 | $0 | 0 (FREE) |

### Enforcement
```typescript
async function checkAndDeductCredits(orgId: string, cost: number): Promise<boolean> {
  const { data: org } = await supabase
    .from('organizations')
    .select('ai_credits_remaining')
    .eq('id', orgId)
    .single();

  if (!org || org.ai_credits_remaining < cost) return false;

  await supabase
    .from('organizations')
    .update({ ai_credits_remaining: org.ai_credits_remaining - cost })
    .eq('id', orgId);

  return true;
}
```

---

## 8. What Gemini CAN and CANNOT Do

### ✅ CAN (confirmed March 2026 with real plans)
- Identify rooms with correct names from plan labels (PB-7.0, SB-7.0, B-1.0 TYPE A, PR-2.0)
- Classify room types (Primary Bathroom, Powder Room, Walk-In Closet, Hallway/Gallery)
- Detect kitchen fixtures: island, countertops, sink, cooktop, refrigerator, cabinetry
- Detect bathroom fixtures: double vanity, single vanity, toilet, bathtub, walk-in shower, combo tub/shower
- Identify HVAC units (R-2.1), structural columns, windows (W1-W5)
- Classify walls: exterior (with orientation), demising, interior partitions
- Detect doors with type
- Understand bathroom naming conventions (PB=Primary Bath, SB=Secondary, PR=Powder Room)
- Work with complex multi-unit floor plans when focused on one apartment
- Process plans with OCR text, dimension lines, and architectural annotations

### ❌ CANNOT (confirmed limitations)
- Produce precise polygon coordinates for room boundaries
- Calculate accurate square footage from visual analysis alone
- Replace manual polygon drawing by the estimator
- Handle entire floor plans with 30+ apartments at once (must focus on sections)
- Consistently detect ALL rooms in a very busy plan (typically 60-80% detection rate on full floors)
- Read very small text or low-resolution plans reliably

### Strategy Implications
- **AI assists, human draws.** The AI's job is to IDENTIFY and CLASSIFY, not to DRAW.
- **Section-by-section is better.** For large plans, prompt Gemini to focus on one apartment/area at a time.
- **Corrections improve results.** The feedback loop makes each subsequent scan on the same project better.
- **Local answers are free.** Always try to answer from quantities data before calling Gemini.
