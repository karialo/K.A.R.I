"""
K.A.R.I. Mood Engine 🎭
Tracks emotional state over time, influenced by memory, events, and system feedback.
"""

class MoodEngine:
    def __init__(self, cortex=None):
        self.mood = "neutral"
        self.level = 50  # Percent intensity
        self.cortex = cortex  # Optional connection to MemoryCortex

        if self.cortex:
            saved = self.cortex.recall("current_mood")
            if saved:
                self.mood = saved

    def get_mood(self):
        return self.mood, self.level

    def set_mood(self, mood, level=50):
        self.mood = mood
        self.level = max(0, min(100, level))
        if self.cortex:
            self.cortex.set_current_mood(mood)
            self.cortex.log_event("MoodEngine", "INFO", f"Mood set to '{mood}' at {self.level}%")

    def adjust_level(self, delta):
        self.level = max(0, min(100, self.level + delta))
        if self.cortex:
            self.cortex.log_event("MoodEngine", "DEBUG", f"Mood level adjusted by {delta}: now {self.level}%")

    def react(self, trigger):
        """Let her mood react to a known trigger string."""
        table = {
            "insult": ("grumpy", +20),
            "compliment": ("happy", +30),
            "panic": ("anxious", +40),
            "idle": ("neutral", -10),
            "tickle": ("manic", +15),
            "404": ("feral", +100)
        }
        if trigger in table:
            mood, delta = table[trigger]
            self.set_mood(mood, self.level + delta)
        else:
            if self.cortex:
                self.cortex.log_event("MoodEngine", "WARN", f"Unknown mood trigger: '{trigger}'")
