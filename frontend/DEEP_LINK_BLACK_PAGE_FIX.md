# Black Page / Device Disconnect - Complete Debugging Guide

## What Was Fixed
1. ✅ Added 500ms delay before navigation to ensure router is ready
2. ✅ Added try-catch and error handling to PasswordResetScreen initialization
3. ✅ Added detailed logging to every step of the deep link flow
4. ✅ Added error display UI if initialization fails
5. ✅ Added logging to router redirect logic

---

## How to Test Now

### Step 1: Clean & Rebuild (CRITICAL!)
```powershell
Push-Location "C:\Users\arham\StudioProjects\MediScanX"
flutter clean
flutter pub get
flutter run -d android    # or -d ios
```

Wait for the app to build completely and show the home screen.

### Step 2: Watch the Console
As the app runs, watch the console output for these 🟢 **good** logs:
```
🔗 Initial deep link: mediscanx://...
🔀 Router: Checking redirect for /password-reset
🔀 Router: isLoggedIn=false
🔀 Router: isPublicPage=true
🔀 Router: No redirect needed, proceeding to /password-reset
🔐 PasswordResetScreen: Initializing auth listener
🔐 PasswordResetScreen: Auth listener initialized successfully
```

### Step 3: Send Test Email & Tap Link
1. In the app, go to **Login → "Forgot Password?"**
2. Enter your test email
3. Check your email
4. **Tap the password reset link in the email**
5. Watch the console for the flow

---

## Expected Console Output Sequence

### ✅ Good - App navigates to password reset:
```
🔗 Initial deep link: mediscanx://password-reset?access_token=...
🔍 Parsing URI - Scheme: mediscanx, Host: password-reset
✅ Password reset link detected, navigating...
🚀 Navigating to password-reset route
🔀 Router: Checking redirect for /password-reset
🔀 Router: No redirect needed, proceeding to /password-reset
🔐 PasswordResetScreen: Initializing auth listener
```

### ❌ Problem - Supabase link format wrong:
```
🔗 Initial deep link: http://localhost:3000/password-reset?...
❌ Not a mediscanx scheme, ignoring
```
**FIX:** Check Supabase URL Configuration → Additional Redirect URLs

### ❌ Problem - Auth subscription crashes:
```
🔐 PasswordResetScreen: Initializing auth listener
❌ PasswordResetScreen: Auth subscription error: ...
```
**FIX:** App will show error screen with "Retry" button

---

## If You Get Black Page

### Check Console First
1. Open Android Studio / Xcode console
2. Look for any red error messages
3. Search for 🔐 or ❌ symbols
4. Copy the error and verify it

### Common Issues & Fixes

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| Black page, no logs | Crash before logging | Check Xcode/AS console for stack trace |
| "Not a mediscanx scheme" | Email has wrong format | Update Supabase URL Config |
| "Auth subscription error" | Supabase client not ready | Appears as error on screen now |
| "Unknown host" | URI format different | Check actual email link URL |
| Device disconnects | Native bridge crashed | Rebuild with `flutter clean` |

---

## Manual Test (Without Email)

### Android
```powershell
adb shell am start -a android.intent.action.VIEW \
  -d "mediscanx://password-reset" \
  com.example.mediscanx
```

Expected: App opens, you see the password reset screen

### iOS
```bash
xcrun simctl openurl booted "mediscanx://password-reset"
```

---

## If Error Screen Appears

You'll see:
```
⚠️ Initialization Error

[Error message]

[Retry] button
```

This is **good** - it means:
- ✅ Deep link was caught
- ✅ App navigated to password reset
- ✅ Screen initialized but had an error
- 🔧 Error is displayed instead of crashing

**Tap Retry** and watch console to see what the actual error is. Report that error and I can fix it.

---

## Verify Supabase Configuration

### 1. Check URL Configuration
- Go to **Supabase Dashboard → Authentication → URL Configuration**
- In **Additional Redirect URLs**, you should have:
  ```
  mediscanx://password-reset
  ```

### 2. Check Recovery Email Template
- Go to **Authentication → Templates → Recovery**
- Body should contain:
  ```html
  <a href="{{ .ConfirmationURL }}">Reset Password</a>
  ```

### 3. Send a Test Email (from Supabase)
```bash
# Replace with your values
curl -X POST "YOUR_SUPABASE_URL/auth/v1/recover" \
  -H "Content-Type: application/json" \
  -H "apikey: YOUR_ANON_KEY" \
  -d '{"email":"test@example.com","redirect_to":"mediscanx://password-reset"}' \
  -v
```

Check the response - it should show your redirect_to value was accepted.

---

## What Each Log Symbol Means

| Symbol | Meaning | Action |
|--------|---------|--------|
| 🔗 | Deep link received | Good, tracking is working |
| 🔍 | Parsing the URI | Good, checking format |
| ✅ | Link matches password-reset | Good, navigating now |
| 🚀 | Starting navigation | Good, route transition started |
| 🔀 | Router redirect check | Good, auth guard working |
| 🔐 | Password screen initializing | Good, screen loading |
| ⚠️  | Warning (non-critical) | Check the message |
| ❌ | Error (critical) | Report the message |

---

## Next Step: Report Output

If still stuck:
1. Run the app with the updated code
2. Send a password reset email
3. Tap the link
4. **Copy the entire console output**
5. Paste it here

I'll be able to pinpoint exactly where the issue is.

