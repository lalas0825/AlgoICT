# Skill: gps-tracking
> Geofencing, check-in/out, GPS stamps, background location
> Track App | Phase T1 | Tables: gps_checkins, gps_geofences

## When to Activate
- Implementing check-in/out (manual or automatic)
- Setting up geofences for job sites
- Embedding GPS coordinates in photos
- Any feature that uses device location
- Background location tracking

## Architecture

### Three GPS Layers
```
Layer 1: GEOFENCE      — Auto check-in when phone enters job site boundary
Layer 2: CHECK-IN      — Manual or auto timestamp + coordinates
Layer 3: PHOTO STAMPS  — GPS metadata embedded in every field photo
```

### expo-location Setup
```typescript
// location-service.ts
import * as Location from 'expo-location';

// Request permissions (do this at app startup)
async function requestLocationPermissions(): Promise<boolean> {
  const { status: foreground } = await Location.requestForegroundPermissionsAsync();
  if (foreground !== 'granted') return false;

  // Background needed for geofence
  const { status: background } = await Location.requestBackgroundPermissionsAsync();
  // Background is optional — geofence won't work without it but manual check-in still works
  
  return true;
}

// Get current position (for check-in, photo stamps)
async function getCurrentPosition(): Promise<{ lat: number; lng: number }> {
  const location = await Location.getCurrentPositionAsync({
    accuracy: Location.Accuracy.High,
  });
  return {
    lat: location.coords.latitude,
    lng: location.coords.longitude,
  };
}
```

### Layer 1: Geofence
```typescript
// Define job site boundary (supervisor sets this up once per project)
async function createGeofence(projectId: string, center: { lat: number; lng: number }, radiusMeters: number) {
  // Save to database
  await db.execute(
    `INSERT INTO gps_geofences (id, project_id, organization_id, latitude, longitude, radius, is_active)
     VALUES (?, ?, ?, ?, ?, ?, true)`,
    [uuid(), projectId, orgId, center.lat, center.lng, radiusMeters]
  );

  // Register with expo-location
  await Location.startGeofencingAsync('JOBSITE_GEOFENCE', [{
    identifier: projectId,
    latitude: center.lat,
    longitude: center.lng,
    radius: radiusMeters,
    notifyOnEnter: true,
    notifyOnExit: true,
  }]);
}

// Handle geofence events (in background task)
TaskManager.defineTask('JOBSITE_GEOFENCE', ({ data, error }) => {
  if (error) return;
  const { eventType, region } = data;

  if (eventType === Location.GeofencingEventType.Enter) {
    autoCheckIn(region.identifier); // project_id
  } else if (eventType === Location.GeofencingEventType.Exit) {
    autoCheckOut(region.identifier);
  }
});
```

### Layer 2: Check-in/Out
```typescript
// Manual check-in (button tap)
async function checkIn(projectId: string, userId: string) {
  const { lat, lng } = await getCurrentPosition();

  await db.execute(
    `INSERT INTO gps_checkins (id, project_id, organization_id, user_id, check_in_at, check_in_lat, check_in_lng)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [uuid(), projectId, orgId, userId, new Date().toISOString(), lat, lng]
  );

  // Haptic feedback
  Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
}

// Manual check-out
async function checkOut(checkinId: string) {
  const { lat, lng } = await getCurrentPosition();

  await db.execute(
    `UPDATE gps_checkins SET check_out_at = ?, check_out_lat = ?, check_out_lng = ? WHERE id = ?`,
    [new Date().toISOString(), lat, lng, checkinId]
  );
}

// Auto check-in from geofence (called by background task)
async function autoCheckIn(projectId: string) {
  const userId = await getCurrentUserId();
  const { lat, lng } = await getCurrentPosition();

  // Check if already checked in today
  const existing = await db.getOptional(
    `SELECT id FROM gps_checkins WHERE user_id = ? AND project_id = ? AND check_out_at IS NULL`,
    [userId, projectId]
  );
  if (existing) return; // already checked in

  await db.execute(
    `INSERT INTO gps_checkins (id, project_id, organization_id, user_id, check_in_at, check_in_lat, check_in_lng, auto_detected)
     VALUES (?, ?, ?, ?, ?, ?, ?, true)`,
    [uuid(), projectId, orgId, userId, new Date().toISOString(), lat, lng]
  );

  // Send local notification
  await Notifications.scheduleNotificationAsync({
    content: { title: 'Checked In', body: `Auto check-in at ${projectName}` },
    trigger: null, // immediate
  });
}
```

### Layer 3: Photo GPS Stamps
```typescript
// Embed GPS in photo metadata before saving
import * as MediaLibrary from 'expo-media-library';

async function capturePhotoWithGPS(): Promise<FieldPhoto> {
  const { lat, lng } = await getCurrentPosition();
  const photo = await camera.takePictureAsync({ exif: true });

  // Embed GPS in EXIF data
  const photoWithGPS = {
    uri: photo.uri,
    latitude: lat,
    longitude: lng,
    timestamp: new Date().toISOString(),
    // EXIF GPS data is embedded automatically by expo-camera if location permission granted
  };

  return photoWithGPS;
}
```

## Tables
```sql
CREATE TABLE gps_checkins (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  user_id UUID NOT NULL REFERENCES profiles(id),
  check_in_at TIMESTAMPTZ NOT NULL,
  check_in_lat NUMERIC,
  check_in_lng NUMERIC,
  check_out_at TIMESTAMPTZ,
  check_out_lat NUMERIC,
  check_out_lng NUMERIC,
  auto_detected BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE gps_geofences (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  organization_id UUID NOT NULL REFERENCES organizations(id),
  latitude NUMERIC NOT NULL,
  longitude NUMERIC NOT NULL,
  radius INTEGER NOT NULL DEFAULT 200,  -- meters
  is_active BOOLEAN DEFAULT true,
  created_by UUID REFERENCES profiles(id),
  created_at TIMESTAMPTZ DEFAULT now()
);
```

## Battery Optimization
- Geofence monitoring: LOW battery impact (OS handles it natively)
- getCurrentPosition: use `Accuracy.Balanced` for check-in (not High — saves battery)
- Use `Accuracy.High` ONLY for photo stamps (need precision)
- NO continuous tracking (we don't track the worker's path — just check-in/out and photo locations)
- Background location: ONLY for geofence events, not continuous polling

## Common Errors to Avoid
- ❌ Continuous GPS tracking (drains battery, not needed, privacy concern)
- ❌ Requiring background location permission for basic features — geofence needs it, check-in doesn't
- ❌ Blocking UI while getting location — get location async, show loading indicator
- ❌ Storing high-precision coordinates (10 decimals) — 6 decimals is ~10cm accuracy, enough
- ❌ Forgetting to handle "location permission denied" — app must work without GPS, just no auto check-in
