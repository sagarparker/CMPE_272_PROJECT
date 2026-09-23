# MediaMesh Project

## Purpose

This GitHub Project tracks the design and implementation of **MediaMesh**, a distributed media storage engine with intelligent recommendations and a semantic search engine.

The project combines three main concerns:

- **Distributed storage:** media is stored across multiple nodes with replication and reliable retrieval.
- **Semantic discovery:** embeddings and a vector index allow users to search by meaning instead of only exact keywords.
- **Intelligent recommendations:** the system recommends related media using content similarity and, later, interaction signals.

## MVP Deliverables

- Upload and media-ingestion API
- Distributed storage-node abstraction
- Replication strategy and failure handling
- Metadata persistence
- Media embedding pipeline
- Vector-based semantic search
- Similar-content recommendation endpoint
- Media retrieval endpoint
- Basic web UI
- Tests and deployment documentation

## Project Workflow

Items move through **Todo → In Progress → Done**.

Priority is recorded as **High, Medium, or Low**. Estimate is a numeric complexity value using a Fibonacci-style scale such as **1, 2, 3, 5, 8**. Work is grouped into two-week iterations.

### Views

- **Team Backlog** — table layout showing Status, Priority, Estimate, Iteration, and assignee.
- **Kanban Board** — board layout grouped by Status for day-to-day progress tracking.
- **Product Roadmap** — roadmap layout using the Iteration field to visualize scheduled work.

## Definition of Done

An item is considered done when its acceptance criteria are satisfied, relevant tests pass, documentation is updated where necessary, and the change has been reviewed and merged.
