---
name: api-rate-limiter
description: >-
  Design and implement API rate limiting for clients and services. Use when
  building request throttling, handling 429 Too Many Requests, choosing a
  limit algorithm (token bucket, leaky bucket, sliding window), or adding
  exponential backoff and retry logic to an API integration.
tags: [api, rate-limiting, throttling, backoff, retry]
triggers:
  - "rate limit"
  - "429 Too Many Requests"
  - "throttle requests"
  - "exponential backoff"
  - "Retry-After"
author: LangConfig
---

# API Rate Limiter

Use this skill when implementing or debugging rate limiting for API clients
and services.

## When to Use
- Building a client that must respect an upstream API's rate limits
- Handling `429 Too Many Requests` / `Retry-After` responses
- Adding throttling, backoff, or retry to an API integration
- Designing a rate limiter for your own API endpoint

## Key Concepts
1. **Limit algorithms**: token bucket (burst-friendly), leaky bucket (steady
   rate), fixed/sliding window (simple, clock-aligned). Pick by traffic shape.
2. **429 handling**: honor the `Retry-After` header when present; otherwise use
   exponential backoff with jitter.
3. **Client-side throttling**: stay under observed `X-RateLimit-*` headers
   (remaining / reset / limit).
4. **Distributed limits**: share state (e.g. Redis) instead of per-process
   counters when multiple instances run.

## Implementation Steps
1. Identify the limiting side (client vs server) and the limit source
   (headers, docs, SLA).
2. Choose the algorithm that matches the traffic shape (bursts vs steady).
3. Implement the limiter as a small, testable function or class.
4. Add retry-on-429 with exponential backoff + jitter and a max-retry cap.
5. Log rate-limit events (limit, remaining, reset) for observability.

## Pitfalls
- ❌ Fixed delay on every request instead of backoff on consecutive 429s
- ❌ Ignoring `Retry-After` when the server provides it
- ❌ Unlimited retries (thundering herd on recovery)
- ✅ Cap retries, surface the failure, and always respect reset headers
