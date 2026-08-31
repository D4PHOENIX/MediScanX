// lib/features/dashboard/providers/temporal_provider.dart
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:supabase_flutter/supabase_flutter.dart';
import '../../diagnostic/providers/scan_history_provider.dart';
import '../services/temporal_service.dart';
import '../models/temporal_models.dart';

final temporalServiceProvider = Provider((ref) => TemporalService());

final patientHistoryProvider = FutureProvider.family<PatientHistoryResponse?, String>((ref, modality) async {
  if (modality.isEmpty) return null;

  // Reactively re-fetch from API whenever local DB changes (e.g. new scan)
  final userId = Supabase.instance.client.auth.currentUser?.id;
  if (userId != null) {
    ref.watch(userScanHistoryProvider(userId));
  }

  final service = ref.watch(temporalServiceProvider);
  return await service.getPatientHistory(modality: modality);
});

final patientTrendsProvider = FutureProvider.family<TrendAnalysis?, String>((ref, modality) async {
  if (modality.isEmpty) return null;

  // Reactively re-fetch from API whenever local DB changes (e.g. new scan)
  final userId = Supabase.instance.client.auth.currentUser?.id;
  if (userId != null) {
    ref.watch(userScanHistoryProvider(userId));
  }

  final service = ref.watch(temporalServiceProvider);
  return await service.getPatientTrends(modality);
});
