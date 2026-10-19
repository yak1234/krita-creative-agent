// @ts-check
// Ends a Pi run after a completed turn. Pi asks the agent's finishTurn hook, which runs once the
// turn's assistant message and tool results are final but before the turn's `turn_end` event.
// Turn counters here count `turn_end` events, so when the hook runs they have not counted this
// turn yet: `shouldStop` receives the number of turns finished including this one. Error and
// aborted turns end the run by themselves; the hook leaves them alone.

/**
 * @param {import('@earendil-works/pi-coding-agent').AgentSession['agent']} agent
 * @param {() => number} counted turns already counted on `turn_end`
 * @param {(turnsDone: number) => boolean} shouldStop
 */
export function stopAfterTurn(agent, counted, shouldStop) {
  agent.finishTurn = turn => {
    if (turn.message.stopReason === 'error' || turn.message.stopReason === 'aborted') return;
    return shouldStop((counted() || 0) + 1) ? /** @type {const} */ ({ action: 'end' }) : undefined;
  };
}
