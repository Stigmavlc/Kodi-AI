# Remote paste from your phone

Typing a long bot token (e.g. `7012345678:AAFqLZ9hM_xqZ5w...`) on a TV's
on-screen keyboard is miserable. Kodi has a built-in HTTP control
interface that lets phone remote apps paste text into any focused input
field on the TV. This is the recommended way to enter the bot token
during Kodi-AI setup.

## Step 1 — enable Kodi's HTTP control

On the Android TV / Shield:

1. **Kodi → Settings (gear icon) → Services → Control.**
2. Enable **Allow remote control via HTTP.**
3. Set a username + password (defaults are `kodi` / blank — change them).
4. Note the **port** (default 8080).
5. Find the Shield's LAN IP in Settings → System → Network — write it
   down (e.g. `192.168.1.42`).

That's it on the TV side.

## Step 2a — Kore (Android)

Kore is the official Kodi remote from the XBMC Foundation. Free.

1. Install [Kore from Google Play](https://play.google.com/store/apps/details?id=org.xbmc.kore).
2. Open Kore → it scans your network and offers to add the Shield.
3. Tap the Shield → enter the username + password from Step 1.
4. To paste:
   - On the Shield, open **Kodi-AI → Configure → Telegram tab**.
   - Focus the **Bot token** field (use the TV remote to highlight it
     and press OK once to open the on-screen keyboard).
   - On your phone, in Kore: tap the keyboard icon at the bottom →
     paste your clipboard.
   - Tap Done on Kore. Kodi closes the on-screen keyboard with your
     token populated.

## Step 2b — Yatse (iOS)

[Yatse](https://yatse.tv/) is a paid third-party remote (Android-only
historically, but works well on iOS too).

1. Install Yatse from the App Store.
2. Add the Shield (it auto-discovers; enter the credentials from Step 1).
3. The keyboard-input flow is the same as Kore.

## Step 3 — use it for the bot token

1. Copy your bot token to the phone's clipboard (in Telegram, long-press
   the token BotFather sent you and tap **Copy**).
2. On the Shield, in Kodi-AI Configure, open the Bot token field.
3. On the phone, open Kore/Yatse → keyboard input → paste → send.

The token populates. Press OK on the Configure dialog. Kodi-AI validates
the token, fills in the pairing command, and you're 30 seconds away
from a working setup.

## Troubleshooting

- **Can't reach the HTTP control.** Confirm the Shield's IP is reachable
  from your phone (same Wi-Fi, no router AP isolation). Try
  `http://<shield-ip>:8080/` in your phone's browser — you should see a
  Kodi login prompt.
- **"401 Unauthorized" in Kore.** Re-enter username + password (case-
  sensitive). Kodi resets the password to blank by default.
- **Paste sends but the field stays empty.** Make sure the on-screen
  keyboard is actually OPEN on the TV when you tap "send" on the phone.
  Some Kore versions silently fail if no input field is focused.

## Privacy note

The HTTP control interface is on your LAN only — don't port-forward it
to the public internet. Anyone with the credentials can fully control
Kodi (play / pause / install addons / etc.).
