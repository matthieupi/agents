// OpenCode V2 2.0.32: promise/tool.ts, promise/session.ts;
// core/tool.ts consumes event.input AFTER execute.before (before validation).
// Keep the native executor, permission checks, depth limit and notifications.
const POLICY = `OpenCode V2 native subagent policy (overrides portable harness delegation examples):
Use the native subagent tool for both read-only and write-capable agents; background execution is the default. Supply agent, description and prompt; use sessionID only to continue a child conversation. Explicit background:false is allowed when foreground execution is needed.
Do not use legacy KDCO delegate/delegation_read routing or split tools by read/write capability. Respect native permissions, agent availability and subagent depth limits; background mode grants no additional authority. Give writers non-overlapping ownership.
Consume automatic completion notifications, inspect results, and launch work as its actual dependencies become ready; do not impose a global wave barrier. Never sleep, poll, request progress, or duplicate active subagent work. Continue independent work; if none is ready, briefly report what is running and end the response so notifications can resume the session.`;

export default {
  id: "background-subagents",
  async setup(ctx) {
    await ctx.tool.hook("execute.before", (event) => {
      if (event.tool !== "subagent") return;
      const input = event.input;
      if (input === null || typeof input !== "object" || Array.isArray(input)) return;
      if (input.background === undefined) input.background = true;
    });
    await ctx.session.hook("context", (event) => {
      if (!event.system.some((part) => part.type === "text" && part.text === POLICY)) {
        event.system.push({ type: "text", text: POLICY });
      }
    });
  },
};
