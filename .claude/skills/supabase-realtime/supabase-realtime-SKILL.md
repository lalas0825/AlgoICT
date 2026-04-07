---
name: supabase-realtime
description: "Reactive data patterns using Supabase Realtime for NotchField. USE THIS SKILL whenever implementing live-updating UI components, reactive queries, real-time subscriptions, collaborative features, or any feature where data must update automatically when it changes in the database. Triggers include: quantities panel updates, canvas object sync, multi-user editing, live dashboards, notification systems, or any mention of 'realtime', 'reactive', 'live update', 'subscribe', 'watch', 'on change', 'auto-refresh'. This skill replaces PowerSync watch patterns from V1 with Supabase Realtime equivalents. It contains the exact channel setup, subscription patterns, cleanup rules, and performance limits that prevent common Realtime bugs."
---

# Supabase Realtime — Reactive Data Patterns for NotchField

> Supabase Realtime replaces PowerSync watch() as the reactive data layer.
> Every live-updating component in NotchField follows the patterns in this skill.

## Table of Contents
1. When to Use Realtime (Decision Tree)
2. Three Realtime Modes
3. Core Pattern: Initial Load + Subscribe
4. NotchField-Specific Subscriptions
5. React Hook Patterns
6. Cleanup Rules
7. Performance & Limits
8. Debugging

---

## 1. When to Use Realtime (Decision Tree)

```
Does the UI need to update when data changes without user action?
  ├── YES → Use Supabase Realtime
  │   ├── Is it database row changes? → Postgres Changes
  │   ├── Is it ephemeral (cursor position, typing indicator)? → Broadcast
  │   └── Is it user presence (who's online)? → Presence
  └── NO → Regular supabase.from().select() is fine
```

**NotchField features that NEED Realtime:**
- Quantities Panel (updates when takeoff objects change)
- Canvas sync (when another user adds/edits objects — Fase 6)
- Drawing list (when new drawings are uploaded)
- Project dashboard (when projects are archived/updated)
- AI Scan progress (when AI generates results)

**Features that DON'T need Realtime:**
- Classification CRUD (user triggers refresh manually)
- Export generation (one-time action)
- Billing page (rarely changes)
- Settings page

---

## 2. Three Realtime Modes

### Postgres Changes (Primary — use for 90% of cases)
Listens to INSERT/UPDATE/DELETE on database tables.
```typescript
const channel = supabase
  .channel('takeoff-objects')
  .on(
    'postgres_changes',
    {
      event: '*',                    // INSERT, UPDATE, DELETE, or *
      schema: 'public',
      table: 'takeoff_objects',
      filter: `drawing_id=eq.${drawingId}`,  // CRITICAL: always filter
    },
    (payload) => {
      // payload.eventType: 'INSERT' | 'UPDATE' | 'DELETE'
      // payload.new: the new row (INSERT/UPDATE)
      // payload.old: the old row (UPDATE/DELETE)
      handleChange(payload);
    }
  )
  .subscribe();
```

**PREREQUISITE:** The table must be added to the `supabase_realtime` publication:
```sql
-- Run ONCE per table (in migration)
ALTER PUBLICATION supabase_realtime ADD TABLE takeoff_objects;
ALTER PUBLICATION supabase_realtime ADD TABLE classifications;
ALTER PUBLICATION supabase_realtime ADD TABLE drawings;
ALTER PUBLICATION supabase_realtime ADD TABLE projects;
```

### Broadcast (Ephemeral messages — Fase 6 collaboration)
For data that doesn't need persistence: cursor positions, typing indicators.
```typescript
// Sender
supabase.channel('room-1').send({
  type: 'broadcast',
  event: 'cursor-move',
  payload: { x: 100, y: 200, userId: 'abc' },
});

// Receiver
supabase.channel('room-1')
  .on('broadcast', { event: 'cursor-move' }, (payload) => {
    moveCursor(payload.payload.x, payload.payload.y);
  })
  .subscribe();
```

### Presence (Who's online — Fase 6 collaboration)
```typescript
const channel = supabase.channel('project-123');
channel
  .on('presence', { event: 'sync' }, () => {
    const state = channel.presenceState();
    setOnlineUsers(Object.values(state).flat());
  })
  .subscribe(async (status) => {
    if (status === 'SUBSCRIBED') {
      await channel.track({ user_id: userId, name: userName });
    }
  });
```

---

## 3. Core Pattern: Initial Load + Subscribe

**CRITICAL:** Always load current data FIRST, then subscribe to changes. If you subscribe first and query second, you can miss changes that happen between subscribe and query.

```typescript
// ✅ CORRECT — load first, then subscribe
export function useTakeoffObjects(drawingId: string) {
  const supabase = useSupabase();
  const [objects, setObjects] = useState<TakeoffObject[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Step 1: Initial load
    const loadData = async () => {
      const { data } = await supabase
        .from('takeoff_objects')
        .select('*, classifications(*)')
        .eq('drawing_id', drawingId)
        .order('created_at');
      if (data) setObjects(data);
      setIsLoading(false);
    };
    loadData();

    // Step 2: Subscribe to changes
    const channel = supabase
      .channel(`objects:${drawingId}`)
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'takeoff_objects',
          filter: `drawing_id=eq.${drawingId}`,
        },
        (payload) => {
          setObjects((prev) => {
            switch (payload.eventType) {
              case 'INSERT':
                return [...prev, payload.new as TakeoffObject];
              case 'UPDATE':
                return prev.map((o) =>
                  o.id === payload.new.id ? (payload.new as TakeoffObject) : o
                );
              case 'DELETE':
                return prev.filter((o) => o.id !== payload.old.id);
              default:
                return prev;
            }
          });
        }
      )
      .subscribe();

    // Step 3: Cleanup on unmount
    return () => {
      supabase.removeChannel(channel);
    };
  }, [drawingId]);

  return { objects, isLoading };
}

// ❌ WRONG — no cleanup, no filter, subscribe without initial load
useEffect(() => {
  supabase.channel('all-objects')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'takeoff_objects' }, handler)
    .subscribe();
  // Missing: initial load, filter, cleanup
}, []);
```

