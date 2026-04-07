---
name: i18n-6lang
description: "Multi-language internationalization patterns for NotchField using next-intl with 6 languages (EN, ES, FR, PT, IT, DE). USE THIS SKILL whenever creating new UI components, adding new pages, building new features, or modifying any user-facing text. Triggers include: any new component with visible text, any new page or modal, any error/success/empty state message, any button label, any placeholder, any tooltip, or when the user mentions 'translate', 'language', 'i18n', 'locale', 'multilingual', or 'internationalization'. CRITICAL: Every hardcoded string in JSX is a bug. This skill prevents the agent from forgetting to translate UI text across all 6 languages."
---

# i18n — 6 Language Patterns for NotchField

> **Rule #1: Every user-visible string MUST use `t('key')`. No exceptions.**
> A hardcoded string in English is a bug that breaks the product for 5 other languages.

## Table of Contents
1. Setup & Configuration
2. The Golden Rule
3. Creating New Translation Keys
4. Namespace Convention
5. Plurals, Numbers, Dates
6. What NOT to Translate
7. Adding a New Feature Checklist
8. Language-Specific Notes

---

## 1. Setup & Configuration

### File Structure
```
messages/
├── en.json    # English (default — write this first)
├── es.json    # Español
├── fr.json    # Français
├── pt.json    # Português
├── it.json    # Italiano
└── de.json    # Deutsch
```

### next-intl Config
```typescript
// src/i18n/routing.ts
import { defineRouting } from 'next-intl/routing';

export const routing = defineRouting({
  locales: ['en', 'es', 'fr', 'pt', 'it', 'de'],
  defaultLocale: 'en',
  // No URL prefixes — locale stored in cookie NEXT_LOCALE
});
```

```typescript
// src/middleware.ts
import createMiddleware from 'next-intl/middleware';
import { routing } from '@/i18n/routing';

export default createMiddleware(routing);
```

### Using Translations in Components
```typescript
// Client component
'use client';
import { useTranslations } from 'next-intl';

export function MyComponent() {
  const t = useTranslations('editor');
  return <button>{t('tools.polygon')}</button>;
}

// Server component
import { getTranslations } from 'next-intl/server';

export default async function Page() {
  const t = await getTranslations('dashboard');
  return <h1>{t('title')}</h1>;
}
```

---

## 2. The Golden Rule

```
✅ CORRECT:  <button>{t('actions.save')}</button>
❌ WRONG:    <button>Save</button>
❌ WRONG:    <button>{"Save"}</button>
❌ WRONG:    <button>{isNew ? "Create" : "Update"}</button>
✅ CORRECT:  <button>{isNew ? t('actions.create') : t('actions.update')}</button>
```

**Every string the user can see must go through `t()`.** This includes:
- Button labels
- Page titles and headings
- Form labels and placeholders
- Error messages
- Success/toast messages
- Empty state messages
- Tooltip text
- Confirmation dialogs
- Navigation items
- Table headers
- Loading messages ("Analyzing plan...", "Uploading...")
- Alt text for images

**The only exceptions** are in section 6 (What NOT to Translate).

---

## 3. Creating New Translation Keys

When building any new feature, create keys in ALL 6 files simultaneously.

### Step-by-Step
1. Write the English keys first in `en.json`
2. Immediately create the same keys in the other 5 files
3. For languages you don't speak, use Claude to translate
4. Use the same key structure across all files

### Example: Adding a new "Repeating Groups" feature

**en.json:**
```json
{
  "repeatingGroups": {
    "title": "Repeating Groups",
    "createMaster": "Create Master Unit",
    "applyTo": "Apply to Drawings",
    "flipH": "Flip Horizontal",
    "flipV": "Flip Vertical",
    "rotate": "Rotate",
    "instances": "{count, plural, one {# instance} other {# instances}}",
    "editMasterWarning": "Editing the master will update all {count} instances",
    "aggregateTotal": "Aggregate Total",
    "empty": "No repeating groups yet. Create one from an existing takeoff.",
    "deleteConfirm": "Delete this repeating group? All instances will be removed."
  }
}
```

**es.json:**
```json
{
  "repeatingGroups": {
    "title": "Grupos Repetitivos",
    "createMaster": "Crear Unidad Maestra",
    "applyTo": "Aplicar a Planos",
    "flipH": "Voltear Horizontal",
    "flipV": "Voltear Vertical",
    "rotate": "Rotar",
    "instances": "{count, plural, one {# instancia} other {# instancias}}",
    "editMasterWarning": "Editar la unidad maestra actualizará las {count} instancias",
    "aggregateTotal": "Total Agregado",
    "empty": "Aún no hay grupos repetitivos. Crea uno desde un takeoff existente.",
    "deleteConfirm": "¿Eliminar este grupo repetitivo? Se eliminarán todas las instancias."
  }
}
```

