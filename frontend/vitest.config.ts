import { defineConfig } from 'vite';

// A plain Vite config for unit tests, separate from vite.config.ts: the unit
// tests only exercise plain .ts modules (src/lib/api.ts, mock.ts, ...), never
// .svelte files or $app/* imports, so the SvelteKit plugin isn't needed and
// would only slow startup down.
export default defineConfig({
	test: {
		environment: 'node',
		include: ['src/**/*.test.ts']
	}
});
