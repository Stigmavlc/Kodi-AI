# Uninstall

How to fully remove Kodi-AI from your device.

---

## 1. Remove the add-on

In Kodi on the Shield:

1. **Add-ons → My add-ons → Services → Kodi-AI**
2. Press **OK → Uninstall**.

This stops the service thread and removes the addon code. It does **not**
delete the state directory or the addon's userdata.

---

## 2. Remove the repository add-on (optional)

If you installed via the repository method:

1. **Add-ons → My add-ons → Add-on repository → Kodi-AI Repository**
2. Press **OK → Uninstall**.

---

## 3. Wipe state (recommended for clean uninstall)

The state directory holds your bot token, OpenRouter API key, audit log,
and session snapshots. Kodi does **not** delete this on uninstall. To
remove it:

### From the Shield (file manager)

Navigate to:

```
Internal storage → Android → data → org.xbmc.kodi → files → .kodi
            → userdata → addon_data → service.kodi.ai
```

Delete the `service.kodi.ai` folder.

### From a shell (adb)

```bash
adb shell rm -rf /sdcard/Android/data/org.xbmc.kodi/files/.kodi/userdata/addon_data/service.kodi.ai
```

Adjust the path if your Kodi is the LibreElec or Kodi-on-Android-TV
variant; the addon-data subpath is the same in all cases.

---

## 4. Revoke the Telegram bot (optional)

If you don't plan to reuse the bot:

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. `/mybots → <your bot> → Bot Settings → Delete Bot → confirm`.

---

## 5. Revoke the OpenRouter key (optional)

1. Open <https://openrouter.ai/keys>.
2. Revoke the key you used.

---

After steps 1, 3, 4, and 5, no trace of Kodi-AI remains on your device or
in any service it ever called.
