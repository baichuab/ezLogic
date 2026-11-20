# ezLogic

A Claude-powered proof verification platform designed for mathematicians. Write Lean proofs interactively with real-time verification and AI-powered explanations.

## Overview

ezLogic is an intelligent platform that enables mathematicians to write and verify formal proofs in Lean. The system leverages LLM as an agent that can:

- **Write Lean proofs** automatically or assist in proof development
- **Verify proofs** by executing Lean commands and processing verification results
- **Explain code snippets** by analyzing the generated Lean code and breaking down the proof logic
- **Iterate intelligently** by responding to verification errors and refining proofs

## Getting Started

### Prerequisites
- **Node.js** (v18+) and **npm** - For the SvelteKit frontend
- **Python** (v3.8+) and **pip** - For the FastAPI backend
- **Lean 4** - For proof verification (optional for development)

### Installation

#### 1. Clone and Install Dependencies

```bash
# Install frontend dependencies
cd frontend
npm install

# Install backend dependencies
cd ../backend
pip install -r requirements.txt
```

#### 2. Configure Environment Variables

```bash
# Create backend environment file
cd backend
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
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
cd backend && pip install -r requirements.txt && python main.py
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
- **AI Agent** - Orchestrates proof writing, verification, and explanation

## Workflow

1. User inputs a mathematical statement, proof sketch or paper
2. Claude agent generates or refines Lean proof code
3. Backend writes the proof to the local file system
4. Lean is executed to verify the proof
5. Verification results are returned to Claude
6. Agent explains the proof or iterates on errors
7. User receives explanation and verification status in the chat interface
