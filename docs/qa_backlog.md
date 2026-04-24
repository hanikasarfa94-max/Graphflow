# QA backlog — features awaiting manual test

Things that passed automated tests + shipped to `graphflow.flyflow.love`, but the user hasn't dogfooded live yet. Run through these before the next submission milestone.

## Scene 2 gated decisions (v0.5 polish) — shipped 2026-04-24 morning

**Setup**: project with a `gate_keeper_map` entry (e.g. `scope_cut → maya`). Two users: a proposer (not the gate-keeper) and the gate-keeper.

- [ ] Proposer types a decision-shape utterance in a gated class ("cut auth from v1"). Edge LLM emits a gated route_proposal card in the proposer's personal stream.
- [ ] Card shows `[⚖ Send for sign-off]` button.
- [ ] Click `Send for sign-off` → proposal lands on the gate-keeper's side.
- [ ] Gate-keeper sees the pending card (currently in their personal stream via the back-compat post; future: pure sidebar inbox).
- [ ] **Verify raw-utterance block (`What they said` / `对方原话`) renders above the agent's framing** on the gate-keeper's card when the two differ. Only appears when `decision_text` is captured (post-0015 proposals).
- [ ] Gate-keeper approves / denies. Proposer sees the outcome card in their personal stream.
- [ ] On approve: DecisionRow exists with `decision_class` + `gated_via_proposal_id` lineage. Visible in the project's decisions list.

## Voting feature (Phase S) — shipped 2026-04-24 afternoon

**Setup**: project with ≥2 owners. One owner = gate-keeper on a class. One owner proposes a decision in that class. (Or use any multi-owner project and rely on the voter pool being owners ∪ gate-keeper.)

### Proposer flow — [🗳 Open to vote] button
- [ ] Proposer's route-proposal card shows the `[🗳 Open to vote]` button alongside `[Send for sign-off]`, only when the authority pool (owners ∪ gate_keeper) has ≥2 members for the class.
- [ ] Button does NOT appear when the pool is 1 (single-authority projects).
- [ ] Clicking `[🗳 Open to vote]` creates the proposal AND opens it to vote in one action — no sign-off detour.
- [ ] Proposer's card collapses to "✓ Opened to vote" / "✓ 已发起投票" on success.

### Voter-side sidebar inbox
- [ ] Every voter in the pool sees a new item in their sidebar inbox badge (count increases).
- [ ] Opening the drawer shows the vote card at top (before routed signals).
- [ ] Card shows: `🗳 Vote pending` + decision-class chip + `2/3 to pass` threshold label + tally row (`✓ 0  ✗ 0`).
- [ ] If proposal has `decision_text`, the raw utterance renders above the agent's framing.
- [ ] Three verdict buttons: `Approve` / `Deny` / `Abstain`.
- [ ] Rationale textarea is optional.

### Vote casting + threshold
- [ ] Cast `approve` as voter 1 → tally updates to `✓ 1  ✗ 0`. My button highlights "✓ Your approve". Proposal stays in-vote.
- [ ] Cast `approve` as voter 2 (pool=3, threshold=2) → resolves as approved, DecisionRow minted with `gated_via_proposal_id` + `decision_class`.
- [ ] Deny-lock: pool=3, 2 denies → resolves as denied, no DecisionRow.
- [ ] Voter can flip their verdict before resolution (approve → deny updates the same row).
- [ ] Tied vote (pool=4, 2 approve + 2 deny) does NOT resolve as approved (strict majority).

### Group stream + proposer stream on resolution
- [ ] Project (team) stream gets a runtime-log card: `🗳 Vote opened on scope cut: ... (threshold 2/3)` when opened, then `✓ Vote approved — scope cut: 2 approve, 0 deny of 3` on resolve.
- [ ] Proposer's personal stream receives the outcome card (loop closes on the triggerer).

### Profile feedback
- [ ] Casting any vote (approve/deny/abstain) bumps the voter's `signal_tally.votes_cast`. Check in `/settings/profile` or via `/api/users/me` if exposed.
- [ ] compute_profile / ProfileTallies reports per-verdict 30d breakdowns.

### Error paths
- [ ] Non-authority member trying to cast a vote → 403 `not_in_voter_pool`.
- [ ] Non-authorized member trying to open-to-vote → 403 `not_authorized_to_open_vote`.
- [ ] Invalid verdict string → 400 `invalid_verdict`.
- [ ] Opening to vote with pool < 2 → 409 `insufficient_voters`.

### i18n
- [ ] Switch to zh locale. All vote UI strings localize (`发起投票`, `你投了赞成`, `{threshold}/{pool} 可通过`, etc.).

---

## Notes
- Prod DB is at `0016_votes (head)`. Migration was applied via `alembic stamp head` because `Base.metadata.create_all()` materialized the `votes` table + `gated_proposals.voter_pool` column on container boot (same pattern as 0014/0015 deploys).
- Credentials: demo users all use password `moonshot2026` per live seed state.
