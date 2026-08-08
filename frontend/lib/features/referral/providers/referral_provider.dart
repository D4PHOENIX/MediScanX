import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../models/referral_models.dart';
import '../services/referral_service.dart';

// Provide the Service
final referralServiceProvider = Provider((ref) => ReferralService());

// Controller State Model
class ReferralState {
  final bool isLoading;
  final ReferralResponse? response;
  final String? errorMessage;

  ReferralState({this.isLoading = false, this.response, this.errorMessage});
}

// The Controller Logic
class ReferralNotifier extends StateNotifier<ReferralState> {
  final ReferralService _service;

  ReferralNotifier(this._service) : super(ReferralState());

  Future<void> submitReferral({
    required String patientId,
    required List<String> scanIds,
  }) async {
    state = ReferralState(isLoading: true);

    final result = await _service.generateReferral(
      patientId: patientId,
      scanIds: scanIds,
    );

    if (result != null) {
      state = ReferralState(isLoading: false, response: result);
    } else {
      state = ReferralState(
          isLoading: false,
          errorMessage: "Failed to generate referral. Please check connection."
      );
    }
  }

  void reset() {
    state = ReferralState();
  }
}

final referralProvider = StateNotifierProvider<ReferralNotifier, ReferralState>((ref) {
  return ReferralNotifier(ref.read(referralServiceProvider));
});