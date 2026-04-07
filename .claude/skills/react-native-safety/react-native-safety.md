# Skill: react-native-safety
> Digital signatures, camera patterns, PDF viewing, push notifications, biometric auth
> Track App | Phase T1-T4 | Used by: safety docs, work tickets, delivery, signoffs

## When to Activate
- Implementing digital signature capture (JHA, PTP, Toolbox, any sign-off)
- Camera integration for QC photos, blocked evidence, delivery confirmation
- Viewing PDFs in-app (safety documents, work instructions)
- Push notification setup and handling
- Biometric auth for secure actions

## Digital Signatures

### In-App Signing
```typescript
// SignatureCapture.tsx
import SignatureCanvas from 'react-native-signature-canvas';

function SignatureCapture({ onSave }: { onSave: (base64: string) => void }) {
  const signatureRef = useRef<SignatureCanvas>(null);

  return (
    <View style={{ height: 200, borderWidth: 2, borderColor: '#334155', borderRadius: 12 }}>
      <SignatureCanvas
        ref={signatureRef}
        onOK={(base64) => onSave(base64)}
        backgroundColor="#1E293B"     // dark mode card bg
        penColor="#F8FAFC"             // white pen on dark
        minWidth={3}                   // thick line for finger drawing
        maxWidth={6}
        dotSize={4}
        style={{ flex: 1 }}
      />
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', padding: 8 }}>
        <Button title="Clear" onPress={() => signatureRef.current?.clearSignature()} />
        <Button title="Save" onPress={() => signatureRef.current?.readSignature()} />
      </View>
    </View>
  );
}
```

### QR Code Signing (for others who don't have the app)
```typescript
// Generate a signing token
async function generateSigningLink(documentId: string): Promise<string> {
  const token = crypto.randomUUID();
  await db.execute(
    `INSERT INTO document_signoffs (id, document_id, organization_id, token, status)
     VALUES (?, ?, ?, ?, 'pending')`,
    [uuid(), documentId, orgId, token]
  );
  // This URL points to the Takeoff web app's public signing page
  return `https://notchfield.io/sign/${token}`;
}

// Display QR code
import QRCode from 'react-native-qrcode-svg';

function SigningQR({ url }: { url: string }) {
  return (
    <View style={{ alignItems: 'center', padding: 20 }}>
      <QRCode value={url} size={200} backgroundColor="#1E293B" color="#F8FAFC" />
      <Text style={{ color: '#94A3B8', marginTop: 12 }}>Scan to sign this document</Text>
    </View>
  );
}
```

### Signature Storage
- Signature image (base64 PNG) → upload to Supabase Storage `signatures/` bucket
- Store URL in `document_signoffs.signature_url`
- Also store: signer name, timestamp, GPS coordinates (proof of location)

## Camera Patterns

### Photo Capture Service
```typescript
// photo-service.ts
import * as ImagePicker from 'expo-image-picker';
import * as Camera from 'expo-camera';

// Quick photo (from camera)
async function takePhoto(): Promise<FieldPhoto> {
  const { status } = await Camera.requestCameraPermissionsAsync();
  if (status !== 'granted') throw new Error('Camera permission required');

  const result = await ImagePicker.launchCameraAsync({
    quality: 0.8,              // good quality, reasonable size
    allowsEditing: false,      // no cropping — we need the full image
    exif: true,                // include GPS data
    base64: false,             // don't load into memory
  });

  if (result.canceled) return null;

  const asset = result.assets[0];
  const { lat, lng } = await getCurrentPosition();

  return {
    localUri: asset.uri,
    width: asset.width,
    height: asset.height,
    latitude: lat,
    longitude: lng,
    timestamp: new Date().toISOString(),
    syncStatus: 'pending',     // will upload when online
  };
}

// Pick from gallery (for existing photos)
async function pickPhoto(): Promise<FieldPhoto> {
  const result = await ImagePicker.launchImageLibraryAsync({
    quality: 0.8,
    allowsMultipleSelection: true,  // for batch photo upload
    selectionLimit: 10,
  });
  // ... similar processing
}
```

### Photo Upload Queue (Offline-Safe)
```typescript
// Photos are large — can't sync through PowerSync
// Use a separate upload queue

