"""Shared helper for generating text on the fly with the OpenAI API.

Every function here is defensive on purpose: if OPENAI_API_KEY isn't set, or the request fails
for any reason (network error, timeout, bad response, content filter), generate_text() returns
None instead of raising. Callers MUST handle None -- normally by falling back to a static
message or telling the user AI isn't configured -- rather than assuming it always succeeds.
"""

import logging

import aiohttp

import config

log = logging.getLogger("bot.ai")

_API_URL = "https://api.openai.com/v1/chat/completions"


def is_configured() -> bool:
    """Whether an OpenAI API key is set, i.e. whether AI features can work at all."""
    return bool(config.OPENAI_API_KEY)


async def generate_text(
    prompt: str,
    *,
    system: str = None,
    max_tokens: int = 250,
    temperature: float = 1.0,
) -> str | None:
    """Asks OpenAI to generate text from a prompt.

    Returns the generated text (stripped), or None if AI isn't configured or the call failed
    in any way -- missing key, network/timeout error, non-200 response, content filter, or a
    response shape that doesn't parse. Never raises.
    """
    if not config.OPENAI_API_KEY:
        return None

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": config.OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _API_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                # content_type=None: don't blow up if OpenAI sends a slightly different
                # content-type header than aiohttp expects -- we still want the JSON body.
                data = await resp.json(content_type=None)
                if resp.status != 200:
                    log.warning("OpenAI API returned HTTP %s: %s", resp.status, str(data)[:300])
                    return None
    except (aiohttp.ClientError, TimeoutError) as e:
        log.warning("OpenAI API request failed: %s", e)
        return None
    except ValueError as e:
        # Malformed/non-JSON body.
        log.warning("OpenAI API returned unparseable JSON: %s", e)
        return None

    try:
        choices = data.get("choices") or []
        if not choices:
            log.warning("OpenAI API returned no choices: %s", str(data)[:300])
            return None
        message = choices[0].get("message") or {}
        text = (message.get("content") or "").strip()
        if not text and choices[0].get("finish_reason") == "content_filter":
            log.warning("OpenAI API response was blocked by the content filter")
        return text or None
    except (AttributeError, TypeError, KeyError, IndexError) as e:
        log.warning("Failed to parse OpenAI API response: %s", e)
        return None
