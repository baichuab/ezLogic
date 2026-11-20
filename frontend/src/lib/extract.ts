export const MAX_FILE_BYTES = 1024 * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = ['.pdf', '.tex'];

export class FileError extends Error {}

export function formatBytes(n: number): string {
	if (n < 1024) return `${n} B`;
	if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
	if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
	return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

/** Throws a FileError if the file is not an acceptable .pdf/.tex upload. */
export function validateProofFile(file: File): void {
	const name = file.name.toLowerCase();
	if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
		throw new FileError('Only .pdf and .tex files are supported.');
	}
	if (file.size > MAX_FILE_BYTES) {
		throw new FileError(`File is too large (${formatBytes(file.size)}). The limit is 1 GB.`);
	}
	if (file.size === 0) throw new FileError('This file is empty.');
}

async function pdfToText(file: File): Promise<string> {
	const [pdfjs, worker] = await Promise.all([
		import('pdfjs-dist'),
		import('pdfjs-dist/build/pdf.worker.min.mjs?url')
	]);
	pdfjs.GlobalWorkerOptions.workerSrc = worker.default;

	const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
	try {
		const pages: string[] = [];
		for (let i = 1; i <= doc.numPages; i++) {
			const page = await doc.getPage(i);
			const content = await page.getTextContent();
			let text = '';
			for (const item of content.items) {
				if (!('str' in item)) continue;
				text += item.str + (item.hasEOL ? '\n' : '');
			}
			pages.push(text.trim());
		}
		return pages.filter(Boolean).join('\n\n');
	} finally {
		await doc.cleanup();
	}
}

/** Read the text of a .tex or .pdf file in the browser. */
export async function extractProofText(file: File): Promise<string> {
	validateProofFile(file);
	let text: string;
	try {
		text = file.name.toLowerCase().endsWith('.pdf') ? await pdfToText(file) : await file.text();
	} catch (e) {
		if (e instanceof FileError) throw e;
		throw new FileError(`Couldn’t read ${file.name}. Is it a valid file?`);
	}
	text = text.trim();
	if (!text) {
		throw new FileError(
			file.name.toLowerCase().endsWith('.pdf')
				? 'Couldn’t extract any text from this PDF (is it a scanned image?).'
				: 'This file has no text.'
		);
	}
	return text;
}

/** Prompt sent to the agent: instructions followed by the extracted file contents. */
export function composePrompt(instructions: string, fileName: string, fileText: string): string {
	const lead = instructions.trim() || 'Formalise and verify the proof in the attached file.';
	return `${lead}\n\n--- Attached file: ${fileName} ---\n${fileText}`;
}
