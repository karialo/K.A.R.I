# internal/sanity_relay/models/mood_model.py

class FakeMoodModel:
    def predict(self, input_data):
        # Simplistic fallback: Just return 'neutral' every time
        return ['neutral'] * len(input_data)
