# Project Vision

## Problem

Western beauty and wellness brands increasingly need to understand Xiaohongshu (小红书), the Chinese social platform where beauty purchasing decisions are researched and made. Chinese color-cosmetics brands that grew up on the platform are now expanding into Western markets, consumer trends that surface there sometimes reach Western consumers months later, and the platform itself gained a wave of Western users in 2025. Yet the content is out of reach for most Western teams: it is written in Chinese, inside a closed mobile ecosystem, and much of its meaning lives in community conventions — for example, 避雷 ("mine warning") posts that flag products to avoid, or 平替 ("affordable substitute") posts that compare dupes — that literal translation does not convey.

Existing tooling does not close this gap. Enterprise social-listening suites treat Chinese platforms as a shallow add-on; domestic Chinese analytics tools have Chinese-only interfaces and assume cultural fluency; raw scraper data is cheap but uninterpreted. What actually closes the gap is a bilingual analyst reading, interpreting, and writing in English.

That analyst work is the problem this software addresses. Done manually, it does not scale to a weekly cadence: screenshots accumulate in a phone camera roll with no structure; translation happens ad hoc and is lost afterward; there is no searchable archive to answer "what have I seen about ingredient X?"; and assembling a weekly report takes roughly four hours, with no reliable way to trace any claim back to the post that supports it. The evidence problem matters most: an intelligence report whose claims cannot be verified against sources is not credible.

## Intended Users

RedThread has one primary user in its first version: the analyst — a bilingual (Chinese/English) researcher who captures Xiaohongshu content daily and produces a weekly English-language intelligence report. I am that analyst, so the project will be used for real work every week, not only demonstrated.

Readers of the exported reports (Western beauty brand and agency teams) are indirect beneficiaries but never touch the application; they only see the exported deliverable. The design anticipates that additional analysts could use the system later, but v1 is deliberately single-user and single-role.

## Goals

The project should help the analyst:

- Capture a Xiaohongshu post from a phone screenshot, a pasted URL, or a CSV batch in under 30 seconds of active effort per post, including annotation.
- Turn raw captures into structured, bilingual records automatically (OCR → translation → entity extraction → embedding), while keeping every machine output correctable by the analyst.
- Build a searchable bilingual corpus in which a question like "what are consumers saying about sunscreen texture?" returns relevant posts with evidence, in English or Chinese.
- Annotate posts quickly against a fixed taxonomy (category, trend type, consumer signal, recommended action, optional trend origin) using keyboard-first interaction.
- Reduce weekly report production from ~4 hours to 1 hour or less.
- Guarantee that every claim in an exported report carries a citation resolving to a captured source post — the report builder should make uncited claims structurally impossible.

## Why This Project

This project sits at the intersection of my degree and my background. As a CS major, it exercises full-stack development, asynchronous pipeline design, vector search, and integration of AI services behind clean abstractions — all directly relevant to the AI-engineering roles I am targeting after graduation. As a native Chinese speaker familiar with Chinese internet platforms, I can supply the ground truth the system needs (correct translations, correct cultural annotations), which makes the project genuinely buildable by me and hard to build without that background.

It is also not a demo-only project. I intend to use it weekly to produce real intelligence output for freelance research work, which means the software will be dogfooded continuously and its usability claims tested against reality.

## Initial Scope

Included in the first version:

- Capture: mobile-friendly batch image upload, manual URL paste with duplicate detection, CSV import, and an authenticated capture API.
- Enrichment pipeline: OCR, translation, entity extraction, and embedding as independent, retryable steps with per-step status.
- Five screens, and only five: Inbox (pipeline status), Triage (review + annotate), Library (search), Report Editor (citation-based assembly), Export Preview.
- Report export as styled HTML rendered to PDF.
- Single analyst account; all content manually curated by the analyst for research and analysis purposes — the system performs no automated bulk collection.

Intentionally not included yet:

- Client-facing portal or client accounts; clients receive exported documents only.
- A standalone chat/Q&A interface over the corpus.
- Browser clipper extension.
- Multi-user support, roles, or permissions.
- Analytics dashboards, charts, or computed trend scores — interpretation is the analyst's job, and the system records it rather than computing it.
- Platforms beyond Xiaohongshu and categories beyond beauty/wellness. The schema keeps a door open (a platform field on captured posts), but the first version walks through none of it.
