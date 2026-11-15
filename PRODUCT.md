# Paul工作台

<!-- impeccable:product-schema 1 -->

## Platform

web

The design artifacts are desktop web prototypes for a macOS PySide6 application. The production application remains a native macOS app with embedded web workspaces; this record does not authorize a framework migration.

## Users

Chinese-speaking video creators using a Mac. The workbench connects media, manuscripts and voice production.

## Product Purpose

Connect video/audio acquisition, local transcription, manuscript comparison and scoring, selected excerpts, composition, voice generation, and existing knowledge-base integrations.

## Operating Context

Long-running local transcription, batch tasks, source manuscripts, model connections, and manually reviewed results. Preserve running tasks; never restart during an active transcription. Prototype content must be explicitly illustrative and must not invoke real models or cloud services.

## Capabilities and Constraints

Existing functions include local audio/video transcription, public-link downloading, homepage collection, live recording with quality selection, voice generation, document/audio libraries, and local editorial scoring/selection/composition. Scoring uses a user-selected configured model connection; no provider is selected automatically. Existing model files, manuscripts, canonical CLI installation, security identities and data paths remain compatible.

## Brand Commitments

Product name: Paul工作台. The native application offers forest, sky, latte, cream and blush palettes. The design directory retains earlier interface concepts as references.

## Evidence on Hand

The current implementation lives in app/src/ui and app/src/core/content_workbench.py. Design previews use authored sample content and do not represent live task status.

## Product Principles

Show the next action and task state clearly. Preserve source material and provenance. Separate illustrative previews from real operations. Keep paid cloud calls explicit.

## Accessibility & Inclusion

Use concise, actionable language, reduce competing controls, and keep primary actions visible. Design priority: download → transcription → manuscript → voice as a continuous workflow.
