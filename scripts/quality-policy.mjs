export const resolveQualityPolicy = (job, config) => {
  const format = job?.format ?? "short";
  if (format !== "short" && format !== "long") {
    throw new Error(`Unsupported Telic format: ${format}`);
  }

  const quality = format === "long" ? config?.longForm?.quality : config?.quality;
  if (!quality || typeof quality !== "object") {
    throw new Error(`The private config has no ${format} quality policy.`);
  }

  const expectedWidth = format === "long" ? 1920 : 1080;
  const expectedHeight = format === "long" ? 1080 : 1920;
  const minimumDurationSeconds = format === "long"
    ? Number(config?.longForm?.minimumDurationSeconds ?? 240)
    : 10;
  const maximumDurationSeconds = Number(quality.maximumDurationSeconds);
  const maximumFrames = Number(quality.maximumFrames) || (format === "long" ? 48 : 20);

  if (!Number.isFinite(minimumDurationSeconds) || minimumDurationSeconds <= 0) {
    throw new Error(`${format} minimum duration policy is invalid.`);
  }
  if (!Number.isFinite(maximumDurationSeconds) || maximumDurationSeconds <= minimumDurationSeconds) {
    throw new Error(`${format} maximum duration policy is invalid.`);
  }

  return {
    format,
    quality,
    expectedWidth,
    expectedHeight,
    minimumDurationSeconds,
    maximumDurationSeconds,
    maximumFrames,
  };
};
