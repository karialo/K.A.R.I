# === K.A.R.I. Entry Point ===
# Primary runtime bootstrapper for K.A.R.I.
# Handles startup of D.E.V.I.L. Core, display systems, module initialization, and async behaviors

import importlib.util
import time
import asyncio
import os
import random

# === Environment Configuration ===
os.environ["SDL_AUDIODRIVER"] = "dummy"  # Prevents audio system crash on headless systems

# === Core Systems ===
from core import devil_core, logger
from core.logger import log_kari_async
from display.retina_array import RetinaArray
from core.menu_engine import MenuEngine, set_retina

# Import just the class from the actual internal module
from internal.memory_cortex.memory_cortex import MemoryCortex

# ----------------------------------------------------------------------------------
# Async Background Task: Periodic Banter from Voice Box (if loaded and ready)
# ----------------------------------------------------------------------------------
async def background_banter(core):
    await asyncio.sleep(5)  # Initial delay after boot
    while True:

        print("[BANTER TASK] Triggering banter line")

        voice_box = core.modules.get("Voice Box")
        memory = core.modules.get("Memory Cortex")
        if voice_box and getattr(voice_box, "ready", False):
            mood = memory.get_current_mood() if memory else "neutral"
            context = {
                **core.data_store.get("vitals", {}),
                "module_name": random.choice(core.attached_internal) if core.attached_internal else "Unknown Module"
            }
            await voice_box.say(
                phrase_type="banter",
                mood=mood,
                context=context
            )
        await asyncio.sleep(random.randint(15, 60))

# ----------------------------------------------------------------------------------
# Main Boot Sequence
# ----------------------------------------------------------------------------------
async def main():
    # Step 1: Preload Memory Cortex for early logging and boot memory
    preloaded_cortex = MemoryCortex()
    preloaded_cortex.meta_data = {
        "version": "1.0",
        "type": "internal",
        "description": "Preloaded Memory Cortex (boot logging)"
    }
    preloaded_cortex.__path_hint__ = os.path.join("internal", "memory_cortex")
    preloaded_cortex.log_event("System", "INFO", "Memory Cortex ghost-loaded before core startup")

    # Step 2: Initialize Retina display (external display module)
    retina = RetinaArray()
    set_retina(retina)
    logger.retina = retina
    retina.splash("K.A.R.I.", "SYNAPSYS CORE BOOTING...")
    await asyncio.sleep(2)
    retina.clear()

    # Step 3: Launch D.E.V.I.L. Core with preloaded cortex
    preloaded = {"memory_cortex": preloaded_cortex}
    core = devil_core.DEVILCore(preloaded_modules=preloaded)
    core.memory = preloaded_cortex
    core.memory.log_event("System", "INFO", "Memory Cortex bound into DEVILCore post-init")

    # Step 4: Attach all internal + prosthetic modules
    await core.scan_and_attach("internal", category="internal")
    await asyncio.sleep(1)
    await core.scan_and_attach("prosthetics", category="prosthetic")
    await asyncio.sleep(1)

    # Step 5: Summary output (includes visual K.A.R.I. log and readiness)
    await core.show_summary()

    # Step 6: Launch menu interface if available
    menu_task = None
    if hasattr(core, "menu") and core.menu:
        menu_task = asyncio.create_task(core.menu.run())

    # Step 7: Launch background banter loop (only after VoiceBox is ready)
    banter_task = asyncio.create_task(background_banter(core))

    # Step 8: Runtime loop — heartbeat of the AI
    try:
        await core.run_forever()

    # Step 9: Shutdown cleanup
    except (asyncio.CancelledError, KeyboardInterrupt):
        if menu_task:
            menu_task.cancel()
            try:
                await menu_task
            except asyncio.CancelledError:
                pass
        retina.write_line("SIGNAL INTERRUPT: Shutting down...")

# ----------------------------------------------------------------------------------
# Runtime Entry Point
# ----------------------------------------------------------------------------------
if __name__ == "__main__":
    asyncio.run(main())
