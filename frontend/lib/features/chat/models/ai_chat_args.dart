import 'package:mediscanx_mobile/features/diagnostic/models/diagnostic_result.dart';

class AIChatArgs {
  final DiagnosticResult? preloadedResult;
  final String? scanContextId;
  final String? initialPrompt;

  const AIChatArgs({
    this.preloadedResult,
    this.scanContextId,
    this.initialPrompt,
  });
}
