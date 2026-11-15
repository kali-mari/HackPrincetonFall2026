import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent } from 'react'
import { BASE_WORDS, CONTEXTS, DEFAULTS, SESSIONS, snapshot, type Context } from './data/engineDemo'
import styles from './EngineDemo.module.css'

type Point = { x: number; y: number }
type Panel = { kind: 'conversation'; index: number } | { kind: 'detail'; title: string; body: string }
const CENTER = { x: 740, y: 330 }
const HUBS = {
  words: { x: 430, y: 265 }, profile: { x: 1040, y: 150 },
  conversations: { x: 280, y: 650 }, suggestions: { x: 1030, y: 430 },
}
const WORDS = [...BASE_WORDS, ...SESSIONS.flatMap((session) => session.words)]
const WORD_POSITIONS = WORDS.map((_, i) => ({ x: 85 + (i % 6) * 108, y: 55 + Math.floor(i / 6) * 72 }))
const FACT_POSITIONS = [
  { x: 900, y: 50 }, { x: 1120, y: 40 }, { x: 1310, y: 75 },
  { x: 1360, y: 170 }, { x: 1260, y: 260 }, { x: 990, y: 285 },
]
const CONVERSATION_POSITIONS = SESSIONS.map((_, i) => ({ x: 75 + (i % 2) * 165, y: 340 + Math.floor(i / 2) * 112 }))
const SUGGESTION_POSITIONS = Array.from({ length: 6 }, (_, i) => ({ x: 1160 + (i % 2) * 220, y: 370 + Math.floor(i / 2) * 130 }))

function Edge({ from, to, fresh = false }: { from: Point; to: Point; fresh?: boolean }) {
  return <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} className={fresh ? styles.newEdge : styles.edge} />
}

function GraphNode({ id, at, label, caption, kind, fresh = false, selected = false, onSelect }: {
  id: string; at: Point; label: string; caption?: string; kind: string; fresh?: boolean; selected?: boolean; onSelect?: () => void
}) {
  return <g transform={`translate(${at.x} ${at.y})`} className={styles.node} data-node={id} data-kind={kind} data-new={fresh} data-selected={selected}
    role={onSelect ? 'button' : 'group'} tabIndex={0}
    aria-label={[label, caption, fresh ? 'New this conversation' : ''].filter(Boolean).join('. ')}
    onClick={onSelect} onKeyDown={onSelect ? (event) => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect() }
    } : undefined}>
    {onSelect && <rect x="-52" y="-26" width="104" height="65" fill="transparent" />}
    <circle className={styles.halo} r="21" />
    <circle className={styles.dot} r={kind === 'hub' ? 16 : 7} />
    <text y={kind === 'hub' ? 39 : 25} textAnchor="middle" className={styles.nodeLabel}>{label}</text>
    {caption && <text y={kind === 'hub' ? 57 : 43} textAnchor="middle" className={styles.nodeCaption}>{caption}</text>}
    {fresh && <circle cx="13" cy="-12" r="3" className={styles.newDot} />}
  </g>
}

