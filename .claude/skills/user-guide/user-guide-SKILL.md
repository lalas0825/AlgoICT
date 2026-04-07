---
name: user-guide
description: "Generate user documentation with real screenshots from the running app. USE THIS SKILL whenever the user asks to create a user guide, manual, help docs, onboarding guide, feature documentation, or tutorial for any NotchField app. Also use when the user says 'document this feature', 'create help page', 'how-to guide', 'user manual', or after completing a development phase and needing to document what was built. This skill uses Playwright to navigate the live app, take screenshots of every screen and interaction, and generates a comprehensive guide with images. Run after each phase completion to keep docs current."
---

# User Guide Generator

> Automatically creates user documentation with real screenshots from the running application.
> Run after each phase completion: `npm run dev` → `/user-guide [phase or feature]`

## Table of Contents
1. How It Works
2. Screenshot Capture Process
3. Guide Structure
4. Running the Skill
5. Output Formats
6. Language Support

---

## 1. How It Works

```
Developer completes a feature/phase
    │
    ├── 1. Start dev server: npm run dev (port 3000)
    ├── 2. Run this skill with target phase/feature
    ├── 3. Playwright launches browser
    ├── 4. Navigates to each screen in the feature
    ├── 5. Takes screenshot at each step
    ├── 6. Captures interaction states (empty, filled, loading, success, error)
    ├── 7. Saves screenshots to /docs/guide/images/
    └── 8. Generates markdown guide with embedded images
```

## 2. Screenshot Capture Process

### Setup
```typescript
// The skill uses Playwright to capture real app screenshots
import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },  // Desktop
  // For tablet: { width: 1024, height: 768 }
  // For mobile: { width: 390, height: 844 }
});
const page = await context.newPage();
```

### Authentication First
```typescript
// Login before capturing any authenticated screens
await page.goto('http://localhost:3000/login');
await page.fill('[name="email"]', 'demo@notchfield.io');
await page.fill('[name="password"]', 'demo-password');
await page.click('button[type="submit"]');
await page.waitForURL('**/projects');
```

### Capture Pattern (for each screen)
```typescript
async function captureScreen(
  page: Page,
  route: string,
  name: string,
  interactions?: Array<{
    action: string;        // 'click', 'fill', 'hover', 'wait'
    selector: string;
    value?: string;
    screenshotName: string;
    description: string;   // What the user sees/does at this step
  }>
) {
  // Navigate to the screen
  await page.goto(`http://localhost:3000${route}`);
  await page.waitForLoadState('networkidle');

  // Capture the initial state
  await page.screenshot({
    path: `docs/guide/images/${name}-overview.png`,
    fullPage: false,
  });

  // Capture each interaction state
  if (interactions) {
    for (const step of interactions) {
      if (step.action === 'click') {
        await page.click(step.selector);
      } else if (step.action === 'fill') {
        await page.fill(step.selector, step.value || '');
      } else if (step.action === 'hover') {
        await page.hover(step.selector);
      } else if (step.action === 'wait') {
        await page.waitForSelector(step.selector);
      }

      await page.waitForTimeout(500); // Let animations complete
      await page.screenshot({
        path: `docs/guide/images/${name}-${step.screenshotName}.png`,
        fullPage: false,
      });
    }
  }
}
```

### Annotated Screenshots (highlight areas of interest)
```typescript
// After capturing, optionally add visual annotations
// Red circles, arrows, numbered steps overlaid on screenshots
// Use Sharp or Canvas to draw on the images programmatically

import sharp from 'sharp';

async function annotateScreenshot(
  inputPath: string,
  outputPath: string,
  annotations: Array<{
    type: 'circle' | 'arrow' | 'number' | 'highlight';
    x: number;
    y: number;
    label?: string;
    color?: string;
  }>
) {
  // Create SVG overlay with annotations
  const svgOverlay = buildAnnotationSVG(annotations);

  await sharp(inputPath)
    .composite([{ input: Buffer.from(svgOverlay), gravity: 'northwest' }])
    .toFile(outputPath);
}
```

---

## 3. Guide Structure

### For Each Feature, Generate:

```markdown
## [Feature Name]

### What it does
[1-2 sentence description in plain language]

### How to use it

**Step 1: [Action]**
[Description of what to do]
![Step 1](images/feature-step1.png)

**Step 2: [Action]**
[Description of what to do]
![Step 2](images/feature-step2.png)

**Step 3: [Result]**
[Description of what happens]
![Step 3](images/feature-step3.png)

### Tips
- [Practical tip from real usage]
- [Common mistake to avoid]

### Keyboard Shortcuts (if applicable)
| Shortcut | Action |
|----------|--------|
| Ctrl+Z | Undo |
```

### Full Guide Table of Contents (by Phase)

```
docs/guide/
├── images/                          # All screenshots
│   ├── login-overview.png
│   ├── login-fill.png
│   ├── dashboard-overview.png
│   ├── dashboard-new-project.png
│   ├── editor-overview.png
│   ├── editor-calibration-step1.png
│   ├── editor-calibration-step2.png
│   ├── editor-polygon-drawing.png
│   ├── editor-quantities-panel.png
│   └── ...
├── en/                              # English guide
│   ├── 00-getting-started.md
│   ├── 01-projects.md
│   ├── 02-drawings.md
│   ├── 03-editor.md
│   ├── 04-calibration.md
│   ├── 05-classifications.md
│   ├── 06-quantities.md
│   ├── 07-export.md
│   └── index.md                     # Table of contents
├── es/                              # Spanish guide (same structure)
├── fr/                              # French
├── pt/                              # Portuguese
├── it/                              # Italian
├── de/                              # German
└── guide.pdf                        # Combined PDF with all screenshots
```

---

## 4. Running the Skill

### After Phase 1 Completion
```
/user-guide phase1

