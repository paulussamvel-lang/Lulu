# Paul工作台

<!-- impeccable:product-schema 1 -->

## Platform

Native macOS desktop application (PySide6).

The design directory also contains desktop web prototypes and the application has embedded web workspaces. The new creator workbench uses the existing native theme and control foundation; this record does not authorize a framework migration.

## Users

Chinese-speaking video creators using a Mac, including solo creators who collect topics, study reference videos and develop their own manuscripts. The workbench connects source material, editorial decisions, media, manuscripts and voice production.

## Product Purpose

Connect topic intake and filtering, reference-video evidence notes, video/audio acquisition, local transcription, manuscript comparison and scoring, selected excerpts, composition, voice generation, and existing knowledge-base integrations.

## Operating Context

Long-running local transcription, batch tasks, source manuscripts, model connections, and manually reviewed results. Preserve running tasks; never restart during an active transcription. Prototype content must be explicitly illustrative and must not invoke real models or cloud services.

## Capabilities and Constraints

Existing functions include local audio/video transcription, public-link downloading, homepage collection, live recording with quality selection, voice generation, document/audio libraries, and local editorial scoring/selection/composition. Scoring uses a user-selected configured model connection; no provider is selected automatically. Existing model files, manuscripts, canonical CLI installation, security identities and data paths remain compatible.

The native creator workbench adds topic intake from manual records, local text/table/subtitle files, public text pages and user-specified Feishu Docx/Wiki/Base sources. Imports are previewed and selected before saving local copies; existing Feishu documents and topic tables are import-only. Runtime sources and connections are supplied by the user, rather than bundled personal documents, links or account identifiers. Duplicate imports preserve existing edits and source snapshots.

Topic selection leads to actual local video playback, timed segment notes and six analysis dimensions: opening, content order, copy, visuals, editing and ending. Optional AI analysis sends text only after the user chooses a configured model and confirms the request; its result is previewed and explicitly appended to existing notes. It does not infer unseen visual evidence from a transcript. Entering the existing editorial workbench adds linked reference snapshots while preserving original manuscripts, candidates and the user's draft.

Intake does not automatically download attachments, start transcription, download models or invoke a model/cloud service. Public-page and Feishu reads occur only on request; AI calls remain explicit. Local video files are linked in place. Topic data stays in the application data directory and must not enter source control or release artifacts.

## Brand Commitments

Product name: Paul工作台. The native application offers forest, sky, latte, cream and blush palettes. The design directory retains earlier interface concepts as references.

## Evidence on Hand

The current implementation lives in app/src/ui and app/src/core/content_workbench.py. The creator extension is implemented in app/src/ui/creator_workbench.py and app/src/core/creator_workbench.py; its workflow and data boundaries are documented in app/docs/features/creator-workbench.md. Focused core and native UI tests cover import preservation, revision conflicts, text-only model boundaries and editorial snapshot handoff. Design previews use authored sample content and do not represent live task status or verification of a user's remote sources.

## Product Principles

Show the next action and task state clearly. Preserve source material and provenance. Separate illustrative previews from real operations. Keep paid cloud calls explicit.

## Accessibility & Inclusion

Use concise, actionable language, reduce competing controls, and keep primary actions visible. Design priority: download → transcription → manuscript → voice as a continuous workflow.