export default function EngineDemo() {
  const [step, setStep] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [context, setContext] = useState<Context>('breakfast')
  const [panel, setPanel] = useState<Panel | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const panelTrigger = useRef<Element | null>(null)
  const swipe = useRef<{ pointerId: number; startX: number } | null>(null)
  const [swipeOffset, setSwipeOffset] = useState(0)
  const svgRef = useRef<SVGSVGElement>(null)
  const worldRef = useRef<SVGGElement>(null)
  const [view, setView] = useState({ x: 0, y: 0, scale: 1 })
  const [positions, setPositions] = useState<Record<string, Point>>({})
  const [dragging, setDragging] = useState(false)
  const drag = useRef<{
    pointerId: number; node: string | null; start: Point; position: Point;
    view: typeof view; moved: boolean
  } | null>(null)
  const suppressClick = useRef(false)
  const at = (id: string, initial: Point) => positions[id] ?? initial
  const center = at('alex', CENTER)
  const hubs = {
    words: at('hub:words', HUBS.words), profile: at('hub:profile', HUBS.profile),
    conversations: at('hub:conversations', HUBS.conversations), suggestions: at('hub:suggestions', HUBS.suggestions),
  }
  const wordAt = (word: string) => at(`word:${word}`, WORD_POSITIONS[WORDS.indexOf(word)])
  const factAt = (i: number) => at(`fact:${i}`, FACT_POSITIONS[i])
  const conversationAt = (i: number) => at(`conversation:${i}`, CONVERSATION_POSITIONS[i])
  const suggestionAt = (i: number) => at(`suggestion:${i}`, SUGGESTION_POSITIONS[i])
  const state = snapshot(step, context)
  const previous = snapshot(Math.max(0, step - 1), context)
  const session = step ? SESSIONS[step - 1] : null

  useEffect(() => {
    if (!playing) return
    const timer = window.setTimeout(() => {
      const next = Math.min(SESSIONS.length, step + 1)
      setStep(next)
      setPanel((current) => current?.kind === 'conversation' ? { kind: 'conversation', index: next - 1 } : current)
      if (next === SESSIONS.length) setPlaying(false)
    }, 4500)
    return () => window.clearTimeout(timer)
  }, [playing, step])

  function openPanel(value: Panel) {
    panelTrigger.current = document.activeElement
    setPlaying(false)
    setSwipeOffset(0)
    setPanel(value)
  }

  function closePanel() {
    setPanel(null)
    setSwipeOffset(0)
    const trigger = panelTrigger.current
    if (trigger?.isConnected && (trigger instanceof HTMLElement || trigger instanceof SVGElement)) trigger.focus()
    else svgRef.current?.focus()
  }

  useEffect(() => {
    if (!panel) return
    const focusFrame = window.requestAnimationFrame(() => closeButtonRef.current?.focus())
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); closePanel() }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      window.removeEventListener('keydown', onKey)
    }
  }, [panel])

  function swipeStart(event: ReactPointerEvent<HTMLElement>) {
    if (event.button !== 0 || (event.target as Element).closest('button')) return
    swipe.current = { pointerId: event.pointerId, startX: event.clientX }
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function swipeMove(event: ReactPointerEvent<HTMLElement>) {
    if (swipe.current?.pointerId === event.pointerId) setSwipeOffset(Math.max(0, event.clientX - swipe.current.startX))
  }

  function swipeEnd(event: ReactPointerEvent<HTMLElement>) {
    if (swipe.current?.pointerId !== event.pointerId) return
    const distance = event.clientX - swipe.current.startX
    swipe.current = null
    if (event.type !== 'pointercancel' && distance > 80) closePanel()
    else setSwipeOffset(0)
  }

  function svgPoint(clientX: number, clientY: number) {
    const matrix = svgRef.current?.getScreenCTM()
    if (!matrix) return { x: 0, y: 0 }
    return new DOMPoint(clientX, clientY).matrixTransform(matrix.inverse())
  }

  function zoom(factor: number, anchor = { x: 750, y: 380 }) {
    setView((old) => {
      const scale = Math.max(0.35, Math.min(5, old.scale * factor))
      const ratio = scale / old.scale
      return { x: anchor.x - (anchor.x - old.x) * ratio, y: anchor.y - (anchor.y - old.y) * ratio, scale }
    })
  }

  // A non-passive listener keeps wheel/trackpad zoom inside the graph, including Ctrl+pinch.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    function onWheel(event: WheelEvent) {
      event.preventDefault()
      const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 760 : 1)
      zoom(Math.exp(-Math.max(-100, Math.min(100, delta)) * 0.004), svgPoint(event.clientX, event.clientY))
    }
    svg.addEventListener('wheel', onWheel, { passive: false })
    return () => svg.removeEventListener('wheel', onWheel)
  }, [])

  function pointerDown(event: ReactPointerEvent<SVGSVGElement>) {
    if (event.button !== 0 || drag.current) return
    const target = (event.target as Element).closest<SVGGElement>('[data-node]')
    const node = target?.dataset.node ?? null
    const transform = target?.transform.baseVal.consolidate()?.matrix
    drag.current = {
      pointerId: event.pointerId, node, start: svgPoint(event.clientX, event.clientY),
      position: { x: transform?.e ?? 0, y: transform?.f ?? 0 }, view, moved: false,
    }
    suppressClick.current = false
    const captureTarget = target ?? event.currentTarget
    captureTarget.setPointerCapture(event.pointerId)
    if (target) target.focus()
    else event.currentTarget.focus()
  }

  function pointerMove(event: ReactPointerEvent<SVGSVGElement>) {
    const active = drag.current
    if (!active || active.pointerId !== event.pointerId) return
    const current = svgPoint(event.clientX, event.clientY)
    const dx = current.x - active.start.x, dy = current.y - active.start.y
    if (!active.moved && Math.hypot(dx, dy) < 4) return
    active.moved = true
    suppressClick.current = true
    setDragging(true)
    if (active.node) {
      const id = active.node
      setPositions((old) => ({ ...old, [id]: { x: active.position.x + dx / active.view.scale, y: active.position.y + dy / active.view.scale } }))
    } else setView({ ...active.view, x: active.view.x + dx, y: active.view.y + dy })
  }

  function pointerUp(event: ReactPointerEvent<SVGSVGElement>) {
    if (drag.current?.pointerId !== event.pointerId) return
    drag.current = null
    setDragging(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  function fitGraph() {
    const bounds = worldRef.current?.getBBox()
    if (!bounds) return
    const scale = Math.min(1.5, 1420 / Math.max(1, bounds.width), 680 / Math.max(1, bounds.height))
    setView({ scale, x: 750 - (bounds.x + bounds.width / 2) * scale, y: 380 - (bounds.y + bounds.height / 2) * scale })
  }

  function graphKey(event: ReactKeyboardEvent<SVGSVGElement>) {
    const arrows: Record<string, Point> = { ArrowLeft: { x: -1, y: 0 }, ArrowRight: { x: 1, y: 0 }, ArrowUp: { x: 0, y: -1 }, ArrowDown: { x: 0, y: 1 } }
    const direction = arrows[event.key]
    if (direction) {
      event.preventDefault()
      const target = (event.target as Element).closest<SVGGElement>('[data-node]')
      const id = target?.dataset.node
      const amount = event.shiftKey ? 40 : 12
      if (id && target) {
        const matrix = target.transform.baseVal.consolidate()!.matrix
        setPositions((old) => ({ ...old, [id]: { x: matrix.e + direction.x * amount, y: matrix.f + direction.y * amount } }))
      } else setView((old) => ({ ...old, x: old.x + direction.x * amount, y: old.y + direction.y * amount }))
    } else if (event.key === '+' || event.key === '=') { event.preventDefault(); zoom(1.2) }
    else if (event.key === '-') { event.preventDefault(); zoom(1 / 1.2) }
    else if (event.key === '0') { event.preventDefault(); fitGraph() }
  }

  function go(value: number) {
    setStep(value)
    openPanel({ kind: 'conversation', index: value - 1 })
  }

  const panelSession = panel?.kind === 'conversation' && panel.index >= 0 ? SESSIONS[panel.index] : null
  const panelTitle = panel?.kind === 'detail' ? panel.title : panelSession?.title ?? 'Start with the essentials'
  const inspect = (title: string, body: string) => openPanel({ kind: 'detail', title, body })

  return <main className={styles.page}>
    <header className={styles.header}>
      <div><a href="#/profiles">← Profiles</a><h1>Engine at work<span>Alex’s growing world</span></h1></div>
      <div className={styles.stats} aria-live="polite" aria-atomic="true">
        <span><strong>{step}<small> / 5</small></strong>conversations</span>
        <span><strong>{state.vocabulary.length}<small> +{state.vocabulary.length - BASE_WORDS.length}</small></strong>personal words</span>
        <span><strong>{state.facts.length}</strong>profile details</span>
        <span><strong>{state.speech.length}</strong>spoken choices</span>
      </div>
      <label className={styles.context}>Suggestion context<select value={context} onChange={(event) => { setContext(event.target.value as Context); setPanel(null) }}>
        {CONTEXTS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
      </select></label>
    </header>

    <section className={styles.canvas} aria-label="Personalization knowledge graph">
      <div className={styles.graphHeading}><span>PERSONAL KNOWLEDGE GRAPH</span><span className={styles.legend}><i />Vocabulary <i />Profile <i />Conversations <i />Suggestions <b />New this step</span></div>
      <div className={styles.graphViewport}>
      <div className={styles.graphTools} role="group" aria-label="Graph controls">
        <button onClick={() => zoom(1.25)} aria-label="Zoom in">+</button>
        <span aria-live="polite">{Math.round(view.scale * 100)}%</span>
        <button onClick={() => zoom(0.8)} aria-label="Zoom out">−</button>
        <button onClick={fitGraph}>Fit graph</button>
        <button onClick={() => { setPositions({}); setView({ x: 0, y: 0, scale: 1 }) }}>Reset layout</button>
      </div>
      <svg ref={svgRef} viewBox="0 0 1500 760" className={styles.graph} data-dragging={dragging} role="group" tabIndex={0}
        onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={pointerUp}
        onLostPointerCapture={() => { drag.current = null; setDragging(false) }}
        onKeyDown={graphKey} onClickCapture={(event) => { if (suppressClick.current && event.detail !== 0) { event.preventDefault(); event.stopPropagation() } }} aria-label={`Alex after ${step} conversations: ${state.vocabulary.length} words, ${state.facts.length} approved profile details, six suggestions.`}>
        <desc>Drag nodes to rearrange, drag background to pan, and scroll to zoom. Keyboard: arrow keys move a focused node or pan the background, plus and minus zoom, and zero fits the graph. Enter inspects a node. Six suggestions appear on the right.</desc>
        <g ref={worldRef} transform={`translate(${view.x} ${view.y}) scale(${view.scale})`}>
        <g aria-hidden="true">
          {Object.values(hubs).map((hub, i) => <Edge key={i} from={center} to={hub} />)}
          {state.vocabulary.map((word) => <Edge key={word} from={hubs.words} to={wordAt(word)} fresh={!previous.vocabulary.includes(word)} />)}
          {state.facts.map((fact, i) => <Edge key={fact.group + fact.value} from={hubs.profile} to={factAt(i)} fresh={i >= previous.facts.length} />)}
          {SESSIONS.slice(0, step).map((_, i) => <Edge key={i} from={hubs.conversations} to={conversationAt(i)} fresh={i === step - 1} />)}
          {state.suggestions.map((item, i) => <Edge key={item.text} from={item.source === 'Profile' ? hubs.profile : item.source === 'History' ? hubs.conversations : hubs.suggestions} to={suggestionAt(i)} fresh={item.text !== previous.suggestions[i]?.text} />)}
          {session?.words.map((word) => <Edge key={word} from={conversationAt(step - 1)} to={wordAt(word)} fresh />)}
        </g>
        <g transform={`translate(${center.x} ${center.y})`} className={styles.center} data-node="alex" tabIndex={0} role="button" aria-label="Alex, draggable demo profile"
          onClick={() => inspect('Alex’s profile', `${state.vocabulary.length} personal words, ${state.facts.length} caregiver-approved details, and ${state.speech.length} confirmed spoken choices across ${step} conversations.`)}
          onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); inspect('Alex’s profile', `${state.vocabulary.length} personal words · ${state.facts.length} caregiver-approved details · ${state.speech.length} spoken choices`) } }}>
          <circle r="57" /><circle r="46" /><text y="-4" textAnchor="middle">Alex</text><text y="18" textAnchor="middle">DEMO PROFILE</text>
        </g>
        <GraphNode id="hub:words" at={hubs.words} label="Word bank" caption={`${state.vocabulary.length} words · ${BASE_WORDS.length} core + caregiver additions`} kind="hub" onSelect={() => inspect('Word bank', `Core words: ${BASE_WORDS.join(', ')}. Caregiver additions: ${state.vocabulary.filter((word) => !BASE_WORDS.includes(word)).join(', ') || 'None yet'}.`)} />
        <GraphNode id="hub:profile" at={hubs.profile} label="User profile" caption={`${state.facts.length} caregiver-approved details`} kind="hub" onSelect={() => inspect('User profile', state.facts.map((fact) => `${fact.group}: ${fact.value}`).join(' · ') || 'No profile facts yet. Personal details appear when the caregiver adds them.')} />
        <GraphNode id="hub:conversations" at={hubs.conversations} label="Conversations" caption={`${state.speech.length} confirmed spoken choices`} kind="hub" onSelect={() => openPanel({ kind: 'conversation', index: step - 1 })} />
        <GraphNode id="hub:suggestions" at={hubs.suggestions} label="Suggestions" caption="Six choices · never auto-spoken" kind="hub" onSelect={() => inspect('How suggestions are chosen', 'Up to two relevant caregiver-approved favorites, then confirmed speech in this activity, broader speech history, and starter phrases. This seeded demo simplifies ranking; the live predictor also uses time buckets and recency decay. Suggestions never select or speak automatically.')} />
        {state.vocabulary.map((word) => <GraphNode key={word} id={`word:${word}`} at={wordAt(word)} label={word} kind="word"
          fresh={!previous.vocabulary.includes(word)} onSelect={() => inspect(word, BASE_WORDS.includes(word) ? `${word} · Core vocabulary, available from the start.` : `${word} · Added by the caregiver after conversation ${SESSIONS.findIndex((item) => item.words.includes(word)) + 1}.`)} />)}
        {state.facts.map((fact, i) => <GraphNode key={fact.group + fact.value} id={`fact:${i}`} at={factAt(i)} label={fact.value} caption={fact.group} kind="fact" fresh={i >= previous.facts.length}
          onSelect={() => inspect(fact.value, `${fact.group}: ${fact.value} · Caregiver approved. Relevant to ${fact.context} suggestions.`)} />)}
        {SESSIONS.slice(0, step).map((item, i) => <GraphNode key={item.title} id={`conversation:${i}`} at={conversationAt(i)} label={item.title} caption={item.time} kind="conversation" selected={panel?.kind === 'conversation' && panel.index === i} fresh={i === step - 1}
          onSelect={() => openPanel({ kind: 'conversation', index: i })} />)}
        {state.suggestions.map((item, i) => <GraphNode key={item.text} id={`suggestion:${i}`} at={suggestionAt(i)} label={`${i + 1}. ${item.text}`} caption={item.source === 'History' ? item.reason : item.source === 'Profile' ? 'Caregiver-approved favorite' : 'Starter phrase'}
          kind="suggestion" fresh={item.text !== previous.suggestions[i]?.text}
          onSelect={() => inspect(item.text, `${item.text} · ${item.reason}. Initially in slot ${i + 1}: “${DEFAULTS[i]}”.`)} />)}
        <text x="1100" y="735" className={styles.baseline} textAnchor="middle">Before: water · more · hungry · all done · help · thanks</text>
        </g>
      </svg>
      <aside className={styles.detailPanel} data-open={Boolean(panel)} aria-hidden={!panel} inert={!panel}
        aria-labelledby="engine-detail-title" style={swipeOffset ? { transform: `translateX(${swipeOffset}px)`, transition: 'none' } : undefined}>
        <header className={styles.panelHeader} onPointerDown={swipeStart} onPointerMove={swipeMove}
          onPointerUp={swipeEnd} onPointerCancel={swipeEnd} onLostPointerCapture={() => { swipe.current = null; setSwipeOffset(0) }}>
          <span className={styles.panelGrip} aria-hidden="true">⋮⋮</span><span>DETAILS <small>Drag right to dismiss</small></span>
          <button ref={closeButtonRef} onClick={closePanel} aria-label="Close details">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M4 12h12m-5-5 5 5-5 5M20 4v16" />
            </svg>
          </button>
        </header>
        <div className={styles.panelBody}>
          <p className={styles.panelEyebrow}>{panel?.kind === 'detail' ? 'KNOWLEDGE GRAPH' : panel?.kind === 'conversation' && panelSession ? `CONVERSATION ${panel.index + 1} · ${panelSession.time}` : 'BEFORE THE FIRST CONVERSATION'}</p>
          <h2 id="engine-detail-title">{panelTitle}</h2>
          {panel?.kind === 'detail' ? <p>{panel.body}</p> : panelSession ? <>
            <section><h3>Caregiver asks</h3><blockquote>{panelSession.prompt}</blockquote></section>
            <section><h3>Alex selects and speaks</h3><ul>{panelSession.replies.map((reply, i) => <li key={i}>“{reply.text}”</li>)}</ul></section>
            <section><h3>Caregiver adds to word bank</h3><div className={styles.panelWords}>{panelSession.words.map((word) => <span key={word}>{word}</span>)}</div></section>
            <section><h3>Approved profile details</h3><ul>{panelSession.facts.map((fact) => <li key={fact.group + fact.value}><strong>{fact.group}:</strong> {fact.value}</li>)}</ul></section>
          </> : <><p>Six core words. No history or profile facts yet.</p><p>Play the replay to watch connections appear. Click any node to see where it came from, or change context to explore different suggestions.</p></>}
          <p className={styles.panelNote}>Fictional seeded data. Profile details require caregiver approval; the live app does not automatically save overheard conversation as facts.</p>
        </div>
      </aside>
      </div>
      <div className={styles.inspector} role="status">Drag nodes to arrange · Drag background to pan · Scroll to zoom · Click a node for details · Escape closes the panel.</div>
    </section>

    <footer className={styles.footer}>
      <div className={styles.controls}>
        <button onClick={() => go(0)} aria-label="Reset replay">↺</button>
        <button onClick={() => go(Math.max(0, step - 1))} disabled={step === 0} aria-label="Previous conversation">←</button>
        <button className={styles.play} onClick={() => { if (step === SESSIONS.length) { setStep(0); setPanel(null) } setPlaying(!playing) }}>{playing ? 'Ⅱ Pause' : '▶ Play'}</button>
        <button onClick={() => go(Math.min(SESSIONS.length, step + 1))} disabled={step === SESSIONS.length} aria-label="Next conversation">→</button>
      </div>
      <div className={styles.timeline} aria-label="Replay step">{['Start', ...SESSIONS.map((_, i) => `Conversation ${i + 1}`)].map((label, i) => <button key={label} onClick={() => go(i)} aria-current={i === step ? 'step' : undefined}><span>{i === 0 ? '○' : i}</span>{label}</button>)}</div>
      <p className={styles.disclaimer}><strong>SEEDED SIMULATION</strong>Fictional data · no profile writes. Simplified ranking; live ranking also uses time and recency. Facts require caregiver approval.</p>
    </footer>
  </main>
}