**fr.json:**
```json
{
  "repeatingGroups": {
    "title": "Groupes Répétitifs",
    "createMaster": "Créer l'Unité Maître",
    "applyTo": "Appliquer aux Plans",
    "flipH": "Retourner Horizontalement",
    "flipV": "Retourner Verticalement",
    "rotate": "Pivoter",
    "instances": "{count, plural, one {# instance} other {# instances}}",
    "editMasterWarning": "Modifier le maître mettra à jour les {count} instances",
    "aggregateTotal": "Total Agrégé",
    "empty": "Aucun groupe répétitif. Créez-en un à partir d'un métré existant.",
    "deleteConfirm": "Supprimer ce groupe répétitif ? Toutes les instances seront supprimées."
  }
}
```

**pt.json:**
```json
{
  "repeatingGroups": {
    "title": "Grupos Repetitivos",
    "createMaster": "Criar Unidade Mestre",
    "applyTo": "Aplicar aos Desenhos",
    "flipH": "Espelhar Horizontal",
    "flipV": "Espelhar Vertical",
    "rotate": "Girar",
    "instances": "{count, plural, one {# instância} other {# instâncias}}",
    "editMasterWarning": "Editar o mestre atualizará todas as {count} instâncias",
    "aggregateTotal": "Total Agregado",
    "empty": "Nenhum grupo repetitivo ainda. Crie um a partir de um levantamento existente.",
    "deleteConfirm": "Excluir este grupo repetitivo? Todas as instâncias serão removidas."
  }
}
```

**it.json:**
```json
{
  "repeatingGroups": {
    "title": "Gruppi Ripetitivi",
    "createMaster": "Crea Unità Master",
    "applyTo": "Applica ai Disegni",
    "flipH": "Capovolgi Orizzontale",
    "flipV": "Capovolgi Verticale",
    "rotate": "Ruota",
    "instances": "{count, plural, one {# istanza} other {# istanze}}",
    "editMasterWarning": "La modifica del master aggiornerà tutte le {count} istanze",
    "aggregateTotal": "Totale Aggregato",
    "empty": "Nessun gruppo ripetitivo. Creane uno da un computo esistente.",
    "deleteConfirm": "Eliminare questo gruppo ripetitivo? Tutte le istanze verranno rimosse."
  }
}
```

**de.json:**
```json
{
  "repeatingGroups": {
    "title": "Wiederholungsgruppen",
    "createMaster": "Master-Einheit Erstellen",
    "applyTo": "Auf Zeichnungen Anwenden",
    "flipH": "Horizontal Spiegeln",
    "flipV": "Vertikal Spiegeln",
    "rotate": "Drehen",
    "instances": "{count, plural, one {# Instanz} other {# Instanzen}}",
    "editMasterWarning": "Das Bearbeiten des Masters aktualisiert alle {count} Instanzen",
    "aggregateTotal": "Gesamtsumme",
    "empty": "Noch keine Wiederholungsgruppen. Erstellen Sie eine aus einem vorhandenen Aufmaß.",
    "deleteConfirm": "Diese Wiederholungsgruppe löschen? Alle Instanzen werden entfernt."
  }
}
```

---

## 4. Namespace Convention

Each feature gets its own namespace. Namespaces match the `features/` directory:

| Namespace | Feature | Example keys |
|-----------|---------|--------------|
| `common` | Shared across app | actions.save, actions.cancel, actions.delete, status.loading |
| `auth` | Login/register | login.title, register.selectTrade, errors.invalidEmail |
| `dashboard` | Projects grid | title, newProject, empty, search.placeholder |
| `projects` | Project detail | title, drawingSets, archive, restore |
| `drawings` | Drawing management | upload.title, upload.progress, rename, rotate |
| `editor` | Canvas editor | tools.polygon, tools.rectangle, tools.line, tools.count, tools.select, tools.merge, tools.cut, tools.split, calibration.title, calibration.hint |
| `quantities` | Quantities panel | title, total, withWaste, grandTotal, setScaleWarning |
| `classifications` | Classification CRUD | title, addNew, folder, color, trade, unit, wasteFactor |
| `export` | Excel/PDF export | excel, pdf, generating, history |
| `billing` | Stripe/plans | plans.starter, plans.pro, plans.team, trial.daysLeft |
| `settings` | Settings page | title, language, team, billing |
| `ai` | AI features | scan.button, scan.analyzing, chat.placeholder, imageSearch.hint |
| `repeatingGroups` | Repeating groups | title, createMaster, instances, editMasterWarning |

### Nested Keys Pattern
```json
{
  "editor": {
    "tools": {
      "polygon": "Polygon",
      "rectangle": "Rectangle",
      "line": "Line",
      "count": "Count",
      "select": "Select",
      "merge": "Merge",
      "cut": "Cut & Subtract",
      "split": "Split"
    },
    "calibration": {
      "title": "Scale Calibration",
      "hint": "Click two points with a known distance",
      "input": "Enter the real distance",
      "success": "Scale set: {scale} px/in"
    },
    "snapping": {
      "toggle": "Toggle Snapping",
      "angles": "Snap to Angles",
      "edges": "Snap to Edges"
    }
  }
}
```

