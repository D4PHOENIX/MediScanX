# B4: CXR Cloud Inference Engine & API - Git Execution Guide

Follow this strict terminal sequence from the **root of the MediScanX-Backend repository** to stage, commit, and push the finalized `cxr_service` container.

## A. Branch Creation
Create and checkout the new branch off `dev`:
```bash
git checkout dev
git pull origin dev
git checkout -b api/B4-cxr-cloud-inference
```

## B. Staged Commits
Execute the following commands explicitly to prevent the `local_dev/` directory or `.env` files from being pushed to the repository. Do NOT use `git add .`.

**Commit 1: Task B4.1 - Build CXR Engine Singleton Service**
```bash
git add cxr_service/src/app/engine/ \
        cxr_service/src/app/explainability/ \
        cxr_service/src/app/models/ \
        cxr_service/weights/

git commit -m "feat(cxr): build cxr engine singleton service #B4.1"
```

**Commit 2: Task B4.2 - Configure Backend for ML-Only Boot**
```bash
git add cxr_service/src/app/core/ \
        cxr_service/pyproject.toml \
        cxr_service/uv.lock \
        cxr_service/.env.example \
        cxr_service/requirements.txt \
        cxr_service/Dockerfile

git commit -m "chore(cxr): configure backend for ml-only boot #B4.2"
```

**Commit 3: Task B4.3 - Implement CXR Cloud Inference Endpoint**
```bash
# Note: Ensure you include the root-level .github workflow
git add cxr_service/src/app/main.py \
        cxr_service/src/app/api/ \
        cxr_service/tests/ \
        cxr_service/README.md \
        cxr_service/__init__.py \
        .github/workflows/cxr-service.yml

git commit -m "feat(cxr): implement cxr cloud inference endpoint #B4.3"
```

## C. Push & PR Guidelines

Push the branch to the remote origin:
```bash
git push -u origin api/B4-cxr-cloud-inference
```

### Pull Request Template
When opening the Pull Request against the `dev` branch, use the following template to ensure the ClickUp automation triggers properly:

**PR Title:**
`feat(cxr): implement CXR Cloud Inference Engine & API (Closes #B4)`

**PR Description:**
```markdown
### Summary
This PR finalizes the B4 ClickUp tasks by implementing the complete, DDD-aligned `cxr_service` ML backend. 

### Subtasks Completed
- **#B4.1**: Built CXR Engine Singleton Service with lazy-loading and multi-label tensor mapping.
- **#B4.2**: Configured backend for ML-only boot and consolidated dual configurations.
- **#B4.3**: Implemented FastAPI cloud inference routing endpoints.

### QA Notes
- Verified `uv` dependency locking and PyTorch caching pipeline.
- Test suite is 100% green and strictly validates clinical thresholds.
```
