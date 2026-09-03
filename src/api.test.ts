import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from './api';

describe('public API client', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('treats an anonymous auth response as a signed-out visitor', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })));

    await expect(api.me()).resolves.toBeNull();
  });

  it('returns the health payload for a successful liveness check', async () => {
    const payload = { status: 'healthy', services: { worker: 'remote-gpu' } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(payload)));

    await expect(api.health()).resolves.toEqual(payload);
  });
});
