# ezLogic

A Claude-powered proof verification platform designed for mathematicians. Write Lean proofs interactively with real-time verification and AI-powered explanations.

## Overview

ezLogic is an intelligent platform that enables mathematicians to write and verify formal proofs in Lean. The system leverages LLM as an agent that can:

- **Write Lean proofs** automatically or assist in proof development
- **Verify proofs** by executing Lean commands and processing verification results
- **Explain code snippets** by analyzing the generated Lean code and breaking down the proof logic
- **Iterate intelligently** by responding to verification errors and refining proofs

## Architecture

### Frontend
- **SvelteKit** - Modern, performant UI framework for the chat interface
- Real-time proof editing and feedback display
- Interactive proof verification status updates

### Backend
- **Python FastAPI** - High-performance REST API
- **Local File System** - Manages Lean project files and proof code
- **Lean Integration** - Executes Lean commands to verify proofs and collect error messages
- **AI Agent** - Orchestrates proof writing, verification, and explanation

## Workflow

1. User inputs a mathematical statement, proof sketch or paper
2. Claude agent generates or refines Lean proof code
3. Backend writes the proof to the local file system
4. Lean is executed to verify the proof
5. Verification results are returned to Claude
6. Agent explains the proof or iterates on errors
7. User receives explanation and verification status in the chat interface
