# Deep Link Testing Guide for MediScanX Password Reset

## Issue
App isn't catching the password reset deep link when clicking the email button.

## Step-by-Step Debugging

### 1. **Check the Actual Email Link**
- Open the password reset email in your email client
- Right-click (or long-press) on the "Reset Password" button
- Copy the link address
- Check what URL it actually contains
- ✅ It should look like: `mediscanx://...` or contain a redirect parameter pointing to `mediscanx://password-reset`

### 2. **Reinstall the App** (Critical!)
After manifest/plist changes, you MUST rebuild:

```powershell
# Clean the build
flutter clean
flutter pub get

# Rebuild for your target platform
flutter run -d android    # For Android
# or
flutter run -d ios        # For iOS
```

### 3. **Enable Deep Link Logging**
Run the app and watch the console output for these logs:

```
🔗 Initial deep link: mediscanx://...
🔍 Parsing URI - Scheme: mediscanx, Host: password-reset, ...
✅ Password reset link detected, navigating...
```

If you see debug logs but NOT the "✅" message, the URI format is different than expected.

### 4. **Manual Deep Link Test** (Android only)
Open Android Studio terminal and run:

```powershell
adb shell am start -a android.intent.action.VIEW -d "mediscanx://password-reset" com.example.mediscanx
```

If the app opens and navigates to password reset, the deep link setup is correct.

### 5. **Check Supabase Email Configuration**

Go to **Supabase Dashboard → Authentication → Templates → Recovery** and verify:

- The email body contains: `<a href="{{ .ConfirmationURL }}">Reset Password</a>`
- In **URL Configuration → Additional Redirect URLs**, verify you have: `mediscanx://password-reset`

If the redirect URL isn't whitelisted in Supabase, it will send a different link.

### 6. **If Still Not Working**

Check your **Supabase Project → Authentication → Settings → User Experience → Email Link Expiry** and make sure it's reasonable (default: 24 hours).

Also verify the email is actually being sent FROM Supabase with the correct link. You can:
- Check Supabase **Auth → Users** and click the user to see their email history
- Look at Supabase **Project → Edge Functions → Logs** if you're using custom handlers

---

## Expected Flow

```
1. User taps "Reset Password" in email
2. iOS/Android system recognizes mediscanx:// scheme
3. Opens MediScanX app (or brings it to foreground)
4. app_links plugin captures the URI
5. Flutter code in main.dart receives it
6. Debug logs show 🔗 URI received
7. Router navigates to /password-reset
8. PasswordResetScreen opens
9. User enters new password → Done!
```

---

## Common Issues & Fixes

| Issue | Cause | Fix |
|-------|-------|-----|
| Deep link not caught | Manifest/plist not updated | Reinstall app after `flutter clean` |
| Link opens web browser | Email client doesn't recognize scheme | Use a native email client (Gmail, Outlook) |
| "URI is null" in logs | No initial link detected | Tap the link WHILE email app is in foreground |
| "Unknown host" in logs | URI format different | Check actual email link URL |
| Works in Android but not iOS | Info.plist not updated | Rebuild iOS with `flutter clean` |

---

## Next Steps

1. **Run the app with the updated code**
2. **Check the console logs** for the 🔗 symbols
3. **Send a test password reset email**
4. **Tap the link in the email**
5. **Paste the logs here** if it still doesn't work

