# FRONTEND_IMPLEMENTATION.md

## Routes

```txt
/                  → redirect to /my-ai
/my-ai             → My AI landing
/conversations     → Conversation index
/conversations/:id → Conversation shell
/tasks             → Tasks index
/tasks/:id         → Task detail
/docs              → Documents / KB index
/docs/:id          → Document reader/editor
/flow              → Flow Center
```

No `/projects/:id` page.

## App shell

```txt
AppShell
  SidebarNav
  Topbar
  ScopeBand
  MainContent
  DrawerHost
```

## Layout

- Sidebar can collapse to icon-only.
- Sidebar and right rail can be drag-resized.
- Persist layout preferences.
- Do not expose prototype-only topbar layout controls in production.

## Component map

### My AI

```txt
MyAILanding
GroundedGreeting
ReadyToShareStrip
MyAIComposer
RoutingSuggestionCard
ShareableDraftItem
```

One composer only. Ready to Share max 3 visible items.

### Conversations

```txt
ConversationIndex
ConversationList
ConversationShell
ConversationHeader
MessageStream
ConversationComposer
TopicRightRail
RoomRightRail
DMRightRail
```

Recent = DMs + Rooms. Active Topics = Topics.

### Tasks

```txt
TaskIndex
TaskList
TaskCard
TaskRightRail
RecognitionPolicyBadge
```

### Documents / KB

```txt
DocumentIndex
DocumentCard
ProjectBriefBadge
DocumentEditor
DocumentRightRail
```

### Flow Center

```txt
FlowCenter
FlowTable
FlowDrawer
MemoryPromptDrawer
MemoryReviewDrawer
AuthorityState
CompressionAnalysis
LineageTimeline
```

## Drawer host

```ts
type DrawerType =
  | "flow_request"
  | "memory_prompt"
  | "memory_review"
  | "edit_request"
  | "create_menu"
  | "notification";
```

## Server-driven permissions

Frontend should render from `authority_check`, not infer from local role strings.

```ts
if (!authority.can_accept) {
  disable("Accept memory");
  show("Request authority review");
}
```

## AI Assistance

AI Assistance buttons are secondary and proposal-only. Sticky CTA footer performs state-changing actions.
