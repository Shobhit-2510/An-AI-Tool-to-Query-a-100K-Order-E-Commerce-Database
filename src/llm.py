"""Provider abstraction over two free LLM tiers: Google Gemini and Groq.

One interface, `generate(prompt, provider)`, so the eval harness can swap models
with a single argument. Both clients are created lazily and cached so importing
this module never requires both API keys to be present.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

PROVIDERS = ("gemini", "groq")

GEMINI_MODEL = "gemini-2.5-flash"
GROQ_MODEL = "llama-3.3-70b-versatile"


@lru_cache(maxsize=1)
def _gemini_client():
    from google import genai

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    return genai.Client(api_key=key)


@lru_cache(maxsize=1)
def _groq_client():
    from groq import Groq

    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set.")
    return Groq(api_key=key)


def _gemini_generate(prompt):
    from google.genai import types

    resp = _gemini_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0),
    )
    return resp.text


def _groq_generate(prompt):
    resp = _groq_client().chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return resp.choices[0].message.content


def generate(prompt, provider="gemini"):
    """Return raw model text for `prompt` using the chosen provider."""
    if provider == "gemini":
        return _gemini_generate(prompt)
    if provider == "groq":
        return _groq_generate(prompt)
    raise ValueError(f"Unknown provider {provider!r}; expected one of {PROVIDERS}.")
