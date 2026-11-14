// Step scanning per LAYOUT.md. Pure functions, no timers: state only changes on next() or select().
//
// null           no highlight (start, or after any tap)
// item === null  group level: the whole group is highlighted
// item < size    item level: one item is highlighted
// item === size  back-out: the whole group again; select() leaves without choosing

export type ScanState = { group: number; item: number | null } | null

export function next(state: ScanState, sizes: number[]): ScanState {
  if (!state) return { group: 0, item: null }
  if (state.item === null) return { group: (state.group + 1) % sizes.length, item: null }
  return { group: state.group, item: (state.item + 1) % (sizes[state.group] + 1) }
}

export function select(
  state: ScanState,
  sizes: number[],
): { state: ScanState; activate: [group: number, item: number] | null } {
  if (!state) return { state: { group: 0, item: null }, activate: null }
  if (state.item === null) return { state: { group: state.group, item: 0 }, activate: null }
  const groupLevel = { group: state.group, item: null }
  if (state.item === sizes[state.group]) return { state: groupLevel, activate: null }
  // After a choice, stay on the same group so the next word nearby takes fewer presses.
  return { state: groupLevel, activate: [state.group, state.item] }
}
