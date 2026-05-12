# PRODUCTION_GAP_LIST.md

v0.6.2 is wire-ready but not production-complete.

## Remove prototype-only controls

Remove before production:

- Design Parameters FAB
- Copy Params button
- Download HTML button
- topbar Toggle nav button
- topbar Rail width button

Keep production behavior:

- sidebar collapse
- drag-resizable sidebar
- drag-resizable right rail
- persisted layout preferences

## Loading states

Required: My AI grounded greeting, Ready to Share, Conversation list, Message stream, Right rail, Flow Center table, Memory Review drawer, Document list/editor, Task list/detail.

## Empty states

Required: no active scope, no grounded items, no Ready to Share drafts, no conversations, no active topics, no tasks, no documents, no flow requests, no memory candidates.

My AI first-use empty state: “Start here. Think with AI first. Share when ready.”

## Error states

Required: 403 authority failure, authority changed while reviewing, network failure, memory candidate expired, evidence permission denied, document publish failed, scope unavailable, AI assistance failed, stale proposal.

## Notifications drawer

Bell badge needs slim drawer for flow replies, mentions, memory review requests, task updates, topic changes, document review requests. Do not make another inbox page.

## Search

Global search needs type filters, keyboard navigation, recent searches, project-scoped indication, grouped result types.

## Mobile

Desktop prototype does not equal mobile UX. Need bottom nav/compact sidebar, full-screen sheets, right rail as details sheet, compact scope indicator, stepwise Memory Review.

## Accessibility

Need keyboard navigation, drawer focus trap, Escape close, ARIA labels for disabled authority actions, screen-reader text for compression warnings, visible focus states.

## Internationalization

Doctrine strings require careful translation: “Memory crystallization is a separate decision,” “Only blank-start objects live here,” “AI Assistance creates proposals only,” “Project is scope, not page.”

## Identity system

Replace hardcoded glyph avatars with photo/initials/fallback/role badge system.
