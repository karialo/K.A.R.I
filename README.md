
# ⚡ K.A.R.I

![Welcome](docs/images/welcome.png)

> **K.A.R.I** (Knowledgeable Autonomous Reactive Interface)  
> A sass-driven, modular AI system that runs as a Linux service, banters on command, self-updates via GitHub, and thrives on chaos.

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

````markdown
---

![Examples](docs/images/examples.png)

## 📚 Examples

K.A.R.I isn’t just some boring background daemon.  
She’s built for **banter, automation, and chaos**.  

Some fun things she can already do:
- Mood-based phrases pulled from `phrases/`.
- Random banter on command:  
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