Captures:
- Login page (email/password, Google OAuth button)
- Register page (org creation, trade selection)
- Dashboard (empty state, project cards, new project modal)
- Project detail (drawing sets, breadcrumb)
- Settings (language switcher, billing)
- Billing page (plan cards, trial countdown)
```

### After Phase 2 Completion
```
/user-guide phase2

Captures:
- Drawing upload (drag & drop, progress bar)
- Drawing list (thumbnails, scale indicator)
- Editor overview (toolbar, canvas, quantities panel)
- Scale calibration (2-click flow, dimension input dialog)
- Each drawing tool (polygon, rectangle, line, count, select)
- Merge/cut/split tools
- Snapping in action
- Classifications (CRUD, folders, color picker)
- Quantities panel (grouped, totals, cost)
- PDF quote export
- Visual evidence capture
```

### Single Feature
```
/user-guide feature:calibration

Captures only the calibration flow with detailed steps
```

### Full Guide Regeneration
```
/user-guide all

Captures everything, regenerates entire guide
```

---

## 5. Output Formats

### Markdown (Primary — for docs site)
Each feature gets a `.md` file with embedded image references.
Can be deployed to a docs site (Docusaurus, GitBook, or simple HTML).

### PDF (for sharing with clients)
Combined PDF with all screenshots, professional formatting.
Generated with Puppeteer or jsPDF from the markdown files.
Includes cover page with NotchField branding.

### In-App Help (future)
Screenshots and descriptions stored in JSON format.
Can power in-app tooltips, onboarding tours, or help modals.

```json
{
  "calibration": {
    "title": "Scale Calibration",
    "steps": [
      {
        "description": "Click the ruler icon in the toolbar",
        "image": "calibration-step1.png",
        "selector": "[data-tool='calibrate']"
      },
      {
        "description": "Click two points on a known dimension",
        "image": "calibration-step2.png"
      },
      {
        "description": "Enter the real-world distance",
        "image": "calibration-step3.png"
      }
    ]
  }
}
```

---

## 6. Language Support

The guide text is generated in English first, then translated to all 6 languages.
Screenshots are language-independent (UI shows the selected language).

### For translated guides:
1. Generate English guide text
2. Use Claude to translate each .md file to ES, FR, PT, IT, DE
3. For language-specific screenshots, change app locale before capturing:
   ```typescript
   // Set locale cookie before capturing
   await context.addCookies([{
     name: 'NEXT_LOCALE',
     value: 'es', // or 'fr', 'pt', 'it', 'de'
     domain: 'localhost',
     path: '/',
   }]);
   ```
4. Capture screenshots in each language (UI text changes)

### Translation prompt for guide text:
```
Translate this user guide section to [LANGUAGE].
Keep it practical and conversational — this is for construction workers, not developers.
Use construction terminology appropriate for [COUNTRY] market.
Keep all image references unchanged.
Translate button labels to match what the user sees in the [LANGUAGE] UI.
```

---

## 7. Capture Recipes by Feature

### Login & Register
```typescript
const loginCaptures = [
  { route: '/login', name: 'login', interactions: [
    { action: 'wait', selector: 'form', screenshotName: 'form', description: 'Login page with email and password fields' },
    { action: 'fill', selector: '[name="email"]', value: 'demo@notchfield.io', screenshotName: 'email-filled', description: 'Enter your email address' },
  ]},
  { route: '/register', name: 'register', interactions: [
    { action: 'wait', selector: 'form', screenshotName: 'form', description: 'Registration page' },
    { action: 'click', selector: '[data-trade="tile"]', screenshotName: 'trade-selected', description: 'Select your trade' },
  ]},
];
```

### Editor
```typescript
const editorCaptures = [
  { route: '/editor/[drawingId]', name: 'editor', interactions: [
    { action: 'wait', selector: 'canvas', screenshotName: 'overview', description: 'The editor with your blueprint loaded' },
    { action: 'click', selector: '[data-tool="calibrate"]', screenshotName: 'calibrate-active', description: 'Click the ruler icon to start calibration' },
    { action: 'click', selector: '[data-tool="polygon"]', screenshotName: 'polygon-active', description: 'Select the polygon tool to draw areas' },
    { action: 'click', selector: '[data-panel="quantities"]', screenshotName: 'quantities-open', description: 'View your measurements in the quantities panel' },
  ]},
];
```

### Dashboard
```typescript
const dashboardCaptures = [
  { route: '/projects', name: 'dashboard', interactions: [
    { action: 'wait', selector: '[data-empty-state]', screenshotName: 'empty', description: 'Your dashboard before creating any projects' },
    { action: 'click', selector: '[data-action="new-project"]', screenshotName: 'new-project-modal', description: 'Click "New Project" to get started' },
  ]},
];
```

---

## 8. Quality Checklist

Before publishing any guide:

- [ ] All screenshots are current (match deployed version)
- [ ] No placeholder/test data visible in screenshots
- [ ] Screenshots use demo account (not real customer data)
- [ ] All 6 language versions exist
- [ ] Image file sizes optimized (<200KB each via Sharp)
- [ ] Each step has a clear description (what to do + what happens)
- [ ] Keyboard shortcuts documented where applicable
- [ ] Tips include common mistakes to avoid
- [ ] PDF version renders correctly with images
- [ ] Links between guide sections work
