const cache = new Map<string, string>();

/**
 * Shorten a URL using TinyURL's free anonymous endpoint.
 * Returns the short URL on success, or the original URL on failure
 * so callers can use it without extra error handling.
 */
export async function shortenUrl(longUrl: string): Promise<string> {
  const cached = cache.get(longUrl);
  if (cached) return cached;

  try {
    const res = await fetch(
      `https://tinyurl.com/api-create.php?url=${encodeURIComponent(longUrl)}`
    );
    if (!res.ok) throw new Error(`TinyURL responded ${res.status}`);
    const short = (await res.text()).trim();
    if (!short.startsWith('http')) throw new Error(`Unexpected response: ${short}`);
    cache.set(longUrl, short);
    return short;
  } catch (err) {
    console.error('[Shortener] Failed, returning original URL:', (err as Error).message);
    return longUrl;
  }
}
