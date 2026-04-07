# Skill: field-ux-patterns
> Construction-specific mobile UX: touch targets, haptics, swipe actions, offline UI, dark mode
> Track App | All Phases | Applied to EVERY component in Track

## When to Activate
- Building ANY UI component in Track
- Implementing interactive elements (checkboxes, buttons, lists)
- Creating animations or transitions
- Handling offline/online states in UI
- Styling components (dark mode, colors, typography)

## The Golden Rule
> Dirty hands. Direct sunlight. Hard hat. 30 seconds of patience.
> Every design decision filters through this reality.

## Touch Targets

### Minimum Sizes (Non-Negotiable)
```typescript
// constants/layout.ts
export const TOUCH = {
  MIN: 48,          // dp — absolute minimum (Google/Apple guideline)
  STANDARD: 56,     // dp — buttons, list items
  CHECKBOX: 64,     // dp — checkboxes that get tapped 50x/day
  FAB: 64,          // dp — floating action button
  SPACING: 12,      // dp — minimum between targets
} as const;
```

### Checkbox Component (The Most Used Component)
```tsx
// components/FieldCheckbox.tsx
import * as Haptics from 'expo-haptics';
import Animated, { useSharedValue, withSpring, withSequence } from 'react-native-reanimated';

function FieldCheckbox({ checked, onToggle, label, subtitle }: {
  checked: boolean;
  onToggle: () => void;
  label: string;
  subtitle?: string;
}) {
  const scale = useSharedValue(1);

  const handlePress = () => {
    // Haptic feedback — MUST feel the tap
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

    // Satisfying bounce animation
    scale.value = withSequence(
      withSpring(0.85, { damping: 10 }),
      withSpring(1.1, { damping: 8 }),
      withSpring(1, { damping: 12 })
    );

    onToggle();
  };

  return (
    <Pressable
      onPress={handlePress}
      style={{
        minHeight: TOUCH.CHECKBOX,
        flexDirection: 'row',
        alignItems: 'center',
        paddingHorizontal: 16,
        paddingVertical: 12,
        gap: 16,
      }}
    >
      <Animated.View style={[{
        width: 32, height: 32, borderRadius: 8,
        borderWidth: 2,
        borderColor: checked ? '#22C55E' : '#64748B',
        backgroundColor: checked ? '#22C55E' : 'transparent',
        justifyContent: 'center', alignItems: 'center',
      }, { transform: [{ scale }] }]}>
        {checked && <CheckIcon color="#FFF" size={20} />}
      </Animated.View>

      <View style={{ flex: 1 }}>
        <Text style={{
          fontSize: 16, fontWeight: '600',
          color: checked ? '#94A3B8' : '#F8FAFC',
          textDecorationLine: checked ? 'line-through' : 'none',
        }}>
          {label}
        </Text>
        {subtitle && (
          <Text style={{ fontSize: 14, color: '#64748B' }}>{subtitle}</Text>
        )}
      </View>
    </Pressable>
  );
}
```

## Swipe Actions

### List Item with Swipe
```tsx
// components/SwipeableAreaItem.tsx
import { Swipeable } from 'react-native-gesture-handler';

function SwipeableAreaItem({ area, onComplete, onBlock }: Props) {
  const renderRightActions = () => (
    <Pressable
      onPress={() => onBlock(area.id)}
      style={{
        backgroundColor: '#EF4444',
        justifyContent: 'center',
        alignItems: 'center',
        width: 80,
      }}
    >
      <BlockIcon color="#FFF" size={24} />
      <Text style={{ color: '#FFF', fontSize: 12, marginTop: 4 }}>Blocked</Text>
    </Pressable>
  );

  const renderLeftActions = () => (
    <Pressable
      onPress={() => onComplete(area.id)}
      style={{
        backgroundColor: '#22C55E',
        justifyContent: 'center',
        alignItems: 'center',
        width: 80,
      }}
    >
      <CheckIcon color="#FFF" size={24} />
      <Text style={{ color: '#FFF', fontSize: 12, marginTop: 4 }}>Done</Text>
    </Pressable>
  );

  return (
    <Swipeable renderRightActions={renderRightActions} renderLeftActions={renderLeftActions}>
      <AreaCard area={area} />
    </Swipeable>
  );
}
```

