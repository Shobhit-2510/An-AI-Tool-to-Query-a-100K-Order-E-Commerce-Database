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

# Overridable via env so the eval can pick a model with free quota headroom
# (e.g. gemini-2.5-flash-lite has a much larger free daily request allowance).
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# Fail fast instead of hanging if an API stalls or retries internally.
TIMEOUT_SECONDS = 45


@lru_cache(maxsize=1)
def _gemini_client():
    from google import genai
    from google.genai import types

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set.")
    # timeout is in milliseconds for the google-genai SDK.
    return genai.Client(
        api_key=key,
        http_options=types.HttpOptions(timeout=TIMEOUT_SECONDS * 1000),
    )


@lru_cache(maxsize=1)
def _groq_client():
    from groq import Groq

    key = os.environ.get("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not set.")
    return Groq(api_key=key, timeout=TIMEOUT_SECONDS, max_retries=1)


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
