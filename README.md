# MediaMesh

**Distributed media storage with intelligent recommendations and semantic search.**

MediaMesh is a distributed media storage engine designed to store, retrieve, and discover large collections of images, audio, and video. The system combines resilient distributed storage with metadata extraction, vector embeddings, semantic search, and personalized recommendations.

## Goals

- Store media across multiple storage nodes with replication and fault tolerance.
- Provide a unified API for uploading, retrieving, and deleting media.
- Extract searchable metadata from uploaded media.
- Generate vector embeddings for semantic similarity search.
- Recommend relevant media based on content similarity and user interaction signals.
- Provide a simple web interface for search, discovery, and media management.

## Proposed Architecture

1. **API Gateway / Backend** - accepts upload, search, recommendation, and retrieval requests.
2. **Metadata Service** - stores media metadata, ownership, tags, and storage locations.
3. **Distributed Storage Nodes** - hold media objects with replication.
4. **Embedding Pipeline** - creates vector representations for searchable media.
5. **Vector Database / Index** - supports nearest-neighbor semantic search.
6. **Recommendation Service** - ranks media using content similarity and interaction history.
7. **Web Client** - exposes upload, search, browsing, and recommendation workflows.

## MVP Scope

The first release will support media upload, distributed placement, metadata persistence, semantic text-to-media search, basic similarity recommendations, retrieval, and a lightweight user interface.

## Project Management

Work is tracked in GitHub Projects using:

- **Status:** Todo, In Progress, Done
- **Priority:** High, Medium, Low
- **Estimate:** numeric complexity estimate
- **Iteration:** two-week development iterations
- **Views:** Team Backlog (Table), Kanban Board (Board), Product Roadmap (Roadmap)

See [`PROJECT_README.md`](PROJECT_README.md), [`docs/PROJECT_SETUP.md`](docs/PROJECT_SETUP.md), and [`PROGRESS_LOG.md`](PROGRESS_LOG.md) for the assignment setup.
