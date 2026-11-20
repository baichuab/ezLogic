import { describe, expect, it } from 'vitest';
import { composePrompt, extractProofText, FileError, formatBytes, MAX_FILE_BYTES, validateProofFile } from './extract';

describe('formatBytes', () => {
	it('uses the smallest sensible unit', () => {
		expect(formatBytes(500)).toBe('500 B');
		expect(formatBytes(2048)).toBe('2.0 KB');
		expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
		expect(formatBytes(2 * 1024 * 1024 * 1024)).toBe('2.0 GB');
	});
});

describe('validateProofFile', () => {
	it('accepts .tex and .pdf, case-insensitively', () => {
		expect(() => validateProofFile(new File(['x'], 'proof.tex'))).not.toThrow();
		expect(() => validateProofFile(new File(['x'], 'Proof.PDF'))).not.toThrow();
	});

	it('rejects an unsupported extension', () => {
		expect(() => validateProofFile(new File(['x'], 'proof.docx'))).toThrow(FileError);
	});

	it('rejects an empty file', () => {
		expect(() => validateProofFile(new File([], 'proof.tex'))).toThrow(FileError);
	});

	it('rejects a file over the size limit', () => {
		const big = new File([new Uint8Array(MAX_FILE_BYTES + 1)], 'proof.tex');
		expect(() => validateProofFile(big)).toThrow(FileError);
	});

	it('accepts a file exactly at the size limit', () => {
		const atLimit = new File([new Uint8Array(MAX_FILE_BYTES)], 'proof.tex');
		expect(() => validateProofFile(atLimit)).not.toThrow();
	});
});

describe('composePrompt', () => {
	it('puts typed instructions before the file content', () => {
		const out = composePrompt('Prove this is correct.', 'proof.tex', '\\begin{theorem}...');
		expect(out).toBe(
			'Prove this is correct.\n\n--- Attached file: proof.tex ---\n\\begin{theorem}...'
		);
	});

	it('falls back to a generic instruction when none were typed', () => {
		const out = composePrompt('   ', 'proof.tex', 'content');
		expect(out).toContain('Formalise and verify the proof in the attached file.');
	});
});

describe('extractProofText', () => {
	it('reads a .tex file as plain text', async () => {
		const file = new File(['\\begin{theorem} 1 + 1 = 2 \\end{theorem}'], 'proof.tex', {
			type: 'text/plain'
		});
		await expect(extractProofText(file)).resolves.toContain('theorem');
	});

	it('rejects an unsupported file before attempting to read it', async () => {
		const file = new File(['whatever'], 'proof.docx');
		await expect(extractProofText(file)).rejects.toThrow(FileError);
	});

	it('reports a .tex file with no text', async () => {
		const file = new File(['   \n\t  '], 'proof.tex');
		await expect(extractProofText(file)).rejects.toThrow(/no text/);
	});
});
