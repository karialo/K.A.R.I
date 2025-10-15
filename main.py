import asyncio
from core import devil_core
from internal.memory_cortex.memory_cortex import MemoryCortex

memory = MemoryCortex()
preloaded = {
    "memory_cortex": memory
}

DEVIL = devil_core.DEVILCore(preloaded_modules=preloaded, debug=True)

async def main():
    # ✅ NOW safe to call the async method
    if hasattr(DEVIL, "mood") and hasattr(DEVIL.mood, "initialize"):
        await DEVIL.mood.initialize()

    await DEVIL.scan_and_attach("internal", category="internal")
    await DEVIL.scan_and_attach("prosthetics", category="prosthetic")
    await DEVIL.show_summary()
    await DEVIL.run_forever()

if __name__ == "__main__":
    asyncio.run(main())
