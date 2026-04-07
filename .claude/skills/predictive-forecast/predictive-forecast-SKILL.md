---
name: predictive-forecast
description: "Predictive project intelligence for construction specialty contractors. USE THIS SKILL whenever implementing production benchmarks, live productivity scorecards, project completion forecasting, crew optimization recommendations, or cross-project historical learning. Triggers: 'forecast', 'prediction', 'production matrix', 'benchmark', 'scorecard', 'productivity rate', 'sqft per hour', 'crew optimization', 'completion date', 'EAC', 'cross-project', 'historical rate'. This feature requires all three NotchField data sources: Takeoff quantities + Track production + GPS hours. No competitor can build this."
---

# Predictive Forecast — NotchField Intelligence Engine

> The killer feature. Predicts project completion from REAL field data.
> Requires: Takeoff (targets) + Track (production) + GPS (hours) = sqft/hr/man
> No competitor has all three data sources connected.

## Table of Contents
1. Production Matrix (Benchmarks)
2. Live Scorecard Calculation
3. Completion Forecasting
4. Crew Optimization
5. Cross-Project Learning
6. Trade Dependency Awareness
7. Data Model
8. Implementation

---

## 1. Production Matrix (Benchmarks)

The PM or supervisor defines expected productivity per area type:

```typescript
interface ProductionBenchmark {
  id: string;
  organization_id: string;
  area_type: string;           // 'bathroom_type_a', 'bathroom_type_b', 'kitchen'
  trade: string;               // 'marble', 'tile', 'drywall'
  
  // From bid / experience
  target_sqft: number;         // typical sqft for this area type
  target_days: number;         // expected duration
  target_crew_size: number;    // expected number of installers
  target_rate: number;         // sqft/hr/man (calculated or manual)
  
  // From historical data (auto-populated after projects complete)
  historical_rate: number;     // actual avg from past projects
  historical_projects: number; // how many projects contributed
  confidence: number;          // 0-1 based on data volume
  
  source: 'manual' | 'historical' | 'ai_suggested';
}

// Target rate calculation:
// Bathroom Type A = 85 sqft, 2 days, 2 installers
// Rate = 85 / (2 days × 8 hrs × 2 men) = 2.66 sqft/hr/man

function calculateTargetRate(sqft: number, days: number, crewSize: number, hoursPerDay = 8): number {
  return sqft / (days * hoursPerDay * crewSize);
}
```

### Default Benchmarks (NYC Specialty Contractors)

| Area Type | Trade | Sqft | Days | Crew | Rate (sqft/hr/man) |
|-----------|-------|------|------|------|-------------------|
| Bathroom Type A (standard) | Marble Floor | 45 | 1 | 2 | 2.81 |
| Bathroom Type A (standard) | Marble Wall | 40 | 1.5 | 2 | 1.67 |
| Bathroom Type B (large) | Marble Floor | 50 | 1 | 2 | 3.13 |
| Bathroom Type B (large) | Marble Wall | 70 | 2 | 2 | 2.19 |
| Kitchen backsplash | Tile | 30 lnft | 1 | 1 | 3.75 lnft/hr |
| Hallway/corridor | Marble Floor | 120 | 1.5 | 3 | 3.33 |
| Lobby | Marble Floor + Wall | 500 | 5 | 4 | 3.13 |

These are starting points — each company adjusts from their experience.

---

## 2. Live Scorecard Calculation

