"""OpenVS CI — GitHub Actions integration, PR auto-review, test gating."""

from openvs.ci.pipeline import ci_pipeline
from openvs.ci.github_actions import GitHubActionsIntegration

__all__ = ["ci_pipeline", "GitHubActionsIntegration"]
