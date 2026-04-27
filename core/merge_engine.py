"""
Merge Engine — safe patch merging for multi-agent results.

When parallel agents produce overlapping patches, the merge engine:
  1. Detects conflicts (same file, overlapping regions)
  2. Attempts semantic merge (non-overlapping patches auto-merge)
  3. Escalates conflicts to critic for resolution
  4. Commits merged result via transaction engine

This is the AI pull request merge system.
"""

import difflib
import time
from typing import Optional
from core.event_bus import bus


class Patch:
    """A single code patch from an agent."""

    def __init__(
        self,
        source_agent: str,
        file_path: str,
        old_content: str,
        new_content: str,
        patch_id: str = None,
    ):
        self.id = patch_id or f"patch_{abs(hash((source_agent, file_path, time.time())))}"
        self.source_agent = source_agent
        self.file_path = file_path
        self.old_content = old_content
        self.new_content = new_content
        self.timestamp = time.time()

    def diff(self) -> str:
        """Generate unified diff for this patch."""
        old_lines = self.old_content.splitlines(keepends=True)
        new_lines = self.new_content.splitlines(keepends=True)
        return "".join(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{self.file_path}",
            tofile=f"b/{self.file_path}",
        ))

    def changed_regions(self) -> list[tuple[int, int]]:
        """Return line ranges that were changed (1-indexed, inclusive)."""
        old_lines = self.old_content.splitlines()
        new_lines = self.new_content.splitlines()
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        regions = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in ("replace", "insert", "delete"):
                regions.append((i1 + 1, i2))  # 1-indexed
        return regions

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_agent": self.source_agent,
            "file_path": self.file_path,
            "diff": self.diff(),
            "changed_regions": self.changed_regions(),
        }


class MergeConflict:
    """Detected conflict between two patches on the same file."""

    def __init__(self, file_path: str, patch_a: Patch, patch_b: Patch, overlap_regions: list):
        self.file_path = file_path
        self.patch_a = patch_a
        self.patch_b = patch_b
        self.overlap_regions = overlap_regions
        self.resolved = False
        self.resolution: Optional[str] = None  # "patch_a", "patch_b", "manual"

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "patch_a": self.patch_a.id,
            "patch_b": self.patch_b.id,
            "overlap_regions": self.overlap_regions,
            "resolved": self.resolved,
            "resolution": self.resolution,
        }


class MergeResult:
    """Result of a merge operation."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.patches_applied: list[str] = []
        self.conflicts: list[MergeConflict] = []
        self.merged_content: Optional[str] = None
        self.status = "pending"  # pending, merged, conflict

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "patches_applied": self.patches_applied,
            "conflicts": [c.to_dict() for c in self.conflicts],
            "status": self.status,
        }


class MergeEngine:
    """Safely merges patches from multiple agents.

    Pipeline:
      subtask patches → conflict detector → semantic merge → critic validation → transaction commit

    Do NOT skip semantic conflict detection.
    """

    def merge_patches(self, patches: list[Patch], base_content: str = None) -> dict:
        """Merge a list of patches for a single file.

        Args:
            patches: List of Patch objects (all for the same file)
            base_content: Original file content (if None, uses first patch's old_content)

        Returns:
            MergeResult dict with status and merged content.
        """
        if not patches:
            return {"status": "no_patches", "merged_content": None}

        # Group by file
        by_file: dict[str, list[Patch]] = {}
        for p in patches:
            by_file.setdefault(p.file_path, []).append(p)

        all_results = []
        all_conflicts = []

        for file_path, file_patches in by_file.items():
            result = self._merge_file(file_path, file_patches, base_content)
            all_results.append(result)
            all_conflicts.extend(result.get("conflicts", []))

        has_conflicts = len(all_conflicts) > 0

        bus.emit("merge.complete" if not has_conflicts else "merge.conflict", {
            "files": len(by_file),
            "patches": len(patches),
            "conflicts": len(all_conflicts),
        })

        return {
            "status": "conflict" if has_conflicts else "merged",
            "results": all_results,
            "conflicts": all_conflicts,
            "total_conflicts": len(all_conflicts),
        }

    def _merge_file(self, file_path: str, patches: list[Patch], base_content: str = None) -> dict:
        """Merge patches for a single file."""
        if len(patches) == 1:
            # Single patch — no conflict possible
            return {
                "file_path": file_path,
                "status": "merged",
                "patches_applied": [p.id for p in patches],
                "conflicts": [],
                "merged_content": patches[0].new_content,
            }

        # Multiple patches — check for conflicts
        current = base_content or patches[0].old_content
        conflicts = []
        applied = []

        # Sort patches by source agent priority (critic patches applied last)
        priority_order = {"critic": 10, "security_auditor": 5, "tester": 3, "coder": 2, "planner": 1}
        sorted_patches = sorted(patches, key=lambda p: priority_order.get(p.source_agent, 0))

        for i, patch in enumerate(sorted_patches):
            # Check if this patch's old content matches current state
            if patch.old_content == current:
                # Clean apply
                current = patch.new_content
                applied.append(patch.id)
            else:
                # Try to apply by finding the old string in current content
                if patch.old_content in current:
                    current = current.replace(patch.old_content, patch.new_content, 1)
                    applied.append(patch.id)
                else:
                    # Conflict — overlapping changes
                    regions_a = sorted_patches[i-1].changed_regions() if i > 0 else []
                    regions_b = patch.changed_regions()
                    overlap = self._find_overlaps(regions_a, regions_b)

                    conflict = {
                        "file_path": file_path,
                        "patch_ids": [p.id for p in sorted_patches[:i+1]],
                        "overlap_regions": overlap,
                        "resolution_needed": True,
                    }
                    conflicts.append(conflict)

        return {
            "file_path": file_path,
            "status": "conflict" if conflicts else "merged",
            "patches_applied": applied,
            "conflicts": conflicts,
            "merged_content": current if not conflicts else None,
        }

    @staticmethod
    def _find_overlaps(regions_a: list, regions_b: list) -> list:
        """Find overlapping line regions between two change sets."""
        overlaps = []
        for start_a, end_a in regions_a:
            for start_b, end_b in regions_b:
                # Check if ranges overlap
                if start_a <= end_b and start_b <= end_a:
                    overlaps.append((max(start_a, start_b), min(end_a, end_b)))
        return overlaps

    def resolve_conflict(self, conflict: dict, resolution: str, resolved_content: str = None) -> dict:
        """Resolve a merge conflict.

        Args:
            conflict: The conflict dict from a merge result
            resolution: "patch_a", "patch_b", or "manual"
            resolved_content: Required for "manual" resolution
        """
        if resolution == "manual" and resolved_content is None:
            return {"status": "error", "reason": "manual resolution requires resolved_content"}

        bus.emit("merge.conflict_resolved", {
            "file_path": conflict["file_path"],
            "resolution": resolution,
        })

        return {
            "status": "resolved",
            "file_path": conflict["file_path"],
            "resolution": resolution,
            "resolved_content": resolved_content,
        }


# Global singleton
merge_engine = MergeEngine()