```typescript
interface AreaScorecard {
  area_id: string;
  area_name: string;
  
  // Targets (from Takeoff + Production Matrix)
  target_sqft: number;
  benchmark_rate: number;       // sqft/hr/man expected
  benchmark_days: number;
  
  // Actuals (from Track production + GPS)
  actual_sqft: number;
  actual_hours: number;         // total man-hours (crew × hours per person)
  actual_rate: number;          // actual sqft/hr/man
  actual_days: number;
  
  // Variance
  rate_variance: number;        // actual - benchmark (positive = ahead)
  rate_variance_pct: number;    // percentage difference
  
  // Status
  status: 'ahead' | 'on_track' | 'behind' | 'critical';
  percent_complete: number;
  
  // Projection
  projected_remaining_hours: number;
  projected_completion_date: string;
  days_ahead_behind: number;    // positive = ahead of schedule
}

function calculateScorecard(
  target: MasterProductionTarget,
  benchmark: ProductionBenchmark,
  progress: ProductionProgress[],
  gpsHours: LocationHistory[]
): AreaScorecard {
  
  const actualSqft = sum(progress.map(p => p.actual_sqft));
  const actualManHours = sum(gpsHours.map(h => h.hours_on_site));
  const actualRate = actualManHours > 0 ? actualSqft / actualManHours : 0;
  
  const remainingSqft = target.target_sqft - actualSqft;
  const projectedRemainingHours = actualRate > 0 
    ? remainingSqft / actualRate 
    : remainingSqft / benchmark.target_rate;
  
  const rateVariance = actualRate - benchmark.target_rate;
  
  let status: string;
  if (rateVariance > benchmark.target_rate * 0.1) status = 'ahead';
  else if (rateVariance > -benchmark.target_rate * 0.1) status = 'on_track';
  else if (rateVariance > -benchmark.target_rate * 0.25) status = 'behind';
  else status = 'critical';
  
  return {
    target_sqft: target.target_sqft,
    benchmark_rate: benchmark.target_rate,
    actual_sqft: actualSqft,
    actual_hours: actualManHours,
    actual_rate: actualRate,
    rate_variance: rateVariance,
    rate_variance_pct: (rateVariance / benchmark.target_rate) * 100,
    status,
    percent_complete: (actualSqft / target.target_sqft) * 100,
    projected_remaining_hours: projectedRemainingHours,
    // ... projected dates
  };
}
```

---

## 3. Completion Forecasting

```typescript
// Project-level forecast aggregates all area scorecards

interface ProjectForecast {
  project_id: string;
  
  // Overall
  total_sqft: number;
  completed_sqft: number;
  percent_complete: number;
  
  // Rates
  avg_rate: number;             // weighted average across all areas
  benchmark_rate: number;
  
  // Schedule
  schedule_end_date: string;    // from PM schedule
  projected_end_date: string;   // from actual rate calculation
  days_ahead_behind: number;
  
  // By floor
  floors: FloorForecast[];
  
  // Recommendations
  recommendations: Recommendation[];
}

interface Recommendation {
  type: 'add_crew' | 'reduce_crew' | 'redistribute' | 'notify_trade' | 'request_extension';
  urgency: 'info' | 'warning' | 'critical';
  message: string;
  details: string;
  estimated_impact: string;     // "Saves 3 days" or "Reduces cost by $4,800"
}

// Example recommendations:
// "At current rate (2.1 sqft/hr/man), Floor 24 finishes April 2 — 3 days late.
//  Add 1 installer to meet March 30 deadline. Cost: $2,400. Savings: avoid delay penalty."
//
// "Mario's crew (4.1 sqft/hr) outperforms Pedro's crew (2.3 sqft/hr) by 78%.
//  Swap Pedro to helper role. Projected impact: +0.8 sqft/hr average rate."
//
// "Floor 25 has 30% more sqft than Floor 24 but same crew allocation.
//  Recommend 3 installers instead of 2. Without adjustment, Floor 25 adds 2 extra days."
```

---

## 4. Crew Optimization

```typescript
// The supervisor's decision engine

interface CrewRecommendation {
  date: string;
  available_workers: Worker[];
  areas_ready: Area[];           // from Ready Board (green status)
  areas_almost: Area[];          // from Ready Board (yellow, ETA 1-2 days)
  
  suggested_assignments: {
    worker: Worker;
    area: Area;
    reason: string;              // "Highest priority area" or "Worker's best trade"
  }[];
  
  idle_workers: {
    worker: Worker;
    reason: string;              // "No areas ready for marble today"
    suggestion: string;          // "Assign to Floor 22 punch list" or "Release for the day"
  }[];
}

// Workers ranked by productivity for smart assignment
function rankWorkersByProductivity(trade: string): WorkerRanking[] {
  // Query historical production_progress + GPS hours per worker
  // Calculate sqft/hr per worker for specific trade
  // Return sorted: best performers first
  // Use for: assign best workers to most critical/visible areas
}
```

---

## 5. Cross-Project Learning

