import traceback
try:
    from google import genai
    print("google.genai (новый SDK) OK")
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()

try:
    from voice_processor import process_voice, format_voice_confirmation
    print("voice_processor OK — всё готово!")
except Exception as e:
    print(f"voice_processor ERROR: {e}")
    traceback.print_exc()
