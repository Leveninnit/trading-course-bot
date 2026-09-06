"""Shared helper for generating text on the fly with the Gemini API.

Every function here is defensive on purpose: if GEMINI_API_KEY isn't set, or the request fails
for any reason (network error, timeout, bad response, safety block), generate_text() returns
None instead of raising. Callers MUST handle None -- normally by falling back to a static
message or telling the user AI isn't configured -- rather than assuming it always succeeds.
"""

import logging

import aiohttp

import config

log = logging.getLogger("bot.ai")

_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"


def is_configured() -> bool:
    """Whether a Gemini API key is set, i.e. whether AI features can work at all."""
    return bool(config.GEMINI_API_KEY)


async def generate_text(
    prompt: str,
    *,
    system: str = None,
    max_tokens: int = 250,
    temperature: float = 1.0,
) -> str | None:
    """Asks Gemini to generate text from a prompt.

    Returns the generated text (stripped), or None if AI isn't configured or the call failed
    in any way -- missing key, network/timeout error, non-200 response, safety block, or a
    response shape that doesn't parse. Never raises.
    """
    if not config.GEMINI_API_KEY:
        return None

    url = _API_URL.format(model=config.GEMINI_MODEL, key=config.GEMINI_API_KEY)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=20)) as resp:
                # content_type=None: don't blow up if Google sends a slightly different
                # content-type header than aiohttp expects -- we still want the JSON body.
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    log.warning("Gemini API returned HTTP %s: %s", resp.status, str(data)[:300])
                    return None
    except (aiohttp.ClientError, TimeoutError) as e:
        log.warning("Gemini API request failed: %s", e)
        return None
    except ValueError as e:
        # Malformed/non-JSON body.
        log.warning("Gemini API returned unparseable JSON: %s", e)
        return None

    try:
        candidates = data.get("candidates") or []
        if not candidates:
            log.warning(
                "Gemini API returned no candidates (likely safety-blocked): %s",
                data.get("promptFeedback"),
            )
            return None
        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        return text or None
    except (AttributeError, TypeError, KeyError, IndexError) as e:
        log.warning("Failed to parse Gemini API response: %s", e)
        return None
