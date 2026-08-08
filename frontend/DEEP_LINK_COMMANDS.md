# Deep Link Testing Commands

## Test on Android

```powershell
# When app is closed (cold start)
adb shell am start -a android.intent.action.VIEW -d "mediscanx://password-reset" com.example.mediscanx

# When app is running (hot link)
adb shell am start -a android.intent.action.VIEW -d "mediscanx://password-reset?token=test123&type=recovery" com.example.mediscanx

# With WireGuard/Supabase token simulation
adb shell am start -a android.intent.action.VIEW -d "mediscanx://password-reset?access_token=eyJhbGc&expires_in=3600&type=recovery" com.example.mediscanx
```

## Test on iOS (using xcrun)

```bash
# Assuming Xcode is installed
xcrun simctl openurl booted "mediscanx://password-reset"

# If you have a physical device
sudo killall usbmuxd  # Reset USB connection if needed
xcrun simctl openurl <DEVICE_UDID> "mediscanx://password-reset"
```

## Check if scheme is registered

### Android
```powershell
adb shell pm query-activities -a android.intent.action.VIEW -d mediscanx://example
```
Should show: `mediscanx_mobile`

### iOS
```bash
xcrun simctl openurl booted "mediscanx://test"
# Check console output for success
```

## Verify Supabase Redirect Configuration

Use curl to test:

```bash
# Replace YOUR_SUPABASE_URL and YOUR_ANON_KEY
curl -X POST "YOUR_SUPABASE_URL/auth/v1/recover" \
  -H "Content-Type: application/json" \
  -H "apikey: YOUR_ANON_KEY" \
  -d '{
    "email": "test@example.com",
    "redirect_to": "mediscanx://password-reset"
  }' \
  -v
```

Expected response should confirm the redirect_to value.

## Monitor App Logs

### Android
```powershell
adb logcat -s Flutter
```

### iOS
```bash
# From Xcode Console or:
log stream --predicate 'process == "MediScanX"'
```

Watch for lines with:
- 🔗 Initial deep link
- 🔍 Parsing URI
- ✅ Password reset link detected

