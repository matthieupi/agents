# Pi local extension bundle

Auto-loaded daily-driver extensions live in `~/.pi/agent/extensions/`:
- `cross-agent.ts`
- `session-replay.ts`
- `startup-table.ts`
- `subagent-widget.ts`
- `system-select.ts`
- `theme-cycler.ts`
- `tool-counter.ts`
- `vim-chat-editor.ts`

Manual/on-demand extensions live in this directory:
- `tool-counter-widget.ts`
- `subagent-widget.ts`
- `agent-team.ts`
- `agent-chain.ts`
- `pi-pi.ts`

Preferred host-wrapper launches from this repo:
```bash
./pi ext-agent-team
./pi ext-agent-chain
./pi ext-pi-pi
./pi ext-agent-team --login
```

Those wrapper presets rebuild the explicit daily-driver stack with `--no-extensions`, prepend `agent-team.ts`, `agent-chain.ts`, or `pi-pi.ts`, and avoid duplicate loading of the auto-discovered defaults.
