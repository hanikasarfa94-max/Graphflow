import React, { useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity,
  Archive,
  ArrowRight,
  Bell,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Database,
  FileText,
  GitBranch,
  Globe2,
  Home,
  Inbox,
  Layers3,
  Lock,
  MessageSquare,
  Network,
  Plus,
  Route,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Users,
  Workflow,
  Zap
} from 'lucide-react';
import './styles.css';

type PageKey =
  | 'home'
  | 'stream'
  | 'my-ai'
  | 'transitions'
  | 'review'
  | 'memory'
  | 'graph'
  | 'work'
  | 'node'
  | 'docs'
  | 'settings';

type PillTone = 'blue' | 'violet' | 'mint' | 'amber' | 'red' | 'slate';

const navItems: Array<{ key: PageKey; label: string; icon: React.ReactNode }> = [
  { key: 'home', label: 'Home', icon: <Home size={18} /> },
  { key: 'stream', label: 'Project Stream', icon: <MessageSquare size={18} /> },
  { key: 'my-ai', label: 'My AI Studio', icon: <Bot size={18} /> },
  { key: 'transitions', label: 'Transitions', icon: <Route size={18} /> },
  { key: 'review', label: 'Review', icon: <ShieldCheck size={18} /> },
  { key: 'memory', label: 'World Memory', icon: <Database size={18} /> },
  { key: 'graph', label: 'Graph', icon: <Network size={18} /> },
  { key: 'work', label: 'Work Graph', icon: <Workflow size={18} /> },
  { key: 'node', label: 'Node Detail', icon: <CircleDot size={18} /> },
  { key: 'docs', label: 'Docs', icon: <FileText size={18} /> },
  { key: 'settings', label: 'Settings', icon: <Settings size={18} /> }
];

