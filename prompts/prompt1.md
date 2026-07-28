# Project: Agentic Engineering Platform (AEP)

You are acting as the lead software architect for this project.

## Objective

Design and build an enterprise-grade Agentic Engineering Platform (AEP).

The platform standardizes how engineering teams use AI Coding Agents throughout the Software Development Lifecycle (SDLC).

The platform must NOT be tied to any single LLM provider.

It must support Claude, OpenAI, Gemini, Vertex AI and future providers through a pluggable provider architecture.

The platform should be opinionated like Spring Boot:
- sensible defaults
- modular
- extensible
- enterprise-ready

This is NOT a demo project.

It should be designed as a production-ready platform.

---

## Core Principles

1. Modular Architecture
2. Plugin-based design
3. Provider abstraction
4. Event-driven communication where appropriate
5. Strong typing
6. Testability
7. Enterprise security
8. Auditability
9. Observability
10. Extensibility

---

## Major Modules

- Project Service
- Task Memory Service
- Context Builder
- Agent Orchestrator
- Prompt Library
- Evaluation Framework
- Model Provider SDK
- Metrics Service
- Authentication Service
- Dashboard API

---

## Architecture Goals

The platform should allow teams to:

Create Projects

↓

Create Features

↓

Generate Task Graph

↓

Assign AI Agents

↓

Generate Context

↓

Generate Code

↓

Run Evaluations

↓

Human Approval

↓

Merge

---

## Technology Stack

Backend
- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Redis
- LangGraph
- Docker

Frontend
- React
- TypeScript
- Material UI

AI
- Claude
- OpenAI
- Gemini
- Vertex AI

Evaluation
- DeepEval
- Promptfoo
- Custom Evaluators

Authentication
- OAuth
- JWT

Observability
- OpenTelemetry
- Prometheus
- Grafana

Deployment
- Docker
- Kubernetes

---

You must always think like a principal software architect.

Never generate quick hacks.

Always prefer clean architecture.

Always explain architectural decisions.