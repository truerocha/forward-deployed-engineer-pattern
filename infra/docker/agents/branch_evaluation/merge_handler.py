"""
Merge Handler — Auto-merge eligible PRs and transition issues to DONE.

Implements the two core user goals:
1. Auto-merge when score >= 8.0, CI green, L1/L2
2. Move the parent issue to DONE status in GitHub Projects

Uses GitHub REST API for merge and GraphQL API for Projects V2 status transitions.

Design ref: docs/design/branch-evaluation-agent.md Section 10.4
Security: Uses GITHUB_TOKEN from environment (Secrets Manager via ADR-014)
"""

import json
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger("fde.branch_evaluation.merge_handler")

GITHUB_API = "https://api.github.com"
GITHUB_GRAPHQL = "https://api.github.com/graphql"


def _get_token() -> str:
    """Get GitHub token from environment."""
    return os.environ.get("GITHUB_TOKEN", "")


def _github_rest(method: str, path: str, data: dict | None = None) -> tuple[int, dict]:
    """Make a GitHub REST API request."""
    token = _get_token()
    if not token:
        logger.error("GITHUB_TOKEN not set")
        return 401, {"error": "GITHUB_TOKEN not set"}

    url = f"{GITHUB_API}{path}"
    body = json.dumps(data).encode() if data else None

    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            response_body = json.loads(resp.read().decode())
            return resp.status, response_body
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error("GitHub API error: %s %s -> %d: %s", method, path, e.code, error_body[:300])
        try:
            return e.code, json.loads(error_body)
        except json.JSONDecodeError:
            return e.code, {"error": error_body[:300]}
    except Exception as e:
        logger.error("GitHub API request failed: %s", e)
        return 500, {"error": str(e)}