function Pill({ children, tone = 'slate' }: { children: React.ReactNode; tone?: PillTone }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

function EvidenceChip({ id, label }: { id: string; label?: string }) {
  return <span className="evidence-chip"><FileText size={13} />{id}{label ? ` · ${label}` : ''}</span>;
}

function SectionTitle({ title, action }: { title: string; action?: string }) {
  return (
    <div className="section-title">
      <h3>{title}</h3>
      {action && <button className="ghost-button small">{action}<ChevronRight size={14} /></button>}
    </div>
  );
}

function Metric({ icon, label, value, delta, tone = 'blue' }: { icon: React.ReactNode; label: string; value: string; delta?: string; tone?: PillTone }) {
  return <div className="metric-card">
    <div className={`metric-icon metric-${tone}`}>{icon}</div>
    <div>
      <div className="metric-value">{value}</div>
      <div className="metric-label">{label}</div>
      {delta && <div className="metric-delta">{delta}</div>}
    </div>
  </div>;
}

function AppShell({ active, setActive, children }: { active: PageKey; setActive: (p: PageKey) => void; children: React.ReactNode }) {
  return <div className="app-frame">
    <aside className="global-nav">
      <div className="brand"><div className="brand-mark">G</div><span>GraphFlow</span></div>
      <nav>
        {navItems.map(item => <button key={item.key} className={`nav-item ${active === item.key ? 'active' : ''}`} onClick={() => setActive(item.key)}>{item.icon}<span>{item.label}</span></button>)}
      </nav>
      <div className="profile-card">
        <div className="avatar">HL</div>
        <div><strong>Hao Lin</strong><span>Pro Plan</span></div>
      </div>
    </aside>
    <main className="workspace">
      <div className="topbar"><div className="search"><Search size={16} /><span>Search nodes, evidence, people, decisions...</span><kbd>⌘K</kbd></div><Bell size={18} /><button className="primary-button"><Plus size={16} />New</button></div>
      {children}
    </main>
    <AskBubble setActive={setActive} />
  </div>;
}

function AskBubble({ setActive }: { setActive: (p: PageKey) => void }) {
  return <button className="ask-bubble" onClick={() => setActive('my-ai')}><Sparkles size={18} />Ask GraphFlow</button>;
}

function PageHeader({ eyebrow, title, subtitle, right }: { eyebrow?: string; title: string; subtitle: string; right?: React.ReactNode }) {
  return <div className="page-header">
    <div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1><p>{subtitle}</p></div>
    {right && <div className="header-right">{right}</div>}
  </div>;
}

const needsMe = [
  ['Should we route the Q2 pricing proposal to Finance?', 'High impact', 'Today 12:00', 'D-102 · M-213'],
  ['Does the partner launch need legal review?', 'Medium impact', 'Tomorrow', 'S-431'],
  ['Should the old onboarding memory be superseded?', 'Review', '2 days', 'M-077'],
  ['Who owns the experiment guardrail definition?', 'Routing', 'Today', 'T-087']
];

function HomePage({ setActive }: { setActive: (p: PageKey) => void }) {
  return <>
    <PageHeader title="Home / Today" subtitle="Daily judgement surface: what requires my judgement now?" right={<div className="status-row"><Pill tone="blue">Asia/Shanghai</Pill><Pill tone="violet">Current project: Pricing Q2</Pill><Pill tone="amber">18 unread routed signals</Pill></div>} />
    <div className="grid home-grid">
      <div className="panel span-6">
        <SectionTitle title="Needs me" action="View all" />
        <div className="list">
          {needsMe.map((item, i) => <button key={item[0]} className="judgement-row" onClick={() => setActive(i === 0 ? 'stream' : 'transitions')}>
            <div className="row-icon warning"><Zap size={16} /></div><div><strong>{item[0]}</strong><span>Evidence: {item[3]}</span></div><Pill tone={i === 0 ? 'red' : 'amber'}>{item[1]}</Pill><span className="deadline">{item[2]}</span>
          </button>)}
        </div>
      </div>
      <div className="panel span-6">
        <SectionTitle title="Active routed questions" action="Transitions" />
        <CompactRows rows={[
          ['Finance model for legacy customer discount?', 'Waiting on Yue · 4 refs', 'waiting'],
          ['Which engineer can judge pricing-system feasibility?', 'Suggested route · 3 refs', 'needs'],
          ['Should Q2 experiment target retained users first?', 'Two conflicting memories', 'review']
        ]} />
      </div>
      <div className="panel span-4"><SectionTitle title="Projects" /><ProjectMiniList /></div>
      <div className="panel span-4"><SectionTitle title="Recent accepted decisions / memory updates" /><CompactRows rows={[
        ['Accepted: layered pricing definition v1.1', 'Canonical · cited by 7 decisions', 'ok'],
        ['Updated: retention-risk memory M-213', 'World Memory · 5 downstream objects', 'ok'],
        ['Superseded: old customer segment model', 'Lineage preserved', 'archived']
      ]} /></div>
      <div className="panel span-4 ask-panel"><SectionTitle title="Ask GraphFlow" /><textarea placeholder="Ask about your judgement load, a project, memory, route, or evidence..." /><div className="action-row"><button onClick={() => setActive('my-ai')} className="primary-button">Open My AI Studio</button><button className="ghost-button">Search memory</button></div></div>
    </div>
  </>;
}

function CompactRows({ rows }: { rows: Array<[string, string, string]> }) {
  return <div className="compact-rows">{rows.map((r) => <div className="compact-row" key={r[0]}><div><strong>{r[0]}</strong><span>{r[1]}</span></div><Pill tone={r[2] === 'ok' ? 'mint' : r[2] === 'waiting' ? 'amber' : r[2] === 'archived' ? 'slate' : 'violet'}>{r[2]}</Pill></div>)}</div>;
}

function ProjectMiniList() {
  return <div className="project-list">{[
    ['New pricing strategy Q2', 72], ['Partner channel launch', 48], ['Agent orchestration upgrade', 35], ['Knowledge graph migration', 21]
  ].map(([name, progress]) => <div className="project-row" key={name as string}><div><strong>{name}</strong><span>Active · {progress}%</span></div><div className="progress"><i style={{ width: `${progress}%` }} /></div></div>)}</div>;
}

function ProjectStreamPage({ setActive }: { setActive: (p: PageKey) => void }) {
  const cards = [
    { type: 'Human turn', text: 'Should we test layered pricing with existing customers first, or start with new acquisition cohorts?', chips: ['S-431', 'M-213'], tone: 'slate' as PillTone },
    { type: 'Routed question', text: 'Possible authority gap: finance model and customer-success risk should be judged by different owners.', chips: ['D-102', 'M-213', 'R-09'], tone: 'violet' as PillTone },
    { type: 'Decision crystallization', text: 'Proposal: run an 8-week pilot on North Region A-segment accounts before full rollout.', chips: ['E-041', 'T-087'], tone: 'blue' as PillTone },
    { type: 'Memory proposal', text: 'Layered pricing policy should preserve legacy-customer protection period.', chips: ['M-213', 'S-431'], tone: 'amber' as PillTone },
    { type: 'Task transition', text: 'Create experiment plan, migration checklist, and customer comms draft.', chips: ['T-087', 'D-102'], tone: 'mint' as PillTone }
  ];
  return <>
    <PageHeader title="Project Stream" subtitle="The project-scoped work surface where discussion, routing, crystallization, and execution happen in one stream." right={<Pill tone="mint">New pricing strategy Q2 · active</Pill>} />
    <div className="stream-layout">
      <section className="stream-main panel">
        <div className="project-meta"><div className="avatar-stack"><span>HL</span><span>YW</span><span>MC</span><span>+6</span></div><Pill tone="blue">Project scope</Pill><Pill tone="slate">Q2 · Pricing · GTM</Pill></div>
        <div className="stream-timeline">
          {cards.map((card, idx) => <article key={card.type} className={`stream-card stream-${card.tone}`}>
            <div className="time">09:{18 + idx * 5}</div>
            <div className="stream-body"><div className="card-head"><Pill tone={card.tone}>{card.type}</Pill><span>GraphFlow Assistant</span></div><p>{card.text}</p><div className="chip-row">{card.chips.map(c => <EvidenceChip key={c} id={c} />)}<button className="ghost-button small" onClick={() => setActive(card.type.includes('Routed') ? 'transitions' : card.type.includes('Decision') ? 'node' : card.type.includes('Task') ? 'work' : 'review')}>Next step<ArrowRight size={14} /></button></div></div>
          </article>)}
        </div>
        <Composer placeholder="Write to the project stream, attach evidence, or turn this into a candidate..." />
      </section>
      <aside className="context-rail">
        <ContextBlock title="Active transitions" items={['T-042 pricing model review', 'T-087 experiment design', 'T-104 migration checklist']} />
        <ContextBlock title="Current scope" items={['Project: Pricing Q2', 'Visibility: project members', 'Referenced nodes: 12']} />
        <ContextBlock title="Related memory" items={['M-213 retention feedback', 'M-077 legacy policy', 'M-182 pilot design']} />
        <ContextBlock title="Suggested people" items={['Yue · Finance model', 'Ming · Customer success', 'Kai · Pricing system']} />
      </aside>
    </div>
  </>;
}

function ContextBlock({ title, items }: { title: string; items: string[] }) {
  return <div className="panel small-panel"><SectionTitle title={title} />{items.map(x => <div className="tiny-row" key={x}>{x}<ChevronRight size={14} /></div>)}</div>;
}

function Composer({ placeholder }: { placeholder: string }) {
  return <div className="composer"><input placeholder={placeholder} /><button><Send size={16} /></button></div>;
}

function MyAIStudioPage({ setActive }: { setActive: (p: PageKey) => void }) {
  const [teamPanel, setTeamPanel] = useState(false);
  return <>
    <PageHeader title="My AI Studio" subtitle="Private reasoning first. Explicitly submit only what should enter project stream or organizational graph." right={<Pill tone="violet"><Lock size={13} /> Private by default</Pill>} />
    <div className="myai-layout">
      <aside className="panel private-list">
        <SectionTitle title="Threads & drafts" />
        {['Q2 pricing challenge', 'Legacy customer risk', 'Experiment metrics', 'Route to Finance?'].map((t, i) => <button className={`private-thread ${i === 0 ? 'active' : ''}`} key={t}><strong>{t}</strong><span>{i === 0 ? 'open conversation' : 'private draft'}</span></button>)}
      </aside>
      <section className="panel ai-conversation">
        <div className="ai-header"><h2>Private AI conversation</h2><Pill tone="blue">Referenced project: Pricing Q2</Pill></div>
        <ChatBubble role="user" text="Challenge this idea before I post it: should we launch layered pricing in Q2? I want blind spots, routing needs, and possible evidence gaps." />
        <ChatBubble role="ai" text="Key tension points: retention risk, value boundary clarity, pricing-system feasibility, and ARPU uncertainty. This should not be posted as a conclusion yet." refs={['D-102', 'M-213', 'T-087', 'S-431']} />
        <div className="action-row compact"><button className="ghost-button">Save draft</button><button className="ghost-button" onClick={() => setActive('stream')}>Send to Project Stream</button><button className="ghost-button">Generate candidate</button><button className="primary-button" onClick={() => setTeamPanel(!teamPanel)}><Users size={15} />How would the team think?</button></div>
        {teamPanel && <div className="team-perspectives"><h3>Team perspectives</h3><div className="perspective-grid"><Perspective title="Finance" text="Need ARPU / churn sensitivity and cash-flow impact before approval." /><Perspective title="Customer success" text="Legacy customers may perceive downgrade unless protected by transition period." /><Perspective title="Engineering" text="Pricing tiers require entitlement and billing migration checks." /></div><div className="route-suggestion"><strong>Routing suggestion</strong><span>Finance judgement: Yue · Customer impact: Ming · System feasibility: Kai</span><button className="primary-button" onClick={() => setActive('transitions')}>Start route</button></div></div>}
        <ChatBubble role="ai" text="Generated reply draft: I suggest framing this as a staged pilot rather than a final policy. The draft can be saved privately, posted to stream, or converted into a decision candidate." />
        <Composer placeholder="Continue privately, ask AI to argue against you, or generate a candidate object..." />
      </section>
      <aside className="panel context-rail fixed">
        <SectionTitle title="Context & next actions" />
        <ContextBlock title="Referenced objects" items={['D-102 pricing discussion', 'M-213 retention memory', 'T-087 experiment task', 'S-431 stream thread']} />
        <ContextBlock title="Next actions" items={['Save as private draft', 'Send to Project Stream', 'Generate route suggestion']} />
        <div className="flow-mini"><span>private_ai_turn</span><ArrowRight size={13} /><span>personal_draft</span><ArrowRight size={13} /><span>proposal_candidate</span></div>
      </aside>
    </div>
  </>;
}

function Perspective({ title, text }: { title: string; text: string }) { return <div className="perspective"><strong>{title}</strong><span>{text}</span></div>; }
function ChatBubble({ role, text, refs = [] }: { role: 'user' | 'ai'; text: string; refs?: string[] }) {
  return <div className={`chat-bubble ${role}`}><div className="bubble-avatar">{role === 'ai' ? <Sparkles size={16} /> : 'HL'}</div><div><p>{text}</p>{refs.length > 0 && <div className="chip-row">{refs.map(r => <EvidenceChip key={r} id={r} />)}</div>}</div></div>;
}

function TransitionsPage({ setActive }: { setActive: (p: PageKey) => void }) {
  const rows = [
    ['discussion', 'decision_candidate', 'Q2 pricing strategy pilot', 'Hao', 'Yue', '7', 'Needs me'],
    ['private_ai_turn', 'route_suggestion', 'Finance model judgement', 'Hao', 'Yue', '4', 'Waiting'],
    ['draft_memory', 'review_pending_memory', 'Legacy customer pricing memory', 'Yue', 'Hao', '9', 'Awaiting Membrane'],
    ['personal_task_draft', 'plan_task_candidate', 'Build pilot metrics board', 'Hao', 'PMO', '3', 'Needs me'],
    ['decision_candidate', 'canonical_decision', 'Adopt 8-week experiment', 'Council', 'SAC', '12', 'Completed']
  ];
  return <>
    <PageHeader title="Transition Bench / Flow Inbox" subtitle="Organizational state-change control room. Not a todo list." />
    <div className="grid transition-grid">
      <Metric icon={<Inbox size={18} />} label="Needs me" value="12" tone="amber" />
      <Metric icon={<Clock3 size={18} />} label="Waiting on others" value="8" tone="violet" />
      <Metric icon={<ShieldCheck size={18} />} label="Awaiting Membrane" value="5" tone="blue" />
      <Metric icon={<CheckCircle2 size={18} />} label="Recently completed" value="36" tone="mint" />
      <div className="panel span-8"><SectionTitle title="Flow packets" /><table className="flow-table"><thead><tr><th>Source → Target</th><th>Title</th><th>Requester</th><th>Authority</th><th>Evidence</th><th>Status</th><th>Next</th></tr></thead><tbody>{rows.map(r => <tr key={r[2]} onClick={() => r[6] === 'Awaiting Membrane' ? setActive('review') : setActive('node')}><td><code>{r[0]} → {r[1]}</code></td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td><td>{r[5]}</td><td><Pill tone={r[6] === 'Completed' ? 'mint' : r[6] === 'Waiting' ? 'violet' : r[6] === 'Awaiting Membrane' ? 'blue' : 'amber'}>{r[6]}</Pill></td><td><ChevronRight size={15} /></td></tr>)}</tbody></table></div>
      <div className="panel span-4"><SectionTitle title="Selected packet" /><ObjectContract /><button className="primary-button full" onClick={() => setActive('review')}>Enter Review Bench</button></div>
    </div>
  </>;
}

function ObjectContract() { return <div className="contract-list">{['What changes: draft_memory → review_pending_memory','Who judges: Hao Lin','Evidence refs: 9','Visibility: project scope','Next: membrane review'].map(x => <div key={x}>{x}</div>)}</div>; }

function ReviewPage({ setActive }: { setActive: (p: PageKey) => void }) {
  return <>
    <PageHeader title="Membrane Review Bench" subtitle="Trust boundary: decide what may enter accepted organizational reality." />
    <div className="review-layout">
      <section className="panel review-queue"><div className="metric-row"><Metric icon={<ShieldCheck size={18}/>} label="Pending" value="24" tone="blue"/><Metric icon={<Zap size={18}/>} label="High impact" value="7" tone="amber"/><Metric icon={<Activity size={18}/>} label="Conflict warnings" value="9" tone="red"/></div><SectionTitle title="Candidates" />{['Q2 pricing policy decision','Legacy customer protection memory','Pricing-system entitlement task','Invite finance owner to route'].map((x,i)=><div className={`candidate ${i===0?'selected':''}`} key={x}><strong>{x}</strong><span>review_pending · evidence {6+i}</span><div><Pill tone={i===0?'red':'amber'}>{i===0?'conflict':'proposal'}</Pill><Pill tone="blue">authority required</Pill></div></div>)}</section>
      <aside className="panel review-detail"><SectionTitle title="Candidate detail" /><h2>Q2 pricing policy decision</h2><p>Adopt an 8-week pilot with legacy-customer protection. High impact because it changes accepted pricing scope.</p><ContextBlock title="Warnings" items={['Conflict with 2024 pricing memory', 'Duplicate candidate from Pricing Room', 'High downstream impact']} /><ContextBlock title="Authority required" items={['Strategy council ≥ 2/3', 'Finance owner confirmation', 'Product owner accountable']} /><div className="review-actions"><button onClick={()=>setActive('node')} className="primary-button">Accept</button><button className="ghost-button danger">Reject</button><button className="ghost-button">Request clarification</button><button className="ghost-button">Counter / revise</button></div></aside>
    </div>
  </>;
}

function MemoryPage({ setActive }: { setActive: (p: PageKey) => void }) {
  const memories = ['Layered pricing review workflow v1.1','Legacy customer protection policy','World model definition and boundary','Old onboarding workflow v0.9','Capability routing principle'];
  return <>
    <PageHeader title="World Memory" subtitle="What the team currently accepts as true, organized by epistemic status rather than folders." />
    <div className="memory-layout"><section className="panel memory-main"><div className="status-tabs"><Pill tone="mint">Canonical 128</Pill><Pill tone="slate">Draft 31</Pill><Pill tone="amber">Review pending 18</Pill><Pill tone="violet">Contested 7</Pill><Pill tone="slate">Superseded 56</Pill></div><table className="flow-table"><thead><tr><th>Memory</th><th>Scope</th><th>Status</th><th>Accepted by</th><th>Evidence</th><th>Citations</th></tr></thead><tbody>{memories.map((m,i)=><tr key={m} onClick={()=>setActive('node')}><td>{m}</td><td>{i<2?'Product Q2':'Global'}</td><td><Pill tone={i===3?'slate':i===2?'amber':'mint'}>{i===3?'Superseded':i===2?'Review pending':'Canonical'}</Pill></td><td>{i===2?'Review committee':'SAC'}</td><td>E-{100+i}, E-{140+i}</td><td>{17-i}</td></tr>)}</tbody></table></section><aside className="panel memory-detail"><SectionTitle title="Selected memory" /><h2>Layered pricing review workflow v1.1</h2><p>Defines how pricing proposals move from private reasoning to project stream, route suggestion, membrane review, and canonical decision.</p><ObjectContract /><ContextBlock title="Lineage" items={['Supersedes workflow v1.0','Cited by D-102 and D-114','Linked tasks T-087, T-109']} /></aside></div>
  </>;
}

function GraphPage({ setActive }: { setActive: (p: PageKey) => void }) {
  return <>
    <PageHeader title="Responsibility Graph" subtitle="Routing evidence and authority topology: who can judge what, and why?" />
    <div className="graph-layout"><section className="panel graph-canvas"><div className="graph-filter"><Pill tone="blue">Domain: Product & Pricing</Pill><Pill tone="slate">Scope: Q2 budget ≤ $200k</Pill><Pill tone="mint">Confidence ≥ 0.7</Pill></div><div className="network-stage"><GraphNode x={47} y={48} label="Needs judgement" main /><GraphNode x={20} y={28} label="Yue · Finance" /><GraphNode x={72} y={28} label="Ming · CS" /><GraphNode x={25} y={72} label="Kai · Engineering" /><GraphNode x={70} y={72} label="Hao · Product" /><svg className="graph-lines" viewBox="0 0 100 100"><line x1="47" y1="48" x2="20" y2="28"/><line x1="47" y1="48" x2="72" y2="28"/><line x1="47" y1="48" x2="25" y2="72"/><line x1="47" y1="48" x2="70" y2="72"/></svg></div></section><aside className="panel graph-detail"><SectionTitle title="Selected capability" /><h2>Pricing judgement</h2><Pill tone="mint">Validated</Pill><ObjectContract /><ContextBlock title="Recommended routes" items={['Yue · Finance · 0.86','Ming · Customer impact · 0.79','Kai · System feasibility · 0.68']} /><button className="primary-button full" onClick={()=>setActive('transitions')}>Create route</button></aside></div>
  </>;
}
function GraphNode({ x, y, label, main=false }: {x:number;y:number;label:string;main?:boolean}) { return <button className={`graph-node ${main?'main':''}`} style={{left:`${x}%`, top:`${y}%`}}>{label}</button>; }

function WorkPage({ setActive }: { setActive: (p: PageKey) => void }) {
  return <>
    <PageHeader title="Work Graph / Plan Surface" subtitle="Tasks are governed execution-state transitions, not generic todos." />
    <div className="grid transition-grid"><Metric icon={<FileText size={18}/>} label="Draft" value="24" tone="slate"/><Metric icon={<GitBranch size={18}/>} label="Candidate" value="16" tone="amber"/><Metric icon={<CheckCircle2 size={18}/>} label="Canonical" value="9" tone="mint"/><Metric icon={<Archive size={18}/>} label="Blocked" value="6" tone="red"/><div className="panel span-8"><SectionTitle title="Task transition objects" /><CompactRows rows={[
      ['personal_task_draft → plan_task_candidate → plan_task_canonical', 'Build pricing pilot metrics board · evidence 5 · D-102 · R-09', 'needs'],
      ['plan_task_candidate → plan_task_canonical', 'Prepare customer communication FAQ · evidence 3 · M-213', 'waiting'],
      ['plan_task_canonical → done', 'Update entitlement matrix · linked to T-087', 'ok']
    ]} /><div className="dependency-map"><span>D-102</span><ArrowRight/><strong>Pricing pilot metrics</strong><ArrowRight/><span>R-09</span></div></div><div className="panel span-4"><SectionTitle title="Selected task" /><ObjectContract /><ContextBlock title="Blockers & risks" items={['R-09 churn sensitivity unclear','D-102 decision not accepted','M-213 legacy feedback']} /><button onClick={()=>setActive('review')} className="primary-button full">Promote to plan</button></div></div>
  </>;
}

function NodePage({ setActive }: { setActive: (p: PageKey) => void }) {
  return <>
    <PageHeader title="Universal Node Detail / Proof Page" subtitle="The trust explanation page for any graph object." right={<Pill tone="mint">Decision · Active</Pill>} />
    <div className="node-layout"><section className="panel proof-main"><h2>Adopt GraphFlow as strategic graph engine</h2><div className="proof-strip"><Pill tone="blue">D-2025-0519-001</Pill><Pill tone="mint">Active</Pill><Pill tone="slate">Company scope</Pill><Pill tone="violet">proposed → active</Pill></div><div className="proof-grid"><ProofCard title="Evidence references" items={['AI governance whitepaper 2025','Q2 council discussion memo','GraphFlow security review']} /><ProofCard title="Authority / accepted by" items={['Decision owner: Hao Lin','Accepted by: Strategy Architecture Council','Effective: 2025-05-21']} /><ProofCard title="Review method" items={['Formal decision review v2.0','4 approve / 0 reject / 3 neutral','Review conclusion: accepted']} /><ProofCard title="Mutation service" items={['Decision Service v1.6','Action: proposed → active','Triggered by SAC approval']} /><ProofCard title="Lineage" items={['Supersedes internal DIY plan v1.0','No newer version yet','3 version history entries']} /><ProofCard title="Downstream affected" items={['12 work graph tasks','5 world memory objects','2 active transitions']} /></div></section><aside className="panel trust-rail"><SectionTitle title="Trust Contract" /><ObjectContract /><button onClick={()=>setActive('graph')} className="ghost-button full">Open authority graph</button><button onClick={()=>setActive('stream')} className="ghost-button full">Open source stream</button></aside></div>
  </>;
}
function ProofCard({ title, items }: {title:string;items:string[]}) { return <div className="proof-card"><h3>{title}</h3>{items.map(i=><div key={i} className="tiny-row">{i}</div>)}</div>; }

function PlaceholderPage({ title }: { title: string }) { return <><PageHeader title={title} subtitle="Support page placeholder for rendered docs, admin, permissions, and integration settings." /><div className="panel placeholder"><Layers3 size={32}/><p>This prototype focuses on the nine core graph-native surfaces. This support page is intentionally minimal.</p></div></>; }

function App() {
  const [active, setActive] = useState<PageKey>('home');
  const page = useMemo(() => {
    switch(active) {
      case 'home': return <HomePage setActive={setActive} />;
      case 'stream': return <ProjectStreamPage setActive={setActive} />;
      case 'my-ai': return <MyAIStudioPage setActive={setActive} />;
      case 'transitions': return <TransitionsPage setActive={setActive} />;
      case 'review': return <ReviewPage setActive={setActive} />;
      case 'memory': return <MemoryPage setActive={setActive} />;
      case 'graph': return <GraphPage setActive={setActive} />;
      case 'work': return <WorkPage setActive={setActive} />;
      case 'node': return <NodePage setActive={setActive} />;
      case 'docs': return <PlaceholderPage title="Rendered Docs" />;
      case 'settings': return <PlaceholderPage title="Settings / Admin" />;
      default: return null;
    }
  }, [active]);
  return <AppShell active={active} setActive={setActive}>{page}</AppShell>;
}

createRoot(document.getElementById('root')!).render(<App />);
