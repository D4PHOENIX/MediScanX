import 'package:powersync/powersync.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

class SupabaseConnector extends PowerSyncBackendConnector {
  final SupabaseClient supabase;
  final String powerSyncUrl;

  SupabaseConnector({
    required this.supabase,
    required this.powerSyncUrl,
  });

  // ==========================================
  // 1. FETCH CREDENTIALS (AUTHORIZE DOWNLOADS)
  // ==========================================
  @override
  Future<PowerSyncCredentials?> fetchCredentials() async {
    // 1. Grab the live Supabase session
    final session = Supabase.instance.client.auth.currentSession;

    // 2. If not logged in, return null (PowerSync will wait)
    if (session == null) return null;

    // 3. Grab the secure JWT token
    final token = session.accessToken;

    // 4. Hand the token to PowerSync!
    return PowerSyncCredentials(
      endpoint: powerSyncUrl,
      token: token,
    );
  }
  // ==========================================
  // 2. UPLOAD DATA (PUSH LOCAL CHANGES TO CLOUD)
  // ==========================================
  @override
  Future<void> uploadData(PowerSyncDatabase database) async {
    // 1. Get the queue of offline actions (inserts, updates, deletes)
    final transaction = await database.getNextCrudTransaction();
    if (transaction == null) return; // Nothing to sync!

    try {
      // 2. Loop through every change the user made locally
      for (var crud in transaction.crud) {
        final table = supabase.from(crud.table);

        // 3. Push the change to Supabase based on what type of action it was
        switch (crud.op) {
          case UpdateType.put:
          // PUT handles both creating new rows and entirely replacing existing ones
            await table.upsert(crud.opData!);
            break;

          case UpdateType.patch:
          // PATCH handles updating specific fields of an existing row
            await table.update(crud.opData!).eq('id', crud.id);
            break;

          case UpdateType.delete:
          // DELETE removes the row
            await table.delete().eq('id', crud.id);
            break;
        }
      }

      // 4. If the cloud accepted all changes, clear them from the local queue
      await transaction.complete();

    } on PostgrestException catch (e) {
      // If there's a database error (like a strict RLS policy blocking the upload)
      print('Supabase Database Error: ${e.message}');
      // We don't complete the transaction so it stays in the queue to be fixed/retried
    } catch (e) {
      // If there's a network error (e.g. internet dropped mid-upload)
      print('Upload failed. PowerSync will keep the data cached and retry later. Error: $e');
      // PowerSync will automatically try again next time it connects!
    }
  }
}