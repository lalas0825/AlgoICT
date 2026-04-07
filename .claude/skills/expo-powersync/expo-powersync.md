# Skill: expo-powersync
> Offline-first sync with PowerSync: SQLite local → Supabase cloud
> Track App | Phase T1 | Critical infrastructure — every feature depends on this

## When to Activate
- Setting up PowerSync in the Expo project
- Defining sync rules (what data syncs to which user)
- Any query that reads/writes shared Supabase tables from Track
- Handling offline/online transitions
- Conflict resolution decisions

## Architecture

### How PowerSync Works in NotchField Track
```
[Supabase PostgreSQL] ←→ [PowerSync Service] ←→ [SQLite on device]
                                                       ↑
                                                  Track app reads/writes here
                                                  (works offline)
```

- Track NEVER queries Supabase directly — always goes through local SQLite via PowerSync
- PowerSync handles bidirectional sync automatically
- When offline: all reads/writes go to local SQLite
- When online: PowerSync syncs changes to Supabase in background
- Takeoff web app queries Supabase directly (no PowerSync)

### PowerSync Setup
```typescript
// powersync.ts
import { PowerSyncDatabase } from '@powersync/react-native';
import { SupabaseConnector } from './supabase-connector';

const connector = new SupabaseConnector();

export const db = new PowerSyncDatabase({
  schema: AppSchema,  // defines local tables mirroring Supabase
  database: {
    dbFilename: 'notchfield-track.db'
  }
});

await db.connect(connector);
```

### Supabase Connector
```typescript
// supabase-connector.ts
import { AbstractPowerSyncDatabase, PowerSyncBackendConnector } from '@powersync/react-native';
import { createClient } from '@supabase/supabase-js';

export class SupabaseConnector implements PowerSyncBackendConnector {
  private supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

  async fetchCredentials() {
    const { data: { session } } = await this.supabase.auth.getSession();
    return {
      endpoint: POWERSYNC_URL,
      token: session?.access_token ?? '',
    };
  }

  async uploadData(database: AbstractPowerSyncDatabase) {
    // Called when local changes need to sync to Supabase
    const batch = await database.getCrudBatch();
    if (!batch) return;

    for (const op of batch.crud) {
      const table = op.table;
      const record = op.opData;

      switch (op.op) {
        case 'PUT':
          await this.supabase.from(table).upsert(record);
          break;
        case 'PATCH':
          await this.supabase.from(table).update(record).eq('id', op.id);
          break;
        case 'DELETE':
          await this.supabase.from(table).delete().eq('id', op.id);
          break;
      }
    }
    await batch.complete();
  }
}
```

## Sync Rules — Who Gets What Data

### By Role
```yaml
# PowerSync sync rules (server-side)

# Foreman: only assigned project
bucket_definitions:
  foreman_bucket:
    parameters:
      - SELECT project_id FROM crew_assignments WHERE worker_id = token_parameters.user_id
    data:
      - SELECT * FROM production_areas WHERE project_id IN bucket.project_id
      - SELECT * FROM production_area_objects WHERE organization_id = token_parameters.org_id
      - SELECT * FROM work_tickets WHERE project_id IN bucket.project_id
      - SELECT * FROM safety_documents WHERE project_id IN bucket.project_id
      # ... all tables filtered by project_id

  # Supervisor: all assigned projects
  supervisor_bucket:
    parameters:
      - SELECT DISTINCT project_id FROM projects WHERE organization_id = token_parameters.org_id
    data:
      - SELECT * FROM production_areas WHERE organization_id = token_parameters.org_id
      # ... all tables filtered by organization_id (sees everything)

  # Worker: minimal data
  worker_bucket:
    parameters:
      - SELECT project_id FROM crew_assignments WHERE worker_id = token_parameters.user_id
    data:
      - SELECT * FROM safety_documents WHERE project_id IN bucket.project_id
      - SELECT * FROM document_signoffs WHERE signer_id = token_parameters.user_id
```

### What NOT to Sync
- `takeoff_objects` full geometry (too large) — sync only id, area, classification_id, drawing_id
- `document_chunks` (pgvector embeddings) — web only
- `ai_feedback`, `ai_usage` — web only
- `bid_adjustments`, `product_catalog` — web only (estimator tools)
- `drawing_sets`, `drawings` (PDFs) — too large for mobile sync. Only metadata.

## Local Queries Pattern
```typescript
// Always use PowerSync watched queries for reactive UI
import { useQuery } from '@powersync/react-native';

function AreaList({ projectId }: { projectId: string }) {
  const { data: areas } = useQuery(
    `SELECT * FROM production_areas WHERE project_id = ? ORDER BY floor_label, label`,
    [projectId]
  );

  return areas.map(area => <AreaCard key={area.id} area={area} />);
}

// For writes: use the PowerSync execute method
async function markSurfaceComplete(objectId: string, userId: string) {
  await db.execute(
    `UPDATE production_area_objects SET status = 'complete', completed_at = ?, completed_by = ? WHERE id = ?`,
    [new Date().toISOString(), userId, objectId]
  );
  // PowerSync auto-syncs this to Supabase when online
}
```

## Conflict Resolution
- **Last-write-wins** — field data is authoritative (foreman was there, PM wasn't)
- If both Track and Takeoff modify the same row, the later timestamp wins
- PowerSync handles this automatically — no custom merge logic needed
- Exception: `production_areas.progress_pct` is CALCULATED, not stored — no conflict possible

## Offline Patterns
```typescript
// Check connectivity
import { useStatus } from '@powersync/react-native';

function SyncIndicator() {
  const status = useStatus();

  if (!status.connected) {
    return <OfflineBanner text="Offline — changes will sync when connected" />;
  }
  if (status.uploading) {
    return <SyncingIcon />;
  }
  return null;
}
```

### Offline Photo Queue
Photos can't sync instantly (large files). Pattern:
1. Save photo to local filesystem
2. Create record in `field_photos` with `sync_status: 'pending'`
3. When online: upload to Supabase Storage → update `sync_status: 'uploaded'` → set `url`
4. Show thumbnail from local file until upload completes

## Common Errors to Avoid
- ❌ Querying Supabase directly from Track — always use PowerSync local DB
- ❌ Syncing large blobs (PDFs, full-res photos) — sync metadata only, download on demand
- ❌ Complex JOIN queries in sync rules — keep them simple for performance
- ❌ Assuming data is always fresh — show "last synced" timestamp
- ❌ Blocking UI on sync — all writes are instant (local), sync is background