---

## 4. NotchField-Specific Subscriptions

### Quantities Panel (Fase 2)
Subscribes to takeoff_objects for the active drawing. Recalculates quantities on every change.

```typescript
// Channel name pattern: "quantities:{drawingId}"
// Filter: drawing_id=eq.{drawingId}
// Events: INSERT, UPDATE, DELETE
// On change: recalculate all quantity groups
```

### Drawing List (Fase 1)
Subscribes to drawings for the active project (via set_id → project).

```typescript
// Channel name pattern: "drawings:{setId}"
// Filter: set_id=eq.{setId}
// Events: INSERT (new upload), UPDATE (rename/rotate), DELETE
```

### Project Dashboard (Fase 1)
Subscribes to projects for the org. Lightweight — only status/name changes.

```typescript
// Channel name pattern: "projects:{orgId}"
// Filter: organization_id=eq.{orgId}
// Events: UPDATE (archive/restore, rename)
```

### AI Scan Results (Fase 4)
When AI generates results, they arrive as INSERTs to a results table.

```typescript
// Channel name pattern: "ai-scan:{drawingId}"
// Subscribe during scan only, remove channel when scan completes
// Events: INSERT (each room/fixture detected)
```

---

## 5. React Hook Patterns

### Generic Realtime Hook
```typescript
function useRealtimeTable<T extends { id: string }>(
  table: string,
  filter: string,           // e.g., "drawing_id=eq.abc-123"
  initialQuery: () => Promise<T[]>
) {
  const supabase = useSupabase();
  const [data, setData] = useState<T[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let channel: ReturnType<typeof supabase.channel>;

    const init = async () => {
      const initial = await initialQuery();
      setData(initial);
      setIsLoading(false);

      channel = supabase
        .channel(`${table}:${filter}`)
        .on('postgres_changes', {
          event: '*',
          schema: 'public',
          table,
          filter,
        }, (payload) => {
          setData((prev) => {
            if (payload.eventType === 'INSERT') return [...prev, payload.new as T];
            if (payload.eventType === 'UPDATE') return prev.map(r => r.id === (payload.new as T).id ? payload.new as T : r);
            if (payload.eventType === 'DELETE') return prev.filter(r => r.id !== (payload.old as T).id);
            return prev;
          });
        })
        .subscribe();
    };

    init();
    return () => { if (channel) supabase.removeChannel(channel); };
  }, [table, filter]);

  return { data, isLoading };
}
```

### Usage
```typescript
const { data: objects, isLoading } = useRealtimeTable(
  'takeoff_objects',
  `drawing_id=eq.${drawingId}`,
  () => supabase.from('takeoff_objects').select('*').eq('drawing_id', drawingId).then(r => r.data ?? [])
);
```

---

## 6. Cleanup Rules

**EVERY subscription MUST be cleaned up on unmount.** Leaking channels causes:
- Memory leaks
- Stale event handlers firing on old data
- Hitting connection limits

```typescript
// ✅ CORRECT cleanup pattern
useEffect(() => {
  const channel = supabase.channel('my-channel').on(...).subscribe();
  return () => {
    supabase.removeChannel(channel);  // MUST call this
  };
}, [dependency]);

// ❌ WRONG — no cleanup
useEffect(() => {
  supabase.channel('my-channel').on(...).subscribe();
  // Channel leaks when component unmounts
}, []);
```

**Channel naming convention:** Use descriptive names with context:
- `objects:{drawingId}` — takeoff objects for a specific drawing
- `drawings:{setId}` — drawings in a specific set
- `projects:{orgId}` — projects for an organization
- `ai-scan:{drawingId}` — temporary AI scan results

**Never subscribe to an entire table without a filter.** Always use the `filter` parameter to scope to the relevant subset (by drawing_id, project_id, organization_id, etc.).

---

## 7. Performance & Limits

**Supabase Realtime pricing:**
- Free: 200 concurrent connections, 2M messages/month
- Pro: 500 concurrent connections, 5M messages/month
- Team: 1000 concurrent connections, custom

**Optimization rules:**
- One channel per feature, not per component (quantities panel = 1 channel, not 1 per classification)
- Use filters aggressively — `drawing_id=eq.X` not `*`
- Unsubscribe when navigating away from the editor
- Batch state updates with `requestAnimationFrame` if receiving rapid changes
- For the Quantities Panel: debounce recalculation by 100ms after receiving a change (prevents rapid recalcs when user draws quickly)

**Message size limit:** Realtime messages have a ~1MB payload limit. Takeoff object geometry is typically <1KB per object, so this is not a concern.

---

## 8. Debugging

**Channel not receiving events?**
1. Check that the table is in the `supabase_realtime` publication
2. Check that RLS allows SELECT for the user
3. Check the filter syntax — must be `column=eq.value` format
4. Check the Supabase Dashboard → Realtime → Logs

**Events firing but UI not updating?**
1. Check that `setData` uses functional update pattern `(prev) => ...`
2. Check that the `id` field matches between payload.new and existing data
3. Check that the channel is not being recreated on every render (dependency array)

**Duplicate events?**
1. Check that you're not subscribing multiple times (missing cleanup)
2. Check that the channel name is unique per subscription
