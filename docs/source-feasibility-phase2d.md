# Source Feasibility Audit - Phase 2D

## Overview

This document evaluates candidate sources for the Gal/VN Radar Phase 2D expansion.
The criteria for inclusion are:
1. Official public API or RSS/Atom feed available.
2. Stable unauthenticated endpoint.
3. Stable item IDs for deduplication.
4. No browser rendering, Cloudflare bypass, or arbitrary HTML scraping required.
5. No authentication or session cookies required.

## Findings

| Source | Public API | RSS/Atom | Auth Required | Stable IDs | Recommended | Notes |
|--------|------------|----------|---------------|------------|-------------|------|
| **itch.io** | Limited | Yes | No | Yes | **Yes** | Native RSS feeds available by appending `/devlog.rss` to project URLs (e.g. `https://creator.itch.io/game/devlog.rss`). |
| **DLsite** | No | No | No (for public info) | No | **No** | No official API or RSS. Requires brittle HTML scraping or undocumented internal endpoints. Subject to Cloudflare blocks. Deferred. |
| **Ci-en** | No | No | Yes (for most content) | No | **No** | No official API or RSS. Sister site to DLsite. Private posts require auth, which violates the no-login constraint. Deferred. |
| **Fantia** | No | No | Yes | No | **No** | No official RSS or API. Requires active session/login. Scraping violates ToS. Deferred. |

## Implementation Decision

Based on the rules outlined in Phase 2D requirements:
- **itch.io** is the only reliable candidate meeting the project's simplicity and stability constraints. We will implement an `ItchAdapter` to parse itch.io RSS feeds (using our generic RSS parsing structure).
- **DLsite, Ci-en, and Fantia** are DEFERRED due to lack of official public structured endpoints, requirement of web scraping, and/or reliance on authentication. Any available official RSS feeds for DLsite/Ci-en/Fantia (if they existed) could be consumed via the existing generic `RSSAdapter`.

We will implement exactly **ONE** source in Phase 2D: **itch.io**.
