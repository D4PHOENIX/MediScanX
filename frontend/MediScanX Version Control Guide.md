---
title: MediScanX Version Control Guide with Clickup Integration
---

This is the ultimate, battle-tested Git and project management workflow
designed specifically for the MediScanX architecture. Since your team of
three---Daud Noman, Muhammad Arham Shafaat, and Wassam Khan ---is
executing a highly ambitious 1-month sprint, this guide eliminates
integration bottlenecks, prevents merge conflicts, and creates a
pristine, professional paper trail for your final university defense.

Store this guide in your repository\'s README.md or a CONTRIBUTING.md
file so the entire team operates by the exact same rules.

**1. The Golden Rules of the Repository**

To maintain absolute stability, your repository relies on a flattened,
trunk-based integration model .

-   **main (The Production Build):** This branch contains 100% stable,
    tested, and demo-ready code. It is untouchable during daily
    development. You will only merge into main at the end of major
    milestones (e.g., right before your Internal Defense I and II).

-   **dev (The Integration Hub):** This is your active staging ground.
    All three developers merge their completed tasks here. **No one ever
    commits directly to dev.** If the dev branch breaks, all feature
    development stops until it is fixed.

-   **Zero Intermediate Branches:** There are no ml, api, or app
    integration branches. Every developer branches directly off dev and
    merges directly back into dev.

**2. Task Management: ClickUp as the Single Source of Truth**

To prevent double data entry, GitHub Issues are entirely bypassed.
ClickUp dictates the workflow.

1.  **Task Creation:** Every feature, bug, or setup step must exist as a
    ClickUp task *before* code is written.

2.  **The ClickUp ID:** Every task in ClickUp has a unique identifier
    (e.g., #CU-8xyz or just 8xyz). This ID is the critical link between
    your code and your project board.

3.  **GitHub Integration:** Ensure your GitHub repository is linked in
    your ClickUp Workspace Settings.

**3. Branching Strategy & Naming Conventions**

When you pull a task from ClickUp, you create a branch off the latest
dev.

**Strict Syntax:**
\<domain-prefix\>/\<ClickUp-ID\>-\<short-description\>

**Domain Prefixes (Who & Where):**

-   **ml/** (Dev 1 - AI/Models): Scripts, PyTorch training, TFLite
    conversions, and dataset handling.

    -   *Example:* ml/CU-1a2b-train-densenet-baseline

-   **app/** (Dev 2 - Frontend): Flutter UI, state management
    (Riverpod), and on-device logic.

    -   *Example:* app/CU-3c4d-build-camera-ui

-   **api/** (Dev 3 - Backend API): FastAPI routes, authentication
    logic, and vector embeddings.

    -   *Example:* api/CU-5e6f-jwt-middleware

-   **db/** (Dev 3 - Database): PostgreSQL schemas, PowerSync rules, and
    Row Level Security (RLS) policies.

    -   *Example:* db/CU-7g8h-rls-paramedic-policies

-   **Universal Prefixes:** bugfix/ (for resolving broken code) and
    config/ (for CI/CD or environment setups).

**4. Commit Message Standard (Conventional Commits)**

Branch names define *where* you are working; commit messages define
*what* you changed.

**Strict Syntax:** \<type\>(\<scope\>): \<clear description\>
#\<ClickUp-ID\>

**Commit Types:**

-   **feat**: A new feature or capability.

-   **fix**: A bug fix.

-   **chore**: Maintenance, dependency updates, or configuration
    changes.

-   **docs**: Updates to documentation, READMEs, or inline comments.

-   **refactor**: Restructuring code without altering its external
    behavior.

**Commit Examples by Role:**

-   **Dev 1:** feat(model): export hybrid CNN-LSTM to TFLite format
    #CU-1a2b

-   **Dev 2:** fix(ui): resolve overflow error on triage dashboard
    #CU-3c4d

-   **Dev 3:** chore(db): enable pgvector extension in cloud sql
    #CU-5e6f

**5. The Daily Developer Workflow (Step-by-Step)**

Here is the exact terminal sequence a developer follows to execute a
task.

Bash

\# 1. Start your day by syncing with the team\'s latest work

git checkout dev

git pull origin dev

\# 2. Branch out using your domain, ClickUp ID, and task description

git checkout -b api/CU-5e6f-jwt-middleware

\# 3. Write your code, test locally, and stage your changes

git add .

\# 4. Commit using the strict Conventional Commit syntax (do this often)

git commit -m \"feat(auth): add pydantic models for token validation
#CU-5e6f\"

\# 5. End your work session by pushing your branch to the remote
repository

git push origin api/CU-5e6f-jwt-middleware

**6. Pull Request (PR) & Code Review Protocols**

When a task is complete, it must cross the bridge into dev via a Pull
Request.

1.  **Open the PR:** Go to GitHub and open a PR from your branch (e.g.,
    api/CU-5e6f-jwt-middleware) into dev.

2.  **Title the PR:** api: setup supabase jwt middleware (Closes
    #CU-5e6f)

3.  **The Review Mandate:** You cannot merge your own code. You must
    assign at least one teammate as a reviewer. (e.g., Dev 3 asks Dev 2
    to verify the API response structure).

4.  **Squash and Merge:** Once approved, the PR author clicks **\"Squash
    and merge\"**. This is mandatory. It condenses all the minor
    \"work-in-progress\" commits into one clean, professional commit on
    the dev branch.

5.  **Clean Up:** Delete your feature branch immediately after merging
    to keep the repository uncluttered.

6.  **Automation:** Because you included #CU-5e6f in your commits and PR
    title, ClickUp will automatically move the task to \"Completed.\"

With this ultimate protocol established, your repository will remain
clean, your team will avoid overlapping code, and your final project
documentation will practically write itself.
