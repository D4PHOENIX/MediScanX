// lib/core/utils/deep_link_debugger.dart

import 'package:app_links/app_links.dart';

/// Helper for manual deep link testing and debugging
class DeepLinkDebugger {
  static final AppLinks _appLinks = AppLinks();

  /// Manually trigger a deep link (for testing)
  static Future<void> testDeepLink(String url) async {
    try {
      final uri = Uri.parse(url);
      debugPrint('🧪 Testing deep link: $url');
      debugPrint('   Parsed - Scheme: ${uri.scheme}, Host: ${uri.host}, Path: ${uri.path}');
      // app_links will process this through uriLinkStream
    } catch (e) {
      debugPrint('❌ Error parsing test deep link: $e');
    }
  }

  /// Get the last deep link that was intercepted
  static Future<Uri?> getLastLink() async {
    try {
      return await _appLinks.getInitialLink();
    } catch (e) {
      debugPrint('❌ Error getting initial link: $e');
      return null;
    }
  }

  /// Print system info for debugging deep links
  static void printDebugInfo() {
    debugPrint('''
    
    ═══════════════════════════════════════════════════════════
    DEEP LINK DEBUG INFO
    ═══════════════════════════════════════════════════════════
    
    Expected Scheme: mediscanx://
    Expected Format: mediscanx://password-reset[?token=xxx&type=recovery]
    
    Android: Check AndroidManifest.xml has:
      <intent-filter>
        <action android:name="android.intent.action.VIEW" />
        <category android:name="android.intent.category.DEFAULT" />
        <category android:name="android.intent.category.BROWSABLE" />
        <data android:scheme="mediscanx" />
      </intent-filter>
    
    iOS: Check Info.plist has:
      <key>CFBundleURLTypes</key>
      <array>
        <dict>
          <key>CFBundleURLSchemes</key>
          <array>
            <string>mediscanx</string>
          </array>
        </dict>
      </array>
    
    ═══════════════════════════════════════════════════════════
    ''');
  }
}

void debugPrint(String message) {
  print(message);
}

