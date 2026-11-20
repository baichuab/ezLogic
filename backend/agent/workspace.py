"""Sandboxed local file system the agent operates on."""

from pathlib import Path

IGNORED_DIRS = {".lake", ".git", "__pycache__", "build"}


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, path: str) -> Path:
        """Resolve a workspace-relative path, refusing anything outside the root."""
        target = (self.root / path).resolve()
        if target != self.root and self.root not in target.parents:
            raise WorkspaceError(f"Path escapes workspace: {path}")
        return target

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def list_files(self, path: str = ".") -> list[str]:
        base = self.resolve(path)
        if not base.exists():
            raise WorkspaceError(f"No such directory: {path}")
        if base.is_file():
            return [self.rel(base)]
        files = []
        for p in sorted(base.rglob("*")):
            if any(part in IGNORED_DIRS for part in p.relative_to(self.root).parts):
                continue
            if p.is_file():
                files.append(self.rel(p))
        return files

    def read_file(self, path: str) -> str:
        target = self.resolve(path)
        if not target.is_file():
            raise WorkspaceError(f"No such file: {path}")
        return target.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        target = self.resolve(path)
        if target == self.root:
            raise WorkspaceError("Cannot write to workspace root")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {self.rel(target)}"

    def edit_file(self, path: str, old_string: str, new_string: str) -> str:
        content = self.read_file(path)
        count = content.count(old_string)
        if count == 0:
            raise WorkspaceError("old_string not found in file")
        if count > 1:
            raise WorkspaceError(
                f"old_string matches {count} times; include more context to make it unique"
            )
        self.resolve(path).write_text(content.replace(old_string, new_string, 1), encoding="utf-8")
        return f"Edited {path}"

    def delete_file(self, path: str) -> str:
        target = self.resolve(path)
        if not target.is_file():
            raise WorkspaceError(f"No such file: {path}")
        target.unlink()
        return f"Deleted {path}"