```typescript
// After each project completes, feed actual data back into benchmarks

async function updateBenchmarksFromProject(projectId: string) {
  // Get all production data from completed project
  const areas = await getCompletedAreas(projectId);
  
  for (const area of areas) {
    const existingBenchmark = await getBenchmark(area.type, area.trade);
    
    if (existingBenchmark) {
      // Weighted average: existing benchmark + new data
      const newRate = weightedAverage(
        existingBenchmark.historical_rate,
        existingBenchmark.historical_projects,
        area.actual_rate,
        1  // this project counts as 1
      );
      
      await updateBenchmark(existingBenchmark.id, {
        historical_rate: newRate,
        historical_projects: existingBenchmark.historical_projects + 1,
        confidence: Math.min(1, (existingBenchmark.historical_projects + 1) / 10),
      });
    } else {
      // First project with this area type — create benchmark
      await createBenchmark({
        area_type: area.type,
        trade: area.trade,
        historical_rate: area.actual_rate,
        historical_projects: 1,
        confidence: 0.1,
        source: 'historical',
      });
    }
  }
}

// After 10+ projects: benchmarks are highly accurate
// New bids auto-suggest realistic durations
// PM sees: "Based on 12 past projects, marble floor in Type A bathroom takes 1.2 days with 2 installers"
```

---

## 6. Trade Dependency Awareness

```typescript
// Forecast must account for upstream trade delays

interface TradeDependency {
  my_trade: string;              // 'marble'
  depends_on: string[];          // ['plumbing', 'drywall', 'waterproofing']
  sequence_position: number;     // where in the chain (1=first, 5=fifth)
}

// When forecasting, check if upstream trades are on schedule
function adjustForecastForDependencies(
  forecast: ProjectForecast,
  readyBoard: AreaReadiness[]
): ProjectForecast {
  
  const blockedAreas = readyBoard.filter(a => a.status === 'blocked' || a.status === 'held');
  
  if (blockedAreas.length > 0) {
    // Adjust projected completion date based on blocked areas
    // If 6 bathrooms are blocked with average 3-day ETA,
    // and crew can only do 2 bathrooms per day,
    // that's 3 + 3 = 6 days of delay, not 3
    
    const blockedDays = calculateBlockedImpact(blockedAreas, forecast.crew_size);
    forecast.projected_end_date = addWorkingDays(forecast.projected_end_date, blockedDays);
    forecast.days_ahead_behind -= blockedDays;
    
    forecast.recommendations.push({
      type: 'notify_trade',
      urgency: 'warning',
      message: `${blockedAreas.length} areas blocked by upstream trades. ${blockedDays} days of delay projected.`,
      details: blockedAreas.map(a => `${a.area_name}: blocked by ${a.blocking_trade}`).join(', '),
    });
  }
  
  return forecast;
}
```

---

## 7. Data Model

```sql
CREATE TABLE production_benchmarks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  area_type TEXT NOT NULL,
  trade TEXT NOT NULL,
  target_sqft NUMERIC,
  target_days NUMERIC,
  target_crew_size INTEGER,
  target_rate NUMERIC,           -- sqft/hr/man
  historical_rate NUMERIC,
  historical_projects INTEGER DEFAULT 0,
  confidence NUMERIC DEFAULT 0,
  source TEXT DEFAULT 'manual',
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(organization_id, area_type, trade)
);

CREATE TABLE forecast_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
  total_sqft NUMERIC,
  completed_sqft NUMERIC,
  percent_complete NUMERIC,
  avg_rate NUMERIC,
  benchmark_rate NUMERIC,
  projected_end_date DATE,
  schedule_end_date DATE,
  days_ahead_behind INTEGER,
  recommendations JSONB,
  floor_breakdown JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE worker_productivity (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  worker_id UUID NOT NULL REFERENCES profiles(id),
  trade TEXT NOT NULL,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  total_sqft NUMERIC,
  total_hours NUMERIC,
  rate NUMERIC,                  -- sqft/hr
  areas_completed INTEGER,
  qc_fail_rate NUMERIC,          -- from Quality Gate
  created_at TIMESTAMPTZ DEFAULT now()
);
```

---

## 8. Implementation

| Component | App | Phase |
|-----------|-----|-------|
| Production Matrix CRUD | Web PM Module | Fase 7 |
| Benchmark defaults (10 trades) | Web PM Module | Fase 7 |
| Live Scorecard calculation | Server (Edge Function) | Fase 7 |
| Scorecard view for supervisor | Track Production tab | Phase T2 |
| Project Forecast dashboard | Web PM Dashboard | Fase 7 |
| Crew optimization suggestions | Web PM + Track | Phase T3 |
| Cross-project learning | Server (post-project job) | Post-launch |
| Trade dependency integration | Server + Ready Board | Phase T3 |
| Worker productivity ranking | Web PM Dashboard | Fase 7 |
