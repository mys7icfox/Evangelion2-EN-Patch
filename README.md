# 🤖 Shinseiki Evangelion 2 - Evangelions - English Translation Patch
Welcome to the English fan translation project for *Neon Genesis Evangelion 2* (Shinseiki Evangelion 2: Evangelions, PS2, SLPS-25299)! This project aims to bring the full, immersive Evangelion simulation and story experience to English-speaking fans.

## 📊 Current Status
**v1.0-beta is out.** All of the game's text has now been translated, and the patch is in the testing phase. The remaining work is in-game testing, fitting text to the boxes, and the text that is drawn into images.

| Area | Translated | Tested in-game |
|---|---|---|
| Main story and character dialogue | ✅ | ✅ |
| Battle messages and scripts | ✅ | ✅ |
| Menus, status screens and item text | ✅ | ✅ |
| Secret info menu | ✅ | ✅ |
| Leftover system text (scenario select, choice menus, minigame) | ✅ | 🚧 Testing |
| Free-roam character chat (about 21,000 lines) | ✅ | 🚧 Testing |
| Story-telling phrases (the "what happened today" sentences, all 16 speakers) | ✅ | 🚧 Testing |
| Text baked into images (HUD, logos, title bars) | ❌ | ❌ Not started |
| Native-speaker review and proofreading | ❌ | ❌ Not started |

## 🛠️ How to Install

### What you need
- **Your own clean dump of the Japanese game** as an `.iso` file (Shinseiki Evangelion 2: Evangelions, SLPS-25299). No game data is included in this patch.
- **Python 3**, free from [python.org/downloads](https://www.python.org/downloads/). On Windows, tick **"Add python.exe to PATH"** during setup.
- A way to play the result, such as [PCSX2](https://pcsx2.net/).

### Steps
1. Go to the [Releases](../../releases) page and download the latest release zip.
2. Unzip it. Keep all the files together in one folder.
3. Apply the patch:
   - **Windows:** drag your Japanese `.iso` onto `Apply_Patch.bat`. You can also double-click it and paste the path to your ISO.
   - **Any system:** run `python apply_patch.py your_game.iso EVA2_EN_beta.patch`
4. Wait for it to finish. It checks your ISO, copies it, applies the patch and verifies the result.
5. A new file ending in `_EN.iso` appears next to your original. **Your original ISO is not modified.** Load the new file in your emulator.

### If something goes wrong
- **"Wrong ISO" or a checksum error:** your dump isn't the one this patch was built for. You need an unmodified, uncompressed ISO of the Japanese game. Formats such as CHD, CSO or ISOs that another tool has already modified won't work.
- **"python is not recognized":** Python isn't installed, or wasn't added to PATH. Reinstall it and tick the PATH option.
- **Not enough disk space:** the patcher makes a full copy of the game, so you need roughly the size of the ISO free.
- **Anything else:** open an issue and include the full error message.

## 🎯 Roadmap & What's Next
1. Playtest every area and fix text overflow, line wrapping and awkward phrasing.
2. Confirm word order in the generated story sentences, which are pieced together from fragments.
3. Edit the text that is drawn into images (HUD, logos, title bars).
4. Review by Japanese-reading and native English proofreaders.
5. A more polished full release.

## ⚠️ Beta Notes
This is an early beta. Expect some text that overflows its box, is cut off, or reads awkwardly. Some image-based text is still in Japanese.

## 🤝 Contributing & Feedback
I'm not taking direct translation PRs just yet. However, bug reports are welcome and very helpful, especially for text overflow, text cut off in boxes, typos, awkward phrasing and any Japanese text that remains. Screenshots help a lot. Please say where in the game you saw the problem.

## ⚖️ Disclaimer
This is a non-profit fan project created out of love for the Neon Genesis Evangelion franchise. This project is not affiliated with, endorsed by, or connected to Gainax, Khara, Bandai, or any official rights holders. The patch contains only changed data and no copyrighted game content, so you must supply your own copy of the game. Please support the official releases and merchandise.