## Optimistic UI Pattern
```typescript
// ALWAYS update UI immediately, sync in background
async function toggleSurfaceComplete(objectId: string) {
  // 1. Haptic feedback (instant)
  Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);

  // 2. Update local state (instant UI update)
  setObjects(prev => prev.map(o =>
    o.id === objectId
      ? { ...o, status: 'complete', completed_at: new Date().toISOString() }
      : o
  ));

  // 3. Show success toast (instant)
  showToast('Surface marked complete ✅');

  // 4. Write to PowerSync local DB (instant, syncs later)
  await db.execute(
    `UPDATE production_area_objects SET status = 'complete', completed_at = ? WHERE id = ?`,
    [new Date().toISOString(), objectId]
  );
  // PowerSync syncs to Supabase in background — user doesn't wait
}
```

## Offline Indicator
```tsx
// components/OfflineBanner.tsx
import { useStatus } from '@powersync/react-native';

function OfflineBanner() {
  const status = useStatus();

  if (status.connected) return null;

  return (
    <View style={{
      backgroundColor: '#F59E0B',
      paddingVertical: 6,
      paddingHorizontal: 16,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 8,
    }}>
      <WifiOffIcon size={14} color="#0F172A" />
      <Text style={{ fontSize: 13, color: '#0F172A', fontWeight: '600' }}>
        Offline — changes will sync when connected
      </Text>
    </View>
  );
}
// Place this at the top of every screen, below the header
```

## Status Colors (High Contrast)
```typescript
// constants/colors.ts
export const STATUS = {
  complete:    { bg: '#22C55E', text: '#FFF', icon: 'check-circle' },
  in_progress: { bg: '#F59E0B', text: '#FFF', icon: 'clock' },
  blocked:     { bg: '#EF4444', text: '#FFF', icon: 'alert-circle' },
  not_started: { bg: '#4B5563', text: '#9CA3AF', icon: 'circle' },
  skipped:     { bg: '#6B7280', text: '#D1D5DB', icon: 'skip-forward' },
} as const;

// Usage — always as badges, never as text color
function StatusBadge({ status }: { status: keyof typeof STATUS }) {
  const s = STATUS[status];
  return (
    <View style={{
      backgroundColor: s.bg,
      paddingHorizontal: 10,
      paddingVertical: 4,
      borderRadius: 12,
      flexDirection: 'row',
      alignItems: 'center',
      gap: 4,
    }}>
      <Icon name={s.icon} size={14} color={s.text} />
      <Text style={{ color: s.text, fontSize: 12, fontWeight: '700' }}>
        {status.replace('_', ' ').toUpperCase()}
      </Text>
    </View>
  );
}
```

## Progress Bar
```tsx
// components/ProgressBar.tsx
import Animated, { useAnimatedStyle, withTiming } from 'react-native-reanimated';

function ProgressBar({ percent, height = 12 }: { percent: number; height?: number }) {
  const color = percent >= 100 ? '#22C55E' : percent > 50 ? '#F59E0B' : '#3B82F6';

  const animatedStyle = useAnimatedStyle(() => ({
    width: withTiming(`${Math.min(percent, 100)}%`, { duration: 500 }),
  }));

  return (
    <View style={{
      height,
      backgroundColor: '#334155',
      borderRadius: height / 2,
      overflow: 'hidden',
    }}>
      <Animated.View style={[{
        height: '100%',
        backgroundColor: color,
        borderRadius: height / 2,
      }, animatedStyle]} />
    </View>
  );
}
```