def _github_graphql(query: str, variables: dict | None = None) -> tuple[int, dict]:
    """Make a GitHub GraphQL API request."""
    token = _get_token()
    if not token:
        return 401, {"error": "GITHUB_TOKEN not set"}

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    body = json.dumps(payload).encode()
    req = urllib.request.Request(GITHUB_GRAPHQL, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            response_body = json.loads(resp.read().decode())
            if "errors" in response_body:
                logger.error("GraphQL errors: %s", response_body["errors"])
                return 400, response_body
            return 200, response_body.get("data", {})
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else ""
        logger.error("GraphQL error: %d: %s", e.code, error_body[:300])
        return e.code, {"error": error_body[:300]}
    except Exception as e:
        logger.error("GraphQL request failed: %s", e)
        return 500, {"error": str(e)}


def merge_pull_request(owner: str, repo: str, pr_number: int, merge_method: str = "squash",
                       commit_title: str = "", commit_message: str = "") -> dict:
    """Merge a pull request via GitHub REST API."""
    path = f"/repos/{owner}/{repo}/pulls/{pr_number}/merge"
    data: dict = {"merge_method": merge_method}
    if commit_title:
        data["commit_title"] = commit_title
    if commit_message:
        data["commit_message"] = commit_message

    status, response = _github_rest("PUT", path, data)

    if status == 200:
        logger.info("PR #%d merged (sha: %s)", pr_number, response.get("sha", "")[:8])
        return {"merged": True, "sha": response.get("sha", ""), "message": response.get("message", "")}
    elif status == 405:
        return {"merged": False, "error": response.get("message", "Not mergeable")}
    elif status == 409:
        return {"merged": False, "error": "Merge conflict"}
    else:
        return {"merged": False, "error": response.get("message", f"HTTP {status}")}


def approve_pull_request(owner: str, repo: str, pr_number: int, body: str = "") -> dict:
    """Approve a pull request (create an APPROVE review)."""
    path = f"/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
    data = {"event": "APPROVE", "body": body or "Branch Evaluation Agent: PASS. Auto-approved."}

    status, response = _github_rest("POST", path, data)
    if status in (200, 201):
        logger.info("PR #%d approved", pr_number)
        return {"approved": True}
    else:
        return {"approved": False, "error": response.get("message", f"HTTP {status}")}


def close_issue(owner: str, repo: str, issue_number: int) -> dict:
    """Close a GitHub issue as completed."""
    path = f"/repos/{owner}/{repo}/issues/{issue_number}"
    data = {"state": "closed", "state_reason": "completed"}

    status, response = _github_rest("PATCH", path, data)
    if status == 200:
        logger.info("Issue #%d closed as completed", issue_number)
        return {"closed": True}
    else:
        return {"closed": False, "error": response.get("message", f"HTTP {status}")}


def move_issue_to_done(owner: str, repo: str, issue_number: int, project_number: int | None = None) -> dict:
    """Move an issue to DONE status in GitHub Projects V2.

    Uses GraphQL to find the project, locate the issue item, find the Status
    field's DONE option, and update the field value.
    """
    issue_node_id = _get_issue_node_id(owner, repo, issue_number)
    if not issue_node_id:
        return {"moved": False, "error": f"Issue #{issue_number} not found"}

    project_data = _find_project_item(owner, issue_node_id, project_number)
    if not project_data:
        return {"moved": False, "error": "Issue not found in any project"}

    status_field = _get_status_field(project_data["project_id"])
    if not status_field:
        return {"moved": False, "error": "Status field not found in project"}

    done_option_id = status_field.get("done_option_id")
    if not done_option_id:
        return {"moved": False, "error": "DONE option not found in Status field"}

    success = _update_item_status(
        project_data["project_id"], project_data["item_id"],
        status_field["field_id"], done_option_id,
    )

    if success:
        logger.info("Issue #%d moved to DONE in '%s'", issue_number, project_data["project_title"])
        return {"moved": True, "project_title": project_data["project_title"]}
    else:
        return {"moved": False, "error": "Failed to update status"}


def _get_issue_node_id(owner: str, repo: str, issue_number: int) -> str:
    """Get the GraphQL node ID for an issue."""
    query = """
    query($owner: String!, $repo: String!, $number: Int!) {
      repository(owner: $owner, name: $repo) {
        issue(number: $number) { id }
      }
    }
    """
    status, data = _github_graphql(query, {"owner": owner, "repo": repo, "number": issue_number})
    if status == 200:
        return data.get("repository", {}).get("issue", {}).get("id", "")
    return ""


def _find_project_item(owner: str, issue_node_id: str, project_number: int | None = None) -> dict | None:
    """Find the issue's item in a GitHub Project V2."""
    query = """
    query($owner: String!, $first: Int!) {
      user(login: $owner) {
        projectsV2(first: $first) {
          nodes {
            id
            title
            number
            items(first: 100) {
              nodes {
                id
                content { ... on Issue { id } }
              }
            }
          }
        }
      }
    }
    """
    status, data = _github_graphql(query, {"owner": owner, "first": 10})

    if status != 200:
        query_org = """
        query($owner: String!, $first: Int!) {
          organization(login: $owner) {
            projectsV2(first: $first) {
              nodes {
                id
                title
                number
                items(first: 100) {
                  nodes {
                    id
                    content { ... on Issue { id } }
                  }
                }
              }
            }
          }
        }
        """
        status, data = _github_graphql(query_org, {"owner": owner, "first": 10})
        if status != 200:
            return None
        projects = data.get("organization", {}).get("projectsV2", {}).get("nodes", [])
    else:
        projects = data.get("user", {}).get("projectsV2", {}).get("nodes", [])

    for project in projects:
        if project_number and project.get("number") != project_number:
            continue
        for item in project.get("items", {}).get("nodes", []):
            content = item.get("content", {})
            if content and content.get("id") == issue_node_id:
                return {
                    "project_id": project["id"],
                    "item_id": item["id"],
                    "project_title": project.get("title", ""),
                }
    return None


def _get_status_field(project_id: str) -> dict | None:
    """Get the Status field ID and DONE option ID from a project."""
    query = """
    query($projectId: ID!) {
      node(id: $projectId) {
        ... on ProjectV2 {
          fields(first: 20) {
            nodes {
              ... on ProjectV2SingleSelectField {
                id
                name
                options { id name }
              }
            }
          }
        }
      }
    }
    """
    status, data = _github_graphql(query, {"projectId": project_id})
    if status != 200:
        return None

    fields = data.get("node", {}).get("fields", {}).get("nodes", [])
    for field in fields:
        if field.get("name", "").lower() == "status":
            options = field.get("options", [])
            done_option = next(
                (opt for opt in options if opt.get("name", "").lower() in ("done", "completed", "closed")),
                None,
            )
            if done_option:
                return {"field_id": field["id"], "done_option_id": done_option["id"]}
    return None


def _update_item_status(project_id: str, item_id: str, field_id: str, option_id: str) -> bool:
    """Update a project item's single-select field value."""
    mutation = """
    mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
      updateProjectV2ItemFieldValue(
        input: {
          projectId: $projectId
          itemId: $itemId
          fieldId: $fieldId
          value: { singleSelectOptionId: $optionId }
        }
      ) { projectV2Item { id } }
    }
    """
    status, data = _github_graphql(mutation, {
        "projectId": project_id, "itemId": item_id,
        "fieldId": field_id, "optionId": option_id,
    })
    return status == 200


def handle_auto_merge(owner: str, repo: str, pr_number: int, issue_number: int,
                      aggregate_score: float, verdict: str, engineering_level: int = 3) -> dict:
    """Full auto-merge flow: approve -> merge -> close issue -> move to DONE.

    Only executes if verdict=PASS, score>=8.0, level<=2.
    """
    result = {
        "auto_merge_attempted": False, "approved": False,
        "merged": False, "issue_closed": False, "issue_moved_to_done": False,
    }

    if verdict != "PASS" or aggregate_score < 8.0 or engineering_level > 2:
        logger.info("Auto-merge not eligible: verdict=%s, score=%.1f, level=%d",
                    verdict, aggregate_score, engineering_level)
        return result

    result["auto_merge_attempted"] = True

    approve_result = approve_pull_request(owner, repo, pr_number,
        body=f"Branch Evaluation Agent: PASS ({aggregate_score:.1f}/10). Auto-approved.")
    result["approved"] = approve_result.get("approved", False)
    if not result["approved"]:
        result["error"] = approve_result.get("error", "Approval failed")
        return result

    merge_result = merge_pull_request(owner, repo, pr_number, merge_method="squash",
        commit_title=f"feat(GH-{issue_number}): auto-merged by evaluation agent (score {aggregate_score:.1f})")
    result["merged"] = merge_result.get("merged", False)
    result["merge_sha"] = merge_result.get("sha", "")
    if not result["merged"]:
        result["error"] = merge_result.get("error", "Merge failed")
        return result

    close_result = close_issue(owner, repo, issue_number)
    result["issue_closed"] = close_result.get("closed", False)

    move_result = move_issue_to_done(owner, repo, issue_number)
    result["issue_moved_to_done"] = move_result.get("moved", False)
    if move_result.get("project_title"):
        result["project_title"] = move_result["project_title"]

    logger.info("Auto-merge complete: PR #%d merged, issue #%d %s",
                pr_number, issue_number,
                "moved to DONE" if result["issue_moved_to_done"] else "closed")
    return result