---

## 5. Plurals, Numbers, Dates

### Plurals (ICU syntax)
```json
{
  "objects": "{count, plural, one {# object} other {# objects}}",
  "drawings": "{count, plural, one {# drawing} other {# drawings}}"
}
```
```typescript
t('objects', { count: 5 })  // "5 objects"
t('objects', { count: 1 })  // "1 object"
```

**Spanish/Portuguese/French/Italian/German all have different plural rules.** next-intl handles this automatically when using ICU syntax — just provide the correct translations for each language.

### Numbers (locale-aware formatting)
```typescript
import { useFormatter } from 'next-intl';

const format = useFormatter();
format.number(1234.56);           // "1,234.56" (en) / "1.234,56" (de)
format.number(0.15, { style: 'percent' });  // "15%" (en) / "15 %" (fr)
```

**For currency — always use the utility from construction-takeoff skill:**
```typescript
const formatCurrency = (amount: number, locale: string) =>
  new Intl.NumberFormat(locale, { style: 'currency', currency: 'USD' }).format(amount);
```

### Dates
```typescript
const format = useFormatter();
format.dateTime(new Date(), { dateStyle: 'medium' });
// "Mar 17, 2026" (en) / "17 mar 2026" (es) / "17 mars 2026" (fr)
```

---

## 6. What NOT to Translate

These are **never** translated — they are user-generated or technical:

- Project names ("430 Park Avenue South")
- Classification names custom-created by user ("Custom Marble A")
- Drawing names/sheet numbers ("A-101", "8th Floor West")
- User names
- Email addresses
- Organization names
- File names
- Technical identifiers (IDs, URLs)
- Trade names when used as enum values in code (`'marble'`, `'tile'`)
- Dimension values ("12'-6\"")

**Trade names in the UI ARE translated:**
```json
// en.json
{ "trades": { "marble": "Marble/Stone", "tile": "Tile", "drywall": "Drywall" } }
// es.json
{ "trades": { "marble": "Mármol/Piedra", "tile": "Azulejo", "drywall": "Tablaroca" } }
// de.json
{ "trades": { "marble": "Marmor/Naturstein", "tile": "Fliesen", "drywall": "Trockenbau" } }
```

---

## 7. Adding a New Feature Checklist

Every time you build a new feature, run through this checklist:

- [ ] Created namespace in `en.json` with all user-visible strings
- [ ] Copied namespace to `es.json` with Spanish translations
- [ ] Copied namespace to `fr.json` with French translations
- [ ] Copied namespace to `pt.json` with Portuguese translations
- [ ] Copied namespace to `it.json` with Italian translations
- [ ] Copied namespace to `de.json` with German translations
- [ ] All button labels use `t('...')`
- [ ] All headings use `t('...')`
- [ ] All error messages use `t('...')`
- [ ] All empty states use `t('...')`
- [ ] All toast/success messages use `t('...')`
- [ ] All placeholders use `t('...')`
- [ ] All tooltips use `t('...')`
- [ ] Plurals use ICU syntax `{count, plural, one {...} other {...}}`
- [ ] Numbers use `useFormatter()` or `Intl.NumberFormat`
- [ ] Dates use `useFormatter()` with dateStyle
- [ ] No hardcoded English strings remain in JSX

---

## 8. Language-Specific Notes

### Spanish (es)
- NYC construction crews are 50%+ Spanish-speaking — this is a key competitive advantage
- Use Latin American Spanish (not Castilian) for construction terms
- "Takeoff" = "Levantamiento de cantidades" or just "Takeoff" (industry standard)
- "Drywall" = "Tablaroca" (MX) or "Yeso" (general) — use "Tablaroca" for US market
- Formal "usted" tone, not "tú"

### French (fr)
- Target: Québec + France construction markets
- Use gender-neutral terms where possible
- "Takeoff" = "Métré" (formal) or "Quantification"
- Numbers: spaces as thousands separator (1 234,56)

### Portuguese (pt)
- Target: Brazil (largest construction market in Latin America)
- Use Brazilian Portuguese, not European
- "Takeoff" = "Levantamento de quantitativos"
- Numbers: dots as thousands separator (1.234,56)

### Italian (it)
- Target: Italy construction market
- "Takeoff" = "Computo metrico"
- Formal tone for professional software

### German (de)
- Target: Germany + Austria + Switzerland (DACH)
- "Takeoff" = "Aufmaß" or "Mengenermittlung"
- Compound nouns are common and long — check UI fits
- Numbers: dots as thousands separator (1.234,56)
