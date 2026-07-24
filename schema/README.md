# MediScanX Database Schema

## Overview
The `0001_initial_schema.sql` file serves as the single source of truth for bootstrapping the MediScanX database. It consolidates all historical schema fragments, table definitions, and constraints into a single, idempotent baseline migration file that adheres to strict DBA standards.

## Architectural Highlights
- **Vector Search (pgvector):** Integrates the `pgvector` extension with 384-dimensional half-precision embeddings (`halfvec`) and optimized HNSW indexing, forming the high-performance knowledge base for our Retrieval-Augmented Generation (RAG) architecture.
- **LangGraph State Persistence:** Includes native PostgreSQL tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) to persist threaded conversational state for the AI agents, ensuring reliable resume-ability.
- **Offline-First Replication (PowerSync):** Employs global logical replication (`PUBLICATION powersync`) and strict `REPLICA IDENTITY FULL` configurations on core domain entities, empowering seamless offline data synchronization across mobile clients.

## Schema Structure
The baseline schema is logically organized into 7 strict sections to guarantee dependency resolution during execution:
1. **[ SECTION 1: EXTENSIONS & TYPES ]** - Provisions necessary PostgreSQL extensions (e.g., `vector`).
2. **[ SECTION 2: TABLES ]** - Defines all core domain entities (`doctor_profiles`, `patient_records`, `scan_results`, `rag_corpus`, `chat_messages`, and LangGraph tables) completely decoupled from foreign key constraints.
3. **[ SECTION 3: INDEXES ]** - Provisions high-performance indexes (e.g., HNSW for vector operations, patient timeline indexing).
4. **[ SECTION 4: FOREIGN KEYS ]** - Explicitly defines cross-table relational constraints and cascading deletion rules.
5. **[ SECTION 5: FUNCTIONS & TRIGGERS ]** - Implements domain logic, such as the `match_rag_corpus` vector search and the `handle_new_user_profile` Supabase Auth trigger.
6. **[ SECTION 6: ROW LEVEL SECURITY ]** - Secures tenant data with strict RLS policies mapped to `auth.uid()`.
7. **[ SECTION 7: REPLICATION ]** - Configures logical replication publications and replica identities for PowerSync.

## Usage & Deployment

### Fresh Database Provisioning
For a clean installation, **only run `0007_updated_schema.sql`**. This file is a fully squashed, standalone baseline that creates all necessary tables, extensions, and configurations from scratch. 
Do not run the legacy migrations (0001 through 0006) on a fresh database.

### Existing Provisioned Databases
If your database was previously provisioned with the older legacy migrations (0001 through 0004), you should apply `0005_medcpt_768.sql` and `0006_narrow_powersync_publication.sql` sequentially to upgrade your schema to the V2 standard.

### Local Development (Supabase CLI)
To spin up the database locally and apply the schema via the Supabase CLI, run:
```bash
# Start the local Supabase stack
supabase start

# Reset the database to apply 0007_updated_schema.sql (Warning: Wipes local data)
supabase db reset
```

### Production / Manual Execution
To manually deploy the schema to a hosted Supabase project:
1. Open your project in the [Supabase Dashboard](https://supabase.com/dashboard).
2. Navigate to the **SQL Editor**.
3. Create a new query, paste the full contents of `0007_updated_schema.sql`, and click **Run**.
*(Note: Because the script is idempotent, it is safe to run on an empty database. However, ensure no conflicting tables exist beforehand if applying to a dirty state.)*
