import tailwindcss from '@tailwindcss/vite';
import adapter from '@sveltejs/adapter-auto';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Backend the dev server proxies `/api` to. Override with API_PROXY_TARGET if
// the FastAPI app isn't running on the default host/port.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
	plugins: [
		tailwindcss(),
		sveltekit({
			compilerOptions: {
				// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
				runes: ({ filename }) =>
					filename.split(/[/\\]/).includes('node_modules') ? undefined : true
			},

			// adapter-auto only supports some environments, see https://svelte.dev/docs/kit/adapter-auto for a list.
			// If your environment is not supported, or you settled on a specific environment, switch out the adapter.
			// See https://svelte.dev/docs/kit/adapters for more information about adapters.
			adapter: adapter()
		})
	],
	server: {
		proxy: {
			// Same-origin `/api` calls so the guest session cookie works without
			// CORS/SameSite issues, and SSE streaming passes straight through.
			'/api': {
				target: API_PROXY_TARGET,
				changeOrigin: true
			}
		}
	}
});
