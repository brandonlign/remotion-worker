# Security

## Public information

The worker repository, workflow definitions, branch names, pull requests, job IDs, workflow duration, and generic success/failure messages are public.

Render requests should therefore contain only:

- an opaque job ID
- an exact private-source commit SHA
- a revision number

Do not put video topics, scripts, composition names, asset names, customer information, or private URLs in a render request.

## Private information

Private source code is checked out only on the temporary GitHub-hosted runner. Render output and detailed logs are uploaded directly to private Google Drive storage. The workflow intentionally does not use `actions/upload-artifact` for private output.

## Secret scope

- `SOURCE_REPO_TOKEN` should be a fine-grained token restricted to one private source repository with contents read-only.
- `RCLONE_CONFIG_B64` grants access to the authorized Google Drive account and must be treated as a password.
- Secrets are not exposed as job-wide environment variables. They are passed only to the checkout or upload step that requires them.
- The private checkout uses `persist-credentials: false`.

## Trigger restrictions

The public render/finalize/preview jobs run only after the secret-free `Worker CI`
workflow has passed and all of these are true:

- the triggering workflow run came from a pull request;
- the pull request branch is inside this repository, not a fork;
- the branch name starts with `render/`;
- the trusted main-branch workflow reads only the request JSON from the exact
  pull-request diff;
- `jobs/request.json` (or the explicitly selected finalize/preview request)
  changed in the allowed request-only scope.

The secret-bearing workflows run from `workflow_run` on trusted worker code.
They never check out or execute pull-request worker code. Do not use
`pull_request_target` for this workflow.

## Trusted-source assumption

The private source repository is trusted code. Its dependency installation, project checks, and Remotion bundle execute on the runner. Do not render commits from untrusted contributors without reviewing them first.

## Collaborator warning

Anyone with write access to this public repository can create an internal render branch and cause the workflow to use configured secrets. Keep write access limited to trusted accounts and installed applications.

## Incident response

If a secret may have appeared in a public log or untrusted workflow run:

1. Cancel active workflows.
2. Revoke the fine-grained GitHub token.
3. Revoke the Google OAuth token stored in the rclone configuration.
4. Replace both repository secrets.
5. Review recent workflow runs and Drive uploads.
