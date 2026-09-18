"""Smoke test for the Groq API.

Runs a single chat completion against Groq's llama-3.3-70b-versatile model.

Usage:
    cd backend
    GROQ_API_KEY=... uv run python scripts/test_groq.py

The `groq` package is optional at import time so pytest collection does not
fail on environments where it is not installed.
"""

import os


def main() -> None:
    try:
        from groq import Groq
    except ImportError:
        print("The 'groq' package is not installed. Install it with: pip install groq")
        return

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("GROQ_API_KEY environment variable is not set.")
        return

    client = Groq(api_key=api_key)

    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": "Explain the importance of fast language models",
            }
        ],
        model="llama-3.3-70b-versatile",
    )

    print(chat_completion.choices[0].message.content)


if __name__ == "__main__":
    main()