## Floating Action Button
```tsx
// components/FAB.tsx
function FAB({ icon, label, onPress }: { icon: string; label: string; onPress: () => void }) {
  return (
    <Pressable
      onPress={() => {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        onPress();
      }}
      style={{
        position: 'absolute',
        bottom: 24,
        right: 24,
        height: TOUCH.FAB,
        paddingHorizontal: 20,
        backgroundColor: '#F97316',  // brand-orange
        borderRadius: TOUCH.FAB / 2,
        flexDirection: 'row',
        alignItems: 'center',
        gap: 8,
        // Shadow
        shadowColor: '#000',
        shadowOffset: { width: 0, height: 4 },
        shadowOpacity: 0.3,
        shadowRadius: 8,
        elevation: 8,
      }}
    >
      <Icon name={icon} size={22} color="#FFF" />
      <Text style={{ color: '#FFF', fontSize: 16, fontWeight: '700' }}>{label}</Text>
    </Pressable>
  );
}

// Usage per screen:
// Area list:    <FAB icon="send" label="Submit Report" onPress={submitReport} />
// Safety tab:   <FAB icon="plus" label="New Document" onPress={newSafetyDoc} />
// Docs tab:     <FAB icon="plus" label="New Ticket" onPress={newTicket} />
```

## Dark Mode Theme
```typescript
// constants/theme.ts
export const dark = {
  background: '#0F172A',      // slate-900
  card: '#1E293B',            // slate-800
  cardElevated: '#334155',    // slate-700 (modals, popovers)
  text: '#F8FAFC',            // slate-50
  textSecondary: '#94A3B8',   // slate-400
  textMuted: '#64748B',       // slate-500
  border: '#334155',          // slate-700
  accent: '#F97316',          // brand-orange
  accentLight: '#FB923C',     // orange-400
  // Status
  success: '#22C55E',
  danger: '#EF4444',
  warning: '#F59E0B',
  info: '#3B82F6',
};

export const light = {
  background: '#F8FAFC',
  card: '#FFFFFF',
  cardElevated: '#F1F5F9',
  text: '#0F172A',
  textSecondary: '#64748B',
  textMuted: '#94A3B8',
  border: '#E2E8F0',
  accent: '#F97316',
  accentLight: '#EA580C',
  success: '#22C55E',
  danger: '#EF4444',
  warning: '#F59E0B',
  info: '#3B82F6',
};
```

## Typography
```typescript
// constants/typography.ts
export const FONT = {
  // Sizes — NEVER below 14
  xs: 14,       // minimum (secondary info, timestamps)
  sm: 15,       // captions
  base: 16,     // body text, surface names
  lg: 18,       // area labels, section headers
  xl: 22,       // screen titles
  xxl: 28,      // dashboard numbers

  // Weights — NEVER light/thin
  medium: '500' as const,
  semibold: '600' as const,
  bold: '700' as const,
} as const;
```

## Screen Keep-Awake
```typescript
// On Area Detail screen — prevent phone from sleeping while working
import { useKeepAwake } from 'expo-keep-awake';

function AreaDetail() {
  useKeepAwake(); // screen stays on while this component is mounted
  // ...
}
```

## Common Errors to Avoid
- ❌ Touch targets smaller than 48dp — instant reject, untappable with gloves
- ❌ Light/thin fonts — unreadable in sunlight
- ❌ Font size below 14sp — squinting is not an option
- ❌ Subtle status colors — bold, obvious, high contrast only
- ❌ Blocking UI on network requests — optimistic updates always
- ❌ No haptic feedback on taps — user thinks the tap didn't register
- ❌ Hamburger menus — bottom tabs always visible, always
- ❌ Complex multi-step forms — break into single-screen steps or tap-to-select
- ❌ Light mode only — dark mode is default, outdoor readability demands it
- ❌ Animations longer than 300ms — field workers don't wait for animations
