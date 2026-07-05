# RedThread

## Overview

RedThread is an internal intelligence-production platform that turns Xiaohongshu (小红书) beauty content into English strategic insights for Western beauty and wellness brands.

Xiaohongshu is the platform where Chinese beauty consumers research and decide what to buy, but its content is effectively unreadable for Western brand teams: it is in Chinese, lives inside a closed mobile app, and depends on cultural context (community slang, review conventions) that machine translation alone does not carry. A bilingual analyst can read it — but doing so at a useful scale is an operations problem: screenshots pile up on a phone, translations are ad hoc, nothing is searchable later, and assembling a weekly intelligence report takes hours with no reliable way to trace a claim back to its source post.

RedThread is the production line that fixes this. The analyst captures posts (screenshots, URLs, CSV batches); a processing pipeline runs OCR, translation, entity extraction, and embedding; the analyst reviews and annotates each post with a fixed taxonomy in a keyboard-first triage screen; everything lands in a searchable bilingual library; and a report builder assembles weekly reports in which every claim carries a citation that resolves to a captured source post.

A core design principle: the app is a factory, not the product. The weekly report is the product. The platform exists to make producing that report fast, verifiable, and repeatable by a single analyst.

## Current Status

Sprint 1 — project definition. The four project documents below are complete; no application code exists yet. Sprint 2 begins implementation, starting with the narrowest vertical slice: one image in → OCR → translation → database → bilingual side-by-side display in the browser.

## Project Documents

- [project-vision.md](docs/project-vision.md)
- [requirements.md](docs/requirements.md)
- [architecture.md](docs/architecture.md)

## Setup Notes

The project is not yet runnable. Planned setup, to be kept current as implementation lands:

- Single-command startup via Docker Compose (web client, API server, worker, PostgreSQL, Redis, Qdrant).
- Stack: React (client), Flask (API), PostgreSQL (relational store), Qdrant (vector store), Celery + Redis (async pipeline).
- AI provider credentials (OCR / translation / extraction / embedding) supplied through a `.env` file; a `.env.example` will document every required variable.
- Content in the system is manually curated by the analyst for research and analysis purposes; the system does not perform automated bulk collection.
