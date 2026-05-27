# Third-Party Notices

Kodi-AI V1 has **zero external Python runtime dependencies** beyond the
Python standard library and the Kodi-provided `xbmc.python` environment.
There is no bundled third-party code in the addon zip.

The add-on does, however, interoperate with three services and one runtime
that deserve acknowledgement.

---

## Kodi (XBMC Foundation)

Kodi-AI runs as an `xbmc.service` and `xbmc.python.script` add-on inside
Kodi 21 (Omega). The add-on uses the `xbmc`, `xbmcaddon`, `xbmcgui`, and
`xbmcvfs` modules provided by the Kodi runtime.

- Project: <https://kodi.tv/>
- License: [GPLv2+](https://github.com/xbmc/xbmc/blob/master/LICENSE.md)

Kodi-AI is an independent third-party add-on and is not affiliated with or
endorsed by the XBMC Foundation.

## Telegram Bot API

All Telegram interaction uses the official Bot API over long-poll HTTPS.

- Docs: <https://core.telegram.org/bots/api>
- License: Telegram's terms of service apply to bot usage.

## OpenRouter

Triage and reasoner LLM calls are routed through OpenRouter.

- Project: <https://openrouter.ai/>
- Models invoked by Kodi-AI are pinned in
  `service.kodi.ai/resources/settings.xml` (`llm.triage_model`,
  `llm.reasoner_model`). Each model has its own upstream license, which
  applies to the model's outputs.

## Python standard library

Kodi-AI relies on `urllib`, `json`, `zlib`, `hashlib`, `threading`,
`queue`, `re`, `os`, `pathlib`, and the rest of the stdlib shipped with
Python 3.11 inside `xbmc.python` 3.0.1.

## script.module.requests

Declared as an `<import>` dependency in `addon.xml` and resolved by Kodi
from the official Kodi repository at install time. Not bundled in the
addon zip.

- Project: <https://requests.readthedocs.io/>
- License: [Apache 2.0](https://github.com/psf/requests/blob/main/LICENSE)

---

If you believe an attribution is missing or incorrect, please open an
issue or email <ivanaguilarmari@gmail.com>.