async function queuePhotoUpload(photo: FieldPhoto, context: {
  type: 'qc' | 'blocked' | 'delivery' | 'safety' | 'progress';
  areaId?: string;
  ticketId?: string;
  documentId?: string;
}) {
  // Save to local queue table
  await db.execute(
    `INSERT INTO field_photos (id, local_uri, latitude, longitude, context_type, context_id, sync_status)
     VALUES (?, ?, ?, ?, ?, ?, 'pending')`,
    [uuid(), photo.localUri, photo.latitude, photo.longitude, context.type, context.areaId || context.ticketId]
  );
}

// Background upload service (runs when online)
async function processPhotoQueue() {
  const pending = await db.getAll(
    `SELECT * FROM field_photos WHERE sync_status = 'pending' LIMIT 5`
  );

  for (const photo of pending) {
    try {
      const fileName = `${photo.context_type}/${photo.id}.jpg`;
      const { data } = await supabase.storage
        .from('field-photos')
        .upload(fileName, await fetch(photo.local_uri).then(r => r.blob()));

      const publicUrl = supabase.storage.from('field-photos').getPublicUrl(fileName).data.publicUrl;

      await db.execute(
        `UPDATE field_photos SET sync_status = 'uploaded', remote_url = ? WHERE id = ?`,
        [publicUrl, photo.id]
      );
    } catch (e) {
      // Will retry next cycle
      console.error('Photo upload failed, will retry:', e);
    }
  }
}
```

### Photo Display
- Show local URI while pending upload (instant display)
- Replace with remote URL after upload
- Thumbnail for lists: resize to 200px width locally
- Full-res on tap: load from remote URL (or local if not uploaded yet)

## PDF Viewing

### In-App PDF Viewer
```typescript
import Pdf from 'react-native-pdf';

function PdfViewer({ url }: { url: string }) {
  return (
    <Pdf
      source={{ uri: url }}
      style={{ flex: 1 }}
      enablePaging={true}
      horizontal={false}
      fitPolicy={0}  // fit width
      onError={(error) => console.error('PDF error:', error)}
    />
  );
}
```

- Use for: viewing safety documents, work instructions, plans
- NOT for: drawing takeoff (that's Takeoff web only)
- Cache PDFs locally for offline viewing

## Push Notifications

### Setup
```typescript
// notifications.ts
import * as Notifications from 'expo-notifications';

async function registerForPushNotifications(): Promise<string | null> {
  const { status } = await Notifications.requestPermissionsAsync();
  if (status !== 'granted') return null;

  const token = (await Notifications.getExpoPushTokenAsync({
    projectId: EAS_PROJECT_ID,
  })).data;

  // Save token to profile in Supabase
  await supabase.from('profiles').update({
    push_token: token,
    push_platform: Platform.OS,
  }).eq('id', userId);

  return token;
}

// Handle incoming notifications
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});
```

### Notification Types
| Type | Trigger | Content |
|------|---------|---------|
| Delivery arriving | Warehouse marks "shipped" | "Delivery arriving for L3-E2 in ~30 min" |
| New assignment | Supervisor assigns area | "You've been assigned to Floor 3 bathrooms" |
| Cert expiring | 30 days before expiry | "Your OSHA-10 cert expires on April 15" |
| PM message | PM sends note via web | "Check RFI #42 before starting L3-E4" |
| Block resolved | PM marks block resolved | "Material delivered — L3-E4 unblocked" |

### Sending Push from Supabase Edge Function
```typescript
// supabase/functions/send-push/index.ts
await fetch('https://exp.host/--/api/v2/push/send', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    to: userPushToken,
    title: 'Delivery Arriving',
    body: 'TL-04 Diplomacy Light Grey for L3-E2',
    data: { type: 'delivery', deliveryId: '...' },
  }),
});
```

## Biometric Auth
```typescript
import * as LocalAuthentication from 'expo-local-authentication';

// Use for: confirming signatures, submitting daily report
async function authenticateForSignature(): Promise<boolean> {
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  if (!hasHardware) return true; // skip if no biometric hardware

  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: 'Confirm your identity to sign',
    cancelLabel: 'Cancel',
    fallbackLabel: 'Use passcode',
  });

  return result.success;
}
```

## Common Errors to Avoid
- ❌ Requiring camera permission at app startup — request when user first taps camera
- ❌ Loading full-res photos in list views — always use thumbnails
- ❌ Blocking UI while uploading photos — upload in background, show progress
- ❌ Sending push notifications without user consent — always check permission first
- ❌ Storing signatures as base64 in the database — upload to Storage, store URL
- ❌ PDF viewer for large construction plans — that's Takeoff web, not Track
