import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import require_role
from app.models import Role, User
from app.schemas import DocRead, DocSummary

router = APIRouter()

# docs/*.md, synced alongside app/ into /opt/groundctl/docs by
# sync_app_code (scripts/lib/app.sh) — sibling to app/, not nested inside
# it, so this resolves identically in a dev checkout (repo_root/docs) and
# in production (/opt/groundctl/docs). Same Path(__file__)-relative
# pattern app/main.py uses for app/static.
_DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "docs"

# Filenames only — no path separators — so this can never traverse outside
# _DOCS_DIR regardless of what a caller passes. Matches the shape every
# doc in docs/ actually has (lowercase, hyphens, .md).
_DOC_FILENAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")

# First H1 (# Title) if present, else the filename — avoids requiring a
# second source of truth for display titles.
_H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


def _title_for(filename: str, content: str) -> str:
    match = _H1_RE.search(content)
    return match.group(1).strip() if match else filename


def _list_docs() -> list[DocSummary]:
    if not _DOCS_DIR.is_dir():
        return []
    summaries = []
    for path in sorted(_DOCS_DIR.glob("*.md")):
        if not _DOC_FILENAME_RE.fullmatch(path.name):
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        summaries.append(DocSummary(filename=path.name, title=_title_for(path.name, content)))
    return summaries


@router.get("", response_model=list[DocSummary])
def list_docs(current_user: User = Depends(require_role(Role.viewer))):
    return _list_docs()


@router.get("/{filename}", response_model=DocRead)
def get_doc(filename: str, current_user: User = Depends(require_role(Role.viewer))):
    if not _DOC_FILENAME_RE.fullmatch(filename):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid doc filename")

    path = _DOCS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="doc not found")

    content = path.read_text(encoding="utf-8", errors="replace")
    return DocRead(filename=filename, title=_title_for(filename, content), content=content)
