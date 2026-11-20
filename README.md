# ezLogic

An AI-powered proof verification platform designed for mathematicians. Write Lean proofs interactively with real-time verification and AI-powered explanations.

## Overview

ezLogic is an intelligent platform that enables mathematicians to write and verify formal proofs in Lean. The system leverages LLM as an agent that can:

- **Write Lean proofs** automatically or assist in proof development
- **Verify proofs** by executing Lean commands and processing verification results
- **Explain code snippets** by analyzing the generated Lean code and breaking down the proof logic
- **Iterate intelligently** by responding to verification errors and refining proofs
- **Break down** the overall logical proof

## Getting Started

### Prerequisites
- **Node.js** (v18+) and **npm** - For the SvelteKit frontend
- **Python** (v3.10+) and **pip** (or **uv**) - For the FastAPI backend
- **Lean 4** via [elan](https://github.com/leanprover/elan) - For proof verification (optional for development; the agent reports proofs as unverified without it)
- **OpenRouter API key** - The agent calls LLMs through [OpenRouter](https://openrouter.ai)

#### Installing Lean 4

Lean is installed through `elan`, the Lean toolchain manager (it is not a pip package):

```bash
curl https://elan.lean-lang.org/elan-init.sh -sSf | sh
lean --version && lake --version
```

The backend uses the `lean` CLI to compile proof files, and the
[`lean-interact`](https://github.com/augustepoiroux/LeanInteract) Python package (installed from
`requirements.txt`) to check short snippets in a Lean REPL. The first snippet check downloads and
builds the REPL, so it takes a while.

### Installation

#### 1. Clone and Install Dependencies

```bash
# Install frontend dependencies
cd frontend
npm install

# Install backend dependencies into a virtualenv
cd ../backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

#### 2. Configure Environment Variables

```bash
# Create backend environment file
cd backend
cp .env.example .env
# Edit .env and set OPENROUTER_API_KEY (and optionally OPENROUTER_MODEL)
```

### Running the Application

You'll need to run both the frontend and backend in separate terminals:

#### Terminal 1 - Frontend
```bash
cd frontend
npm run dev
```
The frontend will be available at `http://localhost:5173`

#### Terminal 2 - Backend
```bash
cd backend
source .venv/bin/activate
python main.py
```
The backend API will be available at `http://localhost:8000`

Access the interactive API documentation at `http://localhost:8000/docs`

### Quick Start (All-in-One)

If you have both terminals available, you can start everything:

```bash
# Terminal 1
cd frontend && npm install && npm run dev

# Terminal 2
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && python main.py
```

## Architecture

### Frontend
- **SvelteKit** - Modern, performant UI framework for the chat interface
- Real-time proof editing and feedback display
- Interactive proof verification status updates

### Backend
- **Python FastAPI** - High-performance REST API
- **Local File System** - Manages Lean project files and proof code
- **Lean Integration** - Executes Lean commands to verify proofs and collect error messages
- **AI Agent** - Orchestrates proof writing, verification, and explanation through OpenRouter

### Agent Tools
The agent (`backend/agent/`) runs a tool-calling loop and can only touch files inside the
sandboxed workspace directory (`WORKSPACE_DIR`, default `backend/workspace/`):

| Tool | Description |
| --- | --- |
| `list_files` | List files in the workspace |
| `read_file` | Read a file |
| `write_file` | Create or overwrite a file |
| `edit_file` | Replace a unique string in a file |
| `delete_file` | Delete a file |
| `check_lean_file` | Compile a `.lean` file with the Lean CLI (`lake env lean` inside a Lake project) |
| `check_lean_snippet` | Check a short snippet in a Lean REPL via `lean-interact` |

## Workflow

1. User inputs a mathematical statement, proof sketch or paper
2. The agent generates or refines Lean proof code
3. Backend writes the proof to the local file system
4. Lean is executed to verify the proof
5. Verification results are returned to the agent
6. Agent explains the proof or iterates on errors
7. User receives explanation and verification status in the chat interface
