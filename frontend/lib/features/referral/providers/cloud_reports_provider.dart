import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/referral_models.dart';
import '../services/referral_service.dart';

class CloudReportsState {
  final bool isLoading;
  final List<CloudReportItem> reports;
  final String? errorMessage;
  final int totalCount;

  CloudReportsState({
    this.isLoading = false,
    this.reports = const [],
    this.errorMessage,
    this.totalCount = 0,
  });

  CloudReportsState copyWith({
    bool? isLoading,
    List<CloudReportItem>? reports,
    String? errorMessage,
    int? totalCount,
  }) {
    return CloudReportsState(
      isLoading: isLoading ?? this.isLoading,
      reports: reports ?? this.reports,
      errorMessage: errorMessage ?? this.errorMessage,
      totalCount: totalCount ?? this.totalCount,
    );
  }
}

class CloudReportsNotifier extends StateNotifier<CloudReportsState> {
  final ReferralService _service;

  CloudReportsNotifier(this._service) : super(CloudReportsState());

  Future<void> fetchReports({int limit = 20, int offset = 0, bool refresh = false}) async {
    if (refresh) {
      state = state.copyWith(isLoading: true, errorMessage: null);
    } else {
      state = state.copyWith(isLoading: true, errorMessage: null);
    }

    final response = await _service.getReports(limit: limit, offset: offset);
    
    if (response != null) {
      final updatedReports = refresh ? response.items : [...state.reports, ...response.items];
      state = state.copyWith(
        isLoading: false,
        reports: updatedReports,
        totalCount: response.totalCount,
      );
    } else {
      state = state.copyWith(
        isLoading: false,
        errorMessage: 'Failed to fetch reports from the cloud.',
      );
    }
  }

  Future<bool> deleteReport(String reportId) async {
    try {
      final success = await _service.deleteReport(reportId);
      if (success) {
        state = state.copyWith(
          reports: state.reports.where((r) => r.reportId != reportId).toList(),
          totalCount: state.totalCount > 0 ? state.totalCount - 1 : 0,
        );
        return true;
      }
      return false;
    } catch (e) {
      rethrow;
    }
  }
}

final cloudReportsProvider = StateNotifierProvider.autoDispose<CloudReportsNotifier, CloudReportsState>((ref) {
  return CloudReportsNotifier(ReferralService());
});
