# MediScanX AI Agent Guidelines

## Architecture Overview
MediScanX is a Flutter telemedicine app for AI-powered diagnostic triage of ECG, X-rays, and skin lesions. It uses an offline-first architecture with PowerSync for real-time sync between local Drift SQLite database and Supabase cloud backend.

**Key Components:**
- **Features**: Auth (login/register/password reset), Dashboard (user profile + diagnostic modules), Diagnostic (AI analysis screens), AI Chat (conversational interface), Referral (package management)
- **Core**: Database (Drift ORM on PowerSync), Config (app constants), Utils, Themes
- **Shared**: Models, Services (sync coordinator), Widgets
- **State Management**: Riverpod with code generation (`@riverpod` annotations)
- **Navigation**: Go Router with auth-based redirects
- **Data Flow**: Supabase auth → PowerSync sync → Drift local queries → Riverpod providers → UI

**Database Schema** (`lib/core/config/drift_database.dart`):
- `PatientRecords`: User profiles for patients
- `DoctorProfiles`: User profiles for doctors  
- `ScanResults`: Diagnostic scan data and AI results
- `ChatMessages`: AI chat conversation history
- `AppSyncStatus`: Sync tracking for offline operations

## Development Workflows

### Code Generation
Run `flutter pub run build_runner watch` for continuous generation of:
- Riverpod providers (`@riverpod` → `*.g.dart`)
- Freezed models (`@freezed` → `*.freezed.dart`) 
- JSON serializable models (`@JsonSerializable` → `*.g.dart`)
- Drift database code (`@DriftDatabase` → `*.g.dart`)

### Database Operations
- Schema changes require updating `drift_database.dart` and incrementing `schemaVersion`
- Migrations defined in `MigrationStrategy.onUpgrade()`
- Use `DatabaseManager.drift` for Drift queries, `DatabaseManager.powersync` for direct PowerSync access

### Building & Running
- `flutter pub get` to install dependencies
- `flutter run` for development (auto-restarts on code changes)
- `flutter build apk` / `flutter build ios` for production builds
- Web builds: `flutter build web` (uses WASM SQLite)

### Testing
- Unit tests: `flutter test`
- Widget tests: `flutter test test/widget_test.dart`
- Integration tests: Manual testing required for sync functionality

## Code Patterns & Conventions

### State Management
Use Riverpod providers for all state:
```dart
@riverpod
class MyNotifier extends _$MyNotifier {
  @override
  FutureOr<MyState> build() async {
    // Initialize state
    return MyState();
  }
  
  void updateData() {
    state = AsyncValue.data(state.value!.copyWith(...));
  }
}
```

### Database Queries
Prefer Drift's type-safe queries over raw SQL:
```dart
// Good
final patients = await db.getScansByUser(userId);

// Avoid raw SQL unless necessary
```

### Error Handling
Use `AsyncValue.guard()` for async operations:
```dart
state = await AsyncValue.guard(() async {
  // Operation that might fail
});
```

### UI Components
- Use `ConsumerWidget` for screens needing providers
- Follow Material 3 design with custom color scheme
- Implement hover effects for web/desktop compatibility
- Use `Image.asset()` with error builders for robust asset loading

### File Organization
- Feature-first: `lib/features/{feature}/` contains screens, providers, models
- Shared components: `lib/shared/` for reusable widgets/services
- Core utilities: `lib/core/` for app-wide concerns
- Generated files excluded from analysis (see `analysis_options.yaml`)

### Authentication Flow
- Supabase handles auth state
- `GoRouterRefreshStream` triggers route rebuilds on auth changes
- Protected routes redirect to `/login` when unauthenticated
- User role stored in Supabase `userMetadata['role']` (Patient/Doctor)

### Offline-First Sync
- PowerSync manages bidirectional sync with Supabase
- Local changes marked with `syncStatus: 'pending'`
- Sync coordinator (`lib/shared/services/sync_provider.dart`) handles background sync
- UI shows "Offline-First" indicator when disconnected

## Key Files
- `lib/main.dart`: App initialization, routing, auth guard
- `lib/core/database/database_manager.dart`: PowerSync + Drift setup
- `lib/core/config/drift_database.dart`: Database schema and migrations
- `lib/features/dashboard/screens/dashboard_screen.dart`: Main UI with diagnostic cards
- `pubspec.yaml`: Dependencies and asset declarations</content>
<parameter name="filePath">C:\Users\arham\StudioProjects\MediScanX\AGENTS.md
