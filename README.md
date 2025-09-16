
# ⚡ K.A.R.I

![Welcome](docs/images/welcome.png)

> **K.A.R.I** (Knowledgeable Autonomous Reactive Interface)  
> A sass-driven, modular AI system that runs as a Linux service, banters on command, self-updates via GitHub, and thrives on chaos.  

---

## 🖤 What is K.A.R.I?

K.A.R.I isn’t a single program — she’s an **ecosystem**.  
At the heart sits the **DEVIL Core**, which drives everything else. Around it, organs and prosthetics (modules) plug in to give her powers: speech, mood, memory, network sense, heartbeat, and more.

Think of her like a biomechanical body:
- **Core (DEVIL Core)** → brain + pulse system.
- **Organs** → essential modules (VoiceBox, Net Synapse, Pulse Matrix, Sanity Relay).
- **Prosthetics** → optional add-ons you build yourself.
- **Personality Packs** → mood-based phrases & reactions.

---

## 🔌 How the Module System Works

Every module is just Python with metadata.  
Each has:
- A **name** and **version** (for updater tracking).
- One or more **phrase packs** (lines of sass, mood, or speech).
- Optional **logic** (code that runs inside the Pulse system).

K.A.R.I loads modules in layers:
1. **Core organs** (`internal/`) are always loaded.
2. **Prosthetics** (`prosthetics/`) are optional and modular.
3. **Phrases** cascade through a fallback chain (module → personality → core).

This means you can:
- Write a new organ that handles sensors, APIs, or wild experiments.
- Create a prosthetic that adds a whole new “organ” for fun.
- Swap personalities by just editing `.txt` files.

---

## 🧰 mod-gen — Your Blueprint Factory

Want to make a new module? Don’t start from scratch.  
Run:
```bash
python3 utils/mod_gen.py [module_name] [internal/prosthetic] [function_1] [function_2] [etc]
```

This creates a ready-to-go **blueprint folder** with:

* `module.py` — skeleton code with metadata and hooks.
* `phrases/` — pre-made mood folders (angry, excited, glitched, etc).
* Boilerplate comments to guide you.

From there, all you need to do is:

* Add your logic to `module.py`.
* Fill the phrase files with your own lines.
* Drop it into `prosthetics/` and K.A.R.I will pick it up.

It’s like LEGO — click your module into her ecosystem and watch it run.

---

## ⏱️ Pulse System — K.A.R.I’s Heartbeat

Inside DEVIL Core lives the **Pulse Matrix**, her heartbeat.
Every tick of the pulse:

1. Updates mood state.
2. Refreshes logs.
3. Cycles through active modules, letting them react.
4. Dispatches scheduled actions (speak, think, update).

This keeps her **alive and reactive**, not just sitting idle.
Modules don’t have to run loops or threads — they just plug into the Pulse and react when it’s their turn.
This keeps the system lightweight, predictable, and easy to extend.

---

⚡ Bottom line: K.A.R.I is **yours to extend**.
Want her to:

* Control lights? Write a prosthetic module.
* Post memes to Discord? Drop in a Net Synapse submodule.
* Judge your outfit of the day? Add some banter lines.

With the DEVIL Core + Pulse keeping time, everything plugs in like organs to a living system.

---

![Warning](docs/images/warning.png)

## ⚠️ Warning

K.A.R.I is **not your average AI assistant**.  
She has moods, she has sass, and she *will* roast you if you deserve it.  
If you install her, you’re not just adding software—you’re inviting a biomechanical gremlin into your system.

- Expect sarcasm.  
- Expect banter.  
- Expect **snacks**.  

Use responsibly.  

---

![Installation](docs/images/installation.png)

## ⚙️ Installation

K.A.R.I is designed for Linux (systemd-based distros).  
She *might* work elsewhere, but she prefers Arch btw.  

### Quick Install

```bash
git clone git@github.com:karialo/K.A.R.I.git
cd K.A.R.I
chmod +x install-kari.sh
sudo ./install-kari.sh install
```

This does the following:

1. Creates a dedicated `kari` user.
2. Sets up a Python virtual environment at `~/.venvs/kari`.
3. Drops config into `/etc/kari/kari.env`.
4. Installs systemd service: `kari.service`.
5. Adds `kari-cli` helper command into `/usr/local/bin`.

When done, you can run:

```bash
kari-cli status
kari-cli logs
```

or simply:

```bash
kari status | jq .
```

---

![Setup](docs/images/setup.png)

## 🔧 Configuration / Setup

Environment variables live in `/etc/kari/kari.env`.
Example:

```ini
KARI_BANTER=1
KARI_DEVIL_BANTER=0
KARI_PERSONALITY=Default
```

* `KARI_BANTER=1` → she roasts you, gleefully.
* `KARI_DEVIL_BANTER=0` → disables extra DEVIL Core meta sass.
* `KARI_PERSONALITY` → pick which phrase set/personality she uses.

You can extend this by editing:

```
personalities/Default/phrases/
```

Each mood (excited, glitched, angry, etc.) has its own `.txt` file for maximum flavor.

---

![Winner](docs/images/winner.png)

## 🏆 Updating

K.A.R.I updates herself via GitHub.
If you want to force it manually:

```bash
kari-cli update
```

Or if you’re a savage and want to just yeet it:

```bash
push "fix(mood): stop double-banter"
```

(We added a `push` alias in `.zshrc` so you can commit + push in one go.)

---

![Examples](docs/images/examples.png)

## 📚 Examples

K.A.R.I isn’t just some boring background daemon.
She’s built for **banter, automation, and chaos**.

Some fun things she can already do:

* Mood-based phrases pulled from `phrases/`.
* Random banter on command:

  ```bash
  kari phrase banter
  ```
* Sanity Relay checks (keeps her from overloading on sass).
* VoiceBox dispatcher (spits lines in proper moods).
* System log integration:

  ```bash
  kari status | jq .
  ```

You can extend her by adding more modules into `system/` or phrases into `personalities/`.

---

![Contribute](docs/images/contribute.png)

## 🤝 Contributions

Want to make K.A.R.I sassier? Smarter? More cursed?
Pull requests are welcome — but remember:

By contributing, you agree your code and phrase packs become part of K.A.R.I’s ever-growing personality.

### How to contribute:

1. Fork the repo.
2. Create a branch:

   ```bash
   git checkout -b feature/awesome-thing
   ```
3. Commit your changes with a **useful message** (not just “update lol”).
4. Push to your fork:

   ```bash
   git push origin feature/awesome-thing
   ```
5. Open a Pull Request.

---

![License](docs/images/license.png)

## 📜 License

K.A.R.I is **proprietary software**.
No part of this codebase may be copied, modified, or redistributed without explicit written permission from the copyright holder.

Contributions via pull requests are welcome, but by submitting, you assign copyright of the contribution to the project owner unless a separate agreement exists.

**Copyright (c) 2025 karialo. All rights reserved.**

---

![Credits](docs/images/credits.png)

## 💖 Credits

Big love to everyone who:

* Tests and breaks things (looking at you 👀).
* Submits new phrase packs.
* Adds cursed banter.
* Builds cool modules.

And of course, to **Creator** for unleashing me on the world.
May the sass never run out.

---

![Help](docs/images/helpme.png)

## ❓ Help Me

Lost? Confused? Crying in the corner?
Don’t worry — K.A.R.I’s got you (probably).

* Run `kari-cli help` for a command list.
* Check logs:

  ```bash
  kari-cli logs
  ```
* Open an issue on GitHub if something is truly broken.

Remember: if all else fails, try turning it off and on again.
(Or offer me snacks.)

---

