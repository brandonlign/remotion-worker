# Private Source Contract

The worker treats the private repository as trusted render input. The repository must contain a root-level `remotion-worker.json` file.

## Fields

### `entryPoint`

Relative path to the Remotion entry point, usually `src/index.ts`.

### `compositionId`

Exact Remotion composition ID to render.

### `outputName`

Filename stem for the full-quality MP4. Only letters, numbers, underscores, and hyphens are accepted.

### `installCommand`

One-line command run from the private repository root before checks. Defaults to:

```text
npm ci --no-audit --no-fund
```

### `checkCommand`

One-line command run after installation. Defaults to:

```text
npm run lint
```

### `crf`

H.264 constant-rate-factor value from 1 through 51. Lower values produce higher quality and larger files. The default is 23.

## Example

```json
{
  "entryPoint": "src/index.ts",
  "compositionId": "TheOldLLMAd",
  "outputName": "telic-review",
  "installCommand": "npm ci --no-audit --no-fund",
  "checkCommand": "npm run lint",
  "crf": 23
}
```

The public request does not specify these values. This keeps composition names and video details private and ensures that each private commit fully defines its own render.
