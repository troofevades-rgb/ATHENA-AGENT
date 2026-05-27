/**
 * Stub for ``react-devtools-core``. Ink imports it inside a path
 * gated by ``process.env.DEV === 'true'``, but the static
 * ``import`` is hoisted to module-load time even when that branch
 * is dead. Production builds alias the real package to this stub
 * so node doesn't try to resolve a dependency we never run.
 *
 * If a contributor wants the real React DevTools in dev mode, run
 * ``bun add -d react-devtools-core`` and remove the alias from
 * ``tsconfig.json`` ``paths``.
 */

const stub = {
  connectToDevTools(): void {
    // no-op in production builds
  },
};

export default stub;